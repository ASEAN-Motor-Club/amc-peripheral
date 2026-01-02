"""
MotorTown game database query module.

Provides structured queries for vehicle, parts, and cargo data extracted from game files.
"""

import sqlite3
import os
import logging
from typing import Optional, Dict, Any, List

log = logging.getLogger(__name__)

GAME_DB_PATH = os.environ.get("GAME_DB_PATH", "/var/lib/motortown/gamedata.db")
EXPECTED_SCHEMA_VERSION = 4

# Raw query safety settings
BLOCKED_KEYWORDS = ["ATTACH", "PRAGMA", "LOAD_EXTENSION", "DETACH"]
MAX_ROWS = 100
QUERY_TIMEOUT_MS = 5000


def execute_raw_query(sql: str) -> dict:
    """
    Execute a raw SQL query against the game database.
    
    The database is opened in read-only mode for safety.
    Only SELECT queries are allowed with additional keyword blocking.
    
    Args:
        sql: SQL query string
        
    Returns:
        Dict with 'results' list or 'error' string
    """
    
    sql = sql.strip()
    sql_upper = sql.upper()
    
    # Block dangerous keywords
    for keyword in BLOCKED_KEYWORDS:
        if keyword in sql_upper:
            return {"error": f"Query contains blocked keyword: {keyword}"}
    
    # Must be a SELECT query
    if not sql_upper.startswith("SELECT"):
        return {"error": "Only SELECT queries are allowed"}
    
    try:
        # Open in read-only mode (uri=True required for mode parameter)
        conn = sqlite3.connect(
            f"file:{GAME_DB_PATH}?mode=ro",
            uri=True,
            timeout=QUERY_TIMEOUT_MS / 1000
        )
        conn.row_factory = sqlite3.Row
        
        cursor = conn.cursor()
        cursor.execute(sql)
        
        # Fetch with row limit
        rows = cursor.fetchmany(MAX_ROWS)
        results = [dict(row) for row in rows]
        
        # Check if there are more rows
        has_more = cursor.fetchone() is not None
        
        conn.close()
        
        if has_more:
            return {
                "results": results,
                "count": len(results),
                "truncated": True,
                "note": f"Results limited to {MAX_ROWS} rows"
            }
        else:
            return {"results": results, "count": len(results)}
        
    except sqlite3.OperationalError as e:
        return {"error": f"SQL error: {str(e)}"}
    except Exception as e:
        log.error(f"Raw query failed: {e}")
        return {"error": f"Query failed: {str(e)}"}


def get_connection() -> sqlite3.Connection:
    """Get database connection with row factory for dict-like access."""
    if not os.path.exists(GAME_DB_PATH):
        raise FileNotFoundError(f"Game database not found at {GAME_DB_PATH}")
    
    conn = sqlite3.connect(GAME_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def validate_schema() -> bool:
    """Check if schema version matches expected version."""
    try:
        with get_connection() as conn:
            result = conn.execute("SELECT version FROM schema_version").fetchone()
            if result:
                version = result[0]
                if version != EXPECTED_SCHEMA_VERSION:
                    log.warning(
                        f"Schema version mismatch: expected {EXPECTED_SCHEMA_VERSION}, got {version}"
                    )
                    return False
                return True
            return False
    except Exception as e:
        log.error(f"Schema validation failed: {e}")
        return False


def get_schema_description() -> str:
    """
    Generate a comprehensive description of the database schema for LLM tool descriptions.
    
    Uses PRAGMA queries to introspect tables and views, providing column names and types.
    
    Returns:
        Formatted schema description string
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            
            # Get all tables and views
            tables_and_views = cursor.execute("""
                SELECT name, type FROM sqlite_master 
                WHERE type IN ('table', 'view') 
                AND name NOT LIKE 'sqlite_%'
                ORDER BY type DESC, name
            """).fetchall()
            
            schema_parts = ["MotorTown Game Database Schema:\n"]
            
            for table_name, obj_type in tables_and_views:
                # Get column info using PRAGMA
                # pyrefly: ignore [sql-injection]
                columns = cursor.execute(f"PRAGMA table_info({table_name})").fetchall()
                
                column_list = []
                for col in columns:
                    # col format: (cid, name, type, notnull, dflt_value, pk)
                    col_name = col[1]
                    col_type = col[2]
                    # pyrefly: ignore [bad-argument-type]
                    column_list.append(f"{col_name} ({col_type})")
                
                obj_label = "VIEW" if obj_type == "view" else "TABLE"
                # pyrefly: ignore [bad-argument-type]
                schema_parts.append(f"\n{obj_label}: {table_name}")
                # pyrefly: ignore [bad-argument-type]
                schema_parts.append(f"  Columns: {', '.join(column_list)}")
            
            return "\n".join(schema_parts)
            
    except Exception as e:
        log.error(f"Schema description generation failed: {e}")
        return "Schema introspection failed - using read-only database with vehicles, vehicle_parts, cargos, and views"


def query_vehicle(search_term: str, filters: Optional[Dict[str, Any]] = None) -> List[Dict]:
    """
    Query vehicles by name or ID.
    
    Args:
        search_term: Name or ID to search for
        filters: Optional dict with keys like 'vehicle_type', 'max_cost'
    
    Returns:
        List of vehicle dicts
    """
    filters = filters or {}
    
    sql = """
        SELECT id, name, vehicle_type, truck_class, cost, comport
        FROM vehicles
        WHERE (id LIKE ? OR name LIKE ?)
          AND (is_hidden = 0 OR is_hidden IS NULL)
          AND (is_disabled = 0 OR is_disabled IS NULL)
    """
    params = [f"%{search_term}%", f"%{search_term}%"]
    
    if filters.get("vehicle_type"):
        sql += " AND vehicle_type = ?"
        params.append(filters["vehicle_type"])
    
    if filters.get("max_cost"):
        sql += " AND cost <= ?"
        params.append(filters["max_cost"])
    
    sql += " ORDER BY cost LIMIT 10"
    
    try:
        with get_connection() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]
    except Exception as e:
        log.error(f"Vehicle query failed: {e}")
        return []


def query_cargo(search_term: str, filters: Optional[Dict[str, Any]] = None) -> List[Dict]:
    """
    Query cargo with resolved weights from active_cargos view.
    
    Args:
        search_term: Name or ID to search for
        filters: Optional dict with keys like 'cargo_type', 'min_weight'
    
    Returns:
        List of cargo dicts
    """
    filters = filters or {}
    
    sql = """
        SELECT id, name, cargo_type, actual_weight_kg, 
               payment_per_km, volume_size
        FROM active_cargos
        WHERE (id LIKE ? OR name LIKE ?)
    """
    params = [f"%{search_term}%", f"%{search_term}%"]
    
    if filters.get("cargo_type"):
        sql += " AND cargo_type = ?"
        params.append(filters["cargo_type"])
    
    if filters.get("min_weight"):
        sql += " AND actual_weight_kg >= ?"
        params.append(filters["min_weight"])
    
    sql += " ORDER BY actual_weight_kg DESC LIMIT 10"
    
    try:
        with get_connection() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]
    except Exception as e:
        log.error(f"Cargo query failed: {e}")
        return []


def query_part(search_term: str, filters: Optional[Dict[str, Any]] = None) -> List[Dict]:
    """
    Query vehicle parts.
    
    Args:
        search_term: Name or ID to search for
        filters: Optional dict with keys like 'part_type', 'max_cost'
    
    Returns:
        List of part dicts
    """
    filters = filters or {}
    
    sql = """
        SELECT id, name, part_type, cost, mass_kg
        FROM vehicle_parts
        WHERE (id LIKE ? OR name LIKE ?)
          AND (is_hidden = 0 OR is_hidden IS NULL)
    """
    params = [f"%{search_term}%", f"%{search_term}%"]
    
    if filters.get("part_type"):
        sql += " AND part_type = ?"
        params.append(filters["part_type"])
    
    if filters.get("max_cost"):
        sql += " AND cost <= ?"
        params.append(filters["max_cost"])
    
    sql += " ORDER BY cost LIMIT 10"
    
    try:
        with get_connection() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]
    except Exception as e:
        log.error(f"Part query failed: {e}")
        return []


def query_heaviest_cargos(limit: int = 5) -> List[Dict]:
    """Get the heaviest cargo items."""
    try:
        with get_connection() as conn:
            return [dict(row) for row in conn.execute("""
                SELECT id, name, cargo_type, actual_weight_kg
                FROM active_cargos
                ORDER BY actual_weight_kg DESC
                LIMIT ?
            """, (limit,)).fetchall()]
    except Exception as e:
        log.error(f"Heaviest cargo query failed: {e}")
        return []


def query_cargo_by_space_type(space_type: str) -> List[Dict]:
    """Get cargo that fits in a specific space type (e.g., 'Flatbed', 'Box')."""
    try:
        with get_connection() as conn:
            return [dict(row) for row in conn.execute("""
                SELECT DISTINCT c.id, c.name, c.actual_weight_kg, c.cargo_type
                FROM active_cargos c
                JOIN cargo_space_types cst ON c.id = cst.cargo_id
                WHERE cst.space_type = ?
                ORDER BY c.actual_weight_kg DESC
                LIMIT 20
            """, (space_type,)).fetchall()]
    except Exception as e:
        log.error(f"Cargo by space type query failed: {e}")
        return []


def handle_game_query(query_type: str, search_term: Optional[str] = None, 
                     filters: Optional[Dict[str, Any]] = None) -> str:
    """
    Main query handler for AI tool calls.
    
    Args:
        query_type: One of 'vehicle_info', 'cargo_info', 'part_info', 
                   'heaviest_cargo', 'cargo_by_space'
        search_term: Search string for info queries
        filters: Additional filters
    
    Returns:
        JSON string with results or error message
    """
    import json
    
    try:
        if query_type == "vehicle_info":
            if not search_term:
                return json.dumps({"error": "search_term required"})
            results = query_vehicle(search_term, filters)
            return json.dumps({"vehicles": results}, indent=2)
        
        elif query_type == "cargo_info":
            if not search_term:
                return json.dumps({"error": "search_term required"})
            results = query_cargo(search_term, filters)
            return json.dumps({"cargo": results}, indent=2)
        
        elif query_type == "part_info":
            if not search_term:
                return json.dumps({"error": "search_term required"})
            results = query_part(search_term, filters)
            return json.dumps({"parts": results}, indent=2)
        
        elif query_type == "heaviest_cargo":
            limit = filters.get("limit", 5) if filters else 5
            results = query_heaviest_cargos(limit)
            return json.dumps({"cargo": results}, indent=2)
        
        elif query_type == "cargo_by_space":
            space_type = filters.get("space_type") if filters else None
            if not space_type:
                return json.dumps({"error": "space_type filter required"})
            results = query_cargo_by_space_type(space_type)
            return json.dumps({"cargo": results}, indent=2)
        
        else:
            return json.dumps({"error": f"Unknown query_type: {query_type}"})
    
    except Exception as e:
        log.error(f"Query handler error: {e}")
        return json.dumps({"error": str(e)})
