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


def _load_knowledge_guide() -> str | None:
    """Load the curated knowledge guide from the knowledge_guides directory."""
    guide_path = os.path.join(os.path.dirname(__file__), "knowledge_guides", "game_db_guide.md")
    try:
        with open(guide_path, "r") as f:
            content = f.read()
        log.info(f"Game DB knowledge guide loaded: {len(content)} chars from {guide_path}")
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
    
    Prefers a curated knowledge guide (knowledge_guides/game_db_guide.md) which includes
    annotated columns, domain context, enum values, and query recipes. Falls back to
    PRAGMA-based schema introspection if the guide is not available.
    
    Returns:
        Formatted schema/guide description string
    """
    # Try curated guide first
    guide = _load_knowledge_guide()
    if guide:
        return guide

    # Fallback: PRAGMA introspection
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


def lookup_vehicle(name: str) -> dict:
    """Full vehicle spec: type, cost, weight, engine, cargo space, drivetrain, capabilities."""
    try:
        with get_connection() as conn:
            row = conn.execute("""
                SELECT v.id, v.name, v.vehicle_type, v.truck_class, v.cost,
                       v.is_taxiable, v.is_limoable, v.is_busable, v.is_race_car,
                       v.can_haul_trailer, v.has_fuel_pump,
                       v.delivery_payment_multiplier, v.delivery_base_payment,
                       COALESCE(vw.chassis_mass_kg, 0) as chassis_mass_kg,
                       COALESCE(vw.parts_weight_kg, 0) as parts_weight_kg,
                       COALESCE(vw.total_weight_kg, 0) as total_weight_kg
                FROM vehicles v
                LEFT JOIN vehicle_weights vw ON v.id = vw.vehicle_id
                WHERE (v.id LIKE ? OR v.name LIKE ?)
                  AND (v.is_hidden = 0 OR v.is_hidden IS NULL)
                  AND (v.is_disabled = 0 OR v.is_disabled IS NULL)
                ORDER BY v.cost
                LIMIT 1
            """, (f"%{name}%", f"%{name}%")).fetchone()

            if not row:
                return {"error": f"No vehicle found matching '{name}'"}

            vehicle = dict(row)

            # Engine info from default parts
            engine_row = conn.execute("""
                SELECT dp.part_id
                FROM vehicle_default_parts dp
                WHERE dp.vehicle_id = ? AND dp.slot = 'Engine'
                LIMIT 1
            """, (vehicle["id"],)).fetchone()
            if engine_row:
                import re
                engine_id = engine_row[0]
                m = re.search(r"(\d+)HP", engine_id)
                vehicle["engine"] = engine_id
                vehicle["engine_hp"] = int(m.group(1)) if m else None

            # Drivetrain from LSD parts
            lsd_rows = conn.execute("""
                SELECT dp.slot FROM vehicle_default_parts dp
                WHERE dp.vehicle_id = ? AND dp.slot LIKE 'LSD%'
            """, (vehicle["id"],)).fetchall()
            lsd_slots = {r[0] for r in lsd_rows}
            has_front = any(s in lsd_slots for s in ("LSD1", "LSD_Front"))
            has_rear = any(s in lsd_slots for s in ("LSD0", "LSD_Rear", "LSD"))
            if has_front and has_rear:
                vehicle["drivetrain"] = "AWD"
            elif has_front:
                vehicle["drivetrain"] = "FWD"
            elif has_rear:
                vehicle["drivetrain"] = "RWD"
            else:
                vehicle["drivetrain"] = ""

            # Cargo space from view
            cargo_row = conn.execute("""
                SELECT cargo_space_type, length_m, width_m, height_m,
                       volume_m3, dump_volume_kl
                FROM vehicles_with_cargo_space WHERE id = ?
            """, (vehicle["id"],)).fetchone()
            if cargo_row:
                vehicle["cargo_space"] = {
                    "type": cargo_row[0] or "",
                    "length_m": cargo_row[1] or 0,
                    "width_m": cargo_row[2] or 0,
                    "height_m": cargo_row[3] or 0,
                    "volume_m3": cargo_row[4] or 0,
                    "dump_volume_kl": cargo_row[5] or 0,
                }

            # Tags
            tag_rows = conn.execute(
                "SELECT DISTINCT tag FROM vehicle_tags WHERE vehicle_id = ?",
                (vehicle["id"],),
            ).fetchall()
            vehicle["tags"] = [r[0] for r in tag_rows]

            return vehicle
    except Exception as e:
        log.error(f"lookup_vehicle failed: {e}")
        return {"error": str(e)}


def lookup_cargo(name: str) -> dict:
    """Full cargo spec: type, weight, payment, compatible space types, production chains."""
    try:
        with get_connection() as conn:
            row = conn.execute("""
                SELECT c.id, c.name, c.cargo_type, c.volume_size,
                       COALESCE(cw.total_weight_kg, c.weight_max, 0) as weight_kg,
                       c.payment_per_km, c.payment_multiplier, c.base_payment,
                       c.min_delivery_distance, c.max_delivery_distance,
                       c.allow_stacking, c.fragile
                FROM cargos c
                LEFT JOIN cargo_weights cw ON c.id = cw.cargo_id
                WHERE (c.id LIKE ? OR c.name LIKE ?)
                  AND (c.is_deprecated = 0 OR c.is_deprecated IS NULL)
                LIMIT 1
            """, (f"%{name}%", f"%{name}%")).fetchone()

            if not row:
                return {"error": f"No cargo found matching '{name}'"}

            cargo = dict(row)

            # Compatible space types
            st_rows = conn.execute(
                "SELECT space_type FROM cargo_space_types WHERE cargo_id = ?",
                (cargo["id"],),
            ).fetchall()
            cargo["space_types"] = [r[0] for r in st_rows]

            # Production sources
            prod_rows = conn.execute("""
                SELECT dp.id as location, pc.production_time_seconds
                FROM production_outputs po
                JOIN production_configs pc ON po.production_config_id = pc.id
                JOIN delivery_points dp ON pc.delivery_point_id = dp.id
                WHERE po.cargo_id = ?
            """, (cargo["id"],)).fetchall()
            produced_at = []
            for pr in prod_rows:
                inputs = conn.execute("""
                    SELECT pi.cargo_id, pi.quantity
                    FROM production_inputs pi
                    JOIN production_configs pc ON pi.production_config_id = pc.id
                    WHERE pc.delivery_point_id = ? AND pc.production_time_seconds = ?
                """, (pr[0], pr[1])).fetchall()
                produced_at.append({
                    "location": pr[0],
                    "inputs": [{"cargo_id": r[0], "quantity": r[1]} for r in inputs],
                    "time_seconds": pr[1],
                })
            cargo["produced_at"] = produced_at

            return cargo
    except Exception as e:
        log.error(f"lookup_cargo failed: {e}")
        return {"error": str(e)}


def compare_vehicles(names: list[str]) -> list[dict]:
    """Side-by-side comparison of multiple vehicles (all key specs)."""
    results = []
    for vehicle_name in names:
        result = lookup_vehicle(vehicle_name)
        if "error" not in result:
            results.append(result)
    return results


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
