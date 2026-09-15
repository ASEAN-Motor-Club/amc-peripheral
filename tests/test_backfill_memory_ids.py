"""Tests for scripts/backfill_memory_ids.py — deterministic id backfill.

Covers every migration rule, ambiguity refusal, bot-row pairing, and
idempotency, against a synthetic player_memories.db.
"""

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "backfill_memory_ids", REPO / "scripts" / "backfill_memory_ids.py"
)
bf = importlib.util.module_from_spec(_spec)
sys.modules["backfill_memory_ids"] = bf
_spec.loader.exec_module(bf)


SCHEMA = """
CREATE TABLE player_memory (
    id INTEGER PRIMARY KEY,
    player_id TEXT NOT NULL,
    player_name TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    is_bot_response INTEGER NOT NULL DEFAULT 0,
    timestamp TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'game_chat'
);
"""


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "pm.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.commit()
    yield path, conn
    conn.close()


def insert(conn, player_id, player_name, ts, is_bot=0, message="m"):
    conn.execute(
        "INSERT INTO player_memory (player_id, player_name, message, "
        "is_bot_response, timestamp, source) VALUES (?,?,?,?,?, 'game_chat')",
        (str(player_id), player_name, message, is_bot, ts),
    )
    conn.commit()


def keys(conn):
    return {
        r[0] for r in conn.execute(
            "SELECT DISTINCT player_id FROM player_memory WHERE source='game_chat'"
        )
    }


class TestRule1NumericNoOp:
    def test_numeric_keys_untouched(self, db):
        _, conn = db
        insert(conn, "76561198958693540", "Alex", "2026-09-15T12:00:00")
        rewrites, stats = bf.plan(conn, None, 30, 3)
        assert rewrites == []
        assert stats["rule5"] == 0


class TestRule2UniqueStoreEvidence:
    def test_tag_key_resolved_via_other_rows(self, db):
        _, conn = db
        insert(conn, "76561198834561342", "frozenblaze", "2026-04-01T10:00:00")
        insert(conn, "[M] frozenblaze", "[M] frozenblaze", "2026-04-02T10:00:00")
        insert(conn, "[M] frozenblaze", "DJ Annie", "2026-04-02T10:00:05", is_bot=1)
        rewrites, stats = bf.plan(conn, None, 30, 3)
        assert ("[M] frozenblaze", "76561198834561342") in rewrites
        assert stats["rule2"] == 1

    def test_ambiguous_name_not_rewritten_by_rule2(self, db):
        _, conn = db
        # 'Ellie' chatted under two different numeric keys
        insert(conn, "76561198058135931", "Ellie", "2026-04-01T10:00:00")
        insert(conn, "76561199191787033", "Ellie", "2026-04-05T10:00:00")
        insert(conn, "Ellie", "Ellie", "2026-04-03T10:00:00")
        rewrites, _ = bf.plan(conn, None, 30, 3)
        assert not any(old == "Ellie" for old, _ in rewrites)


class TestRule3TemporalAttribution:
    def _seed_two_candidates(self, conn):
        # Candidate A active 12:00–13:00 on Apr 3; candidate B only on Apr 1
        for i in range(6):
            insert(conn, "76561198000000001", "Sam",
                   f"2026-04-03T12:{i:02d}:00", message=f"a{i}")
        for i in range(6):
            insert(conn, "76561198000000002", "Sam",
                   f"2026-04-01T12:{i:02d}:00", message=f"b{i}")

    def test_row_window_picks_active_candidate(self, db):
        _, conn = db
        self._seed_two_candidates(conn)
        # Name-keyed row sits inside A's burst (Apr 3 12:30)
        insert(conn, "Sam", "Sam", "2026-04-03T12:30:00")
        rewrites, stats = bf.plan(conn, None, 30, 3)
        assert ("Sam", "76561198000000001") in rewrites
        assert stats["rule3"] == 1

    def test_no_active_candidate_left_untouched(self, db):
        _, conn = db
        self._seed_two_candidates(conn)
        # Name-keyed row weeks after both bursts
        insert(conn, "Sam", "Sam", "2026-05-20T12:30:00")
        rewrites, _ = bf.plan(conn, None, 30, 3)
        assert not any(old == "Sam" for old, _ in rewrites)

    def test_below_min_evidence_untouched(self, db):
        _, conn = db
        # Only 1-2 rows of evidence (below default floor of 3)
        insert(conn, "76561198000000001", "Sam", "2026-04-03T12:29:00")
        insert(conn, "76561198000000002", "Sam", "2026-04-01T12:00:00")
        insert(conn, "Sam", "Sam", "2026-04-03T12:30:00")
        rewrites, _ = bf.plan(conn, None, 30, 3)
        assert not any(old == "Sam" for old, _ in rewrites)

    def test_mixed_windows_strict_majority_required(self, db):
        _, conn = db
        self._seed_two_candidates(conn)
        # One row near A, one near B — no strict majority → untouched.
        insert(conn, "Sam", "Sam", "2026-04-03T12:31:00")
        insert(conn, "Sam", "Sam", "2026-04-01T12:01:00")
        rewrites, _ = bf.plan(conn, None, 30, 3)
        assert not any(old == "Sam" for old, _ in rewrites)


class TestRule4UniqueBackend:
    def test_unique_backend_match(self, db, monkeypatch):
        _, conn = db
        insert(conn, "Whodis", "Whodis", "2026-04-03T12:00:00")
        monkeypatch.setattr(
            bf, "backend_unique_lookup",
            lambda names, dsn: {"whodis": "76561198888888888"},
        )
        rewrites, stats = bf.plan(conn, "postgresql://mock", 30, 3)
        assert ("Whodis", "76561198888888888") in rewrites
        assert stats["rule4"] == 1


class TestRule5Unresolved:
    def test_unresolvable_left_name_keyed(self, db):
        _, conn = db
        insert(conn, "OnlyMe", "OnlyMe", "2026-04-03T12:00:00")
        rewrites, _ = bf.plan(conn, None, 30, 3)
        assert rewrites == []
        assert keys(conn) == {"OnlyMe"}


class TestApply:
    def test_apply_rewrites_and_is_idempotent(self, db):
        path, conn = db
        insert(conn, "76561198834561342", "frozenblaze", "2026-04-01T10:00:00")
        insert(conn, "[M] frozenblaze", "[M] frozenblaze", "2026-04-02T10:00:00")
        insert(conn, "[M] frozenblaze", "DJ Annie", "2026-04-02T10:00:05", is_bot=1)
        conn.close()
        # apply through plan + the same UPDATE semantics main() uses
        conn = sqlite3.connect(path)
        rewrites, _ = bf.plan(conn, None, 30, 3)
        assert rewrites == [("[M] frozenblaze", "76561198834561342")]
        cur = conn.cursor()
        cur.execute("BEGIN")
        for old, new in rewrites:
            cur.execute(
                "UPDATE player_memory SET player_id = ? WHERE player_id = ? "
                "AND source = 'game_chat'",
                (new, old),
            )
        conn.commit()
        # both player and bot rows moved together
        assert keys(conn) == {"76561198834561342"}
        # idempotency: second plan() finds nothing
        rewrites2, _ = bf.plan(conn, None, 30, 3)
        assert rewrites2 == []
        conn.close()
