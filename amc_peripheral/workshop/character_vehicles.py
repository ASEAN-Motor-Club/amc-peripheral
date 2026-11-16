"""Fixed-query CharacterVehicle adapter.

This deliberately does not expose the generic backend SQL interface. Only six
rendering fields plus the JSON config are read, every statement is parameterized,
and the endpoint remains disabled unless an operator explicitly enables it.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .payloads import normalize_character_vehicle


class CharacterVehicleUnavailable(Exception):
    pass


class CharacterVehicleRepository:
    def __init__(self, dsn: str | None, *, enabled: bool = False):
        self.dsn = dsn
        self.enabled = enabled

    def _connect(self):
        if not self.enabled or not self.dsn:
            raise CharacterVehicleUnavailable
        import psycopg2

        conn = psycopg2.connect(
            self.dsn,
            options=(
                "-c statement_timeout=5000 "
                "-c default_transaction_read_only=on"
            ),
        )
        conn.set_session(readonly=True, autocommit=True)
        return conn

    def _row(self, vehicle_id: int) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, vehicle_id, config "
                    "FROM amc_charactervehicle WHERE id = %s LIMIT 1",
                    (vehicle_id,),
                )
                row = cur.fetchone()
        finally:
            conn.close()
        if not row:
            return None
        config = row[2] if isinstance(row[2], dict) else {}
        canonical = json.dumps(config, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False).encode()
        return {
            "id": int(row[0]),
            "vehicle_id": int(row[1] or 0),
            "config": config,
            "config_hash": hashlib.sha256(canonical).hexdigest(),
        }

    def get(self, vehicle_id: int) -> dict[str, Any] | None:
        row = self._row(vehicle_id)
        return row

    def meta(self, vehicle_id: int) -> dict[str, Any] | None:
        row = self._row(vehicle_id)
        if not row:
            return None
        config = row["config"]
        return {
            "id": row["id"],
            "vehicleKey": str(config.get("VehicleName") or ""),
            "configHash": row["config_hash"],
            "visibility": "public",
        }

    def normalize(self, row: dict[str, Any], *, asset_version: str,
                  known_attachment_keys: set[str] | None = None):
        return normalize_character_vehicle(
            row,
            asset_version=asset_version,
            known_attachment_keys=known_attachment_keys,
        )
