"""
AMC Backend PostgreSQL query module.

Provides read-only SQL access to the amc-backend database
for the agentic Discord bot. Connects over Tailscale to the
PostgreSQL instance running in the amc-backend container.
"""

import json
import logging
import os
from typing import Optional

from amc_peripheral.settings import BACKEND_DB_URL

log = logging.getLogger(__name__)

# Safety settings
BLOCKED_KEYWORDS = [
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
    "TRUNCATE", "GRANT", "REVOKE", "COPY", "VACUUM", "EXECUTE",
    "CALL", "DO", "PREPARE", "DEALLOCATE", "LISTEN", "NOTIFY",
    "LOCK", "DISCARD", "RESET", "SET ROLE", "SET SESSION",
    "LOAD", "REINDEX", "CLUSTER", "REFRESH", "COMMENT",
]
MAX_ROWS = 100
QUERY_TIMEOUT_MS = 30000

# Cache for schema description
_schema_cache: Optional[str] = None


def _get_connection():
    """Create a new database connection with safety settings."""
    import psycopg2

    if not BACKEND_DB_URL:
        raise RuntimeError("BACKEND_DB_URL environment variable not set")

    conn = psycopg2.connect(
        BACKEND_DB_URL,
        options=f"-c statement_timeout={QUERY_TIMEOUT_MS} -c default_transaction_read_only=on",
    )
    conn.set_session(readonly=True, autocommit=True)
    return conn


def _load_knowledge_guide() -> str | None:
    """Load the curated knowledge guide from the knowledge_guides directory."""
    guide_path = os.path.join(
        os.path.dirname(__file__), "knowledge_guides", "backend_db_guide.md"
    )
    try:
        with open(guide_path, "r") as f:
            content = f.read()
        log.info(f"Backend DB knowledge guide loaded: {len(content)} chars from {guide_path}")
        return content
    except FileNotFoundError:
        log.info(f"No knowledge guide at {guide_path}, falling back to schema introspection")
        return None
    except Exception as e:
        log.warning(f"Failed to load knowledge guide: {e}")
        return None


def get_schema_description() -> str:
    """
    Get a description of the database for LLM tool descriptions.

    Prefers a curated knowledge guide (knowledge_guides/backend_db_guide.md) which includes
    annotated columns, relationships, domain context, and query recipes. Falls back to
    information_schema introspection if the guide is not available.

    Returns cached result after first call.
    """
    global _schema_cache

    if _schema_cache is not None:
        return _schema_cache

    # Try curated guide first
    guide = _load_knowledge_guide()
    if guide:
        _schema_cache = guide
        return _schema_cache

    if not BACKEND_DB_URL:
        return "Backend database not configured (BACKEND_DB_URL not set)"

    # Fallback: information_schema introspection
    try:

        conn = _get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """)
        tables = [row[0] for row in cursor.fetchall()]

        schema_parts = ["AMC Backend Database Schema (PostgreSQL):\n"]
        schema_parts.append("NOTE: Finance tables (amc_finance_*) are access-restricted.\n")

        for table_name in tables:
            cursor.execute("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s
                ORDER BY ordinal_position
            """, (table_name,))
            columns = cursor.fetchall()

            col_list = []
            for col_name, data_type, nullable in columns:
                null_marker = "" if nullable == "YES" else " NOT NULL"
                col_list.append(f"{col_name} ({data_type}{null_marker})")

            schema_parts.append(f"\nTABLE: {table_name}")
            schema_parts.append(f"  Columns: {', '.join(col_list)}")

        conn.close()
        _schema_cache = "\n".join(schema_parts)
        return _schema_cache

    except Exception as e:
        log.error(f"Backend schema introspection failed: {e}")
        return f"Backend schema introspection failed: {e}"


def execute_query(sql: str) -> dict:
    """
    Execute a read-only SELECT query against the backend database.

    Multiple layers of protection:
    1. Application-level: keyword blocking, SELECT-only check
    2. Connection-level: default_transaction_read_only=on, session readonly
    3. Database-level: amc_bot_reader role has SELECT-only grants
    4. Row-level: RLS policies block access to finance tables

    Args:
        sql: SQL query string

    Returns:
        Dict with 'results' list and 'count', or 'error' string
    """
    sql = sql.strip().rstrip(";")
    sql_upper = sql.upper()

    # Block dangerous keywords
    for keyword in BLOCKED_KEYWORDS:
        # Check for keyword as a word boundary (not part of another word)
        if keyword in sql_upper:
            # More precise check: ensure it's not part of a column name
            import re
            if re.search(rf'\b{keyword}\b', sql_upper):
                return {"error": f"Query contains blocked keyword: {keyword}"}

    # Must be a SELECT or WITH (CTE) query
    if not (sql_upper.startswith("SELECT") or sql_upper.startswith("WITH")):
        return {"error": "Only SELECT queries are allowed (WITH/CTE also supported)"}

    if not BACKEND_DB_URL:
        return {"error": "Backend database not configured (BACKEND_DB_URL not set)"}

    try:
        import psycopg2
        import psycopg2.extras

        conn = _get_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Auto-add LIMIT if not present and not an aggregate query
        sql_to_execute = sql
        if "LIMIT" not in sql_upper and not any(
            agg in sql_upper for agg in ["COUNT(", "SUM(", "AVG(", "MIN(", "MAX(", "GROUP BY"]
        ):
            sql_to_execute = f"{sql} LIMIT {MAX_ROWS}"

        cursor.execute(sql_to_execute)

        rows = cursor.fetchmany(MAX_ROWS)
        results = [dict(row) for row in rows]

        # Check if there are more rows
        has_more = cursor.fetchone() is not None

        conn.close()

        response = {"results": results, "count": len(results)}
        if has_more:
            response["truncated"] = True
            response["note"] = f"Results limited to {MAX_ROWS} rows. Use LIMIT/OFFSET for pagination."

        return response

    except Exception as e:
        error_msg = str(e).split("\n")[0]  # First line only
        log.error(f"Backend query failed: {e}")
        return {"error": f"Query failed: {error_msg[:300]}"}


def format_results(result: dict) -> str:
    """Format query results as a JSON string, truncated for LLM context."""
    try:
        output = json.dumps(result, default=str)
        # Cap output at 4000 chars to avoid overwhelming the LLM
        if len(output) > 4000:
            return output[:4000] + '... (truncated)'
        return output
    except Exception as e:
        return json.dumps({"error": f"Failed to format results: {str(e)}"})
