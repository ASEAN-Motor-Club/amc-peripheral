#!/usr/bin/env python3
"""Backfill radio player_memory keys onto deterministic player ids.

Rewrites `player_id` values in the radio bot's player_memories.db that hold
chat NAMES instead of deterministic IDs. Key classes:

  1. Numeric 17-digit keys (Steam id / amc_player.unique_id)  → no-op
  2. Name keys whose tag-stripped form maps to exactly ONE numeric id among
     the store's own rows (same player, other sessions)     → rewrite
  3. Ambiguous names → per-row temporal attribution: assign each row to the
     candidate whose numeric-keyed activity (±WINDOW minutes around the
     row's timestamp) has the most rows, provided that evidence is >=
     --min-evidence. A player can only chat under one key at a time, so the
     temporally-active candidate is the sender.           → rewrite
  4. Tag-stripped name maps to exactly one amc_player.unique_id in the
     backend (unique match only — shared names are never joined) → rewrite
  5. Anything else stays name-keyed. Never invent an id.

Both sides of each exchange (player rows and the paired bot-response rows
under the same key) are rewritten together.

Dry-run by default; pass --apply to write. Single transaction, integrity
check after write, restores nothing automatically (a .bak copy is expected
to be taken by the operator before --apply).

Usage:
  python3 backfill_memory_ids.py --db /path/to/player_memories.db            # dry-run
  python3 backfill_memory_ids.py --db /path/to/player_memories.db --apply    # write
  python3 backfill_memory_ids.py --db ... --backend-dsn postgresql://...     # enable rule 4
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime

STEAM_KEY_RE = re.compile(r"^\d{17}$")
_ROLE_TAG_RE = re.compile(r"^(?:\s*\[[A-Za-z0-9]+\]\s*)+")
# Rows inserted by the bot itself; they share the player's key and must be
# rewritten together with the player's rows.
BOT_NAMES = {"DJ Annie", "Bot", "Annie"}
DEFAULT_WINDOW_MIN = 30
DEFAULT_MIN_EVIDENCE = 3


def strip_tag(name: str | None) -> str:
    if not name:
        return ""
    return _ROLE_TAG_RE.sub("", name).strip()


def parse_ts(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return None
    # The store mixes naive (+07:00 wall-clock) and aware (UTC) timestamps;
    # normalize everything to naive UTC so deltas are comparable.
    if dt.tzinfo is not None:
        dt = (dt - dt.utcoffset()).replace(tzinfo=None)
    return dt


def load_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    return conn.execute(
        "SELECT id, player_id, player_name, timestamp, is_bot_response "
        "FROM player_memory WHERE source = 'game_chat'"
    ).fetchall()


def build_steam_identity(
    rows: list[sqlite3.Row],
) -> tuple[dict[str, str], dict[str, list[sqlite3.Row]]]:
    """name(lower, tag-stripped) -> numeric id  (unique names only), and
    numeric id -> that player's timestamped rows (for rule 3)."""
    name_ids: dict[str, set[str]] = defaultdict(set)
    id_rows: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for r in rows:
        pid = str(r["player_id"])
        if not STEAM_KEY_RE.match(pid):
            continue
        id_rows[pid].append(r)
        if r["is_bot_response"]:
            continue
        nm = strip_tag(r["player_name"]).lower()
        if nm:
            name_ids[nm].add(pid)
    unique = {n: next(iter(ids)) for n, ids in name_ids.items() if len(ids) == 1}
    return unique, id_rows


def temporal_assign(
    row: sqlite3.Row,
    candidates: list[str],
    id_rows: dict[str, list[sqlite3.Row]],
    window_min: int,
    min_evidence: int,
) -> str | None:
    """Pick the candidate with most numeric-keyed rows within ±window of the
    name-keyed row's timestamp. Returns None below the evidence floor."""
    ts = parse_ts(row["timestamp"])
    if ts is None:
        return None
    best_id, best_count = None, 0
    for pid in candidates:
        count = 0
        for r in id_rows.get(pid, ()):
            rts = parse_ts(r["timestamp"])
            if rts is None:
                continue
            delta = abs((rts - ts).total_seconds())
            if delta <= window_min * 60:
                count += 1
        if count > best_count:
            best_id, best_count = pid, count
    return best_id if best_count >= min_evidence else None


def backend_unique_lookup(
    names: set[str], dsn: str
) -> dict[str, str]:
    """Rule 4: tag-stripped name -> unique amc_player.unique_id. Only names
    resolving to EXACTLY one backend player are returned."""
    try:
        import psycopg2
    except ImportError:
        print("rule 4 skipped: psycopg2 not available", file=sys.stderr)
        return {}
    out: dict[str, str] = {}
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            for nm in names:
                cur.execute(
                    """
                    SELECT p.unique_id
                    FROM amc_character c
                    JOIN amc_player p ON p.unique_id = c.player_id
                    WHERE lower(c.name) = %s
                    GROUP BY p.unique_id
                    """,
                    (nm,),
                )
                ids = [str(r[0]) for r in cur.fetchall()]
                if len(ids) == 1:
                    out[nm] = ids[0]
    finally:
        conn.close()
    return out


def plan(conn: sqlite3.Connection, dsn: str | None, window_min: int,
         min_evidence: int) -> tuple[list[tuple[str, str]], dict[str, int]]:
    """Returns (list of (old_key, new_key) rewrites, per-rule counters)."""
    rows = load_rows(conn)
    name_keys = {
        str(r["player_id"]) for r in rows if not STEAM_KEY_RE.match(str(r["player_id"]))
    }
    # name_key -> set of candidate numeric ids (from the store itself)
    candidates_by_key: dict[str, set[str]] = {}
    for nk in name_keys:
        nm = strip_tag(nk).lower()
        matching = {
            pid
            for r in rows
            if (pid := str(r["player_id"])) and STEAM_KEY_RE.match(pid)
            and not r["is_bot_response"]
            and strip_tag(r["player_name"]).lower() == nm
        }
        if matching:
            candidates_by_key[nk] = matching

    unique_name_map, id_rows = build_steam_identity(rows)
    _ = unique_name_map  # reserved: alias-boost signal, not yet used

    # Rule 4 candidates: name keys with NO in-store candidate evidence
    rule4_names = {strip_tag(nk).lower() for nk in name_keys
                   if not candidates_by_key.get(nk)}
    backend_map = backend_unique_lookup(rule4_names, dsn) if dsn and rule4_names else {}

    rewrites: list[tuple[str, str]] = []
    stats: dict[str, int] = {"rule2": 0, "rule3": 0, "rule4": 0, "rule5": 0}
    for nk in sorted(name_keys):
        nm = strip_tag(nk).lower()
        cands = candidates_by_key.get(nk, set())
        target = None
        if len(cands) == 1:
            target = next(iter(cands))
            stats["rule2"] += 1
            rewrites.append((nk, target))
        elif not cands and nm in backend_map:
            rewrites.append((nk, backend_map[nm]))
            stats["rule4"] += 1

    # Rule 3 per-row temporal attribution for ambiguous keys
    ambiguous_keys = [nk for nk, cands in candidates_by_key.items() if len(cands) > 1]
    rows_by_key: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for r in rows:
        pid = str(r["player_id"])
        if pid in ambiguous_keys:
            rows_by_key[pid].append(r)
    for nk in sorted(ambiguous_keys):
        nk_rows = rows_by_key.get(nk, [])
        decided: dict[int, str] = {}
        for r in nk_rows:
            pid = temporal_assign(r, sorted(candidates_by_key[nk]), id_rows,
                                  window_min, min_evidence)
            if pid:
                decided[int(r["id"])] = pid
        if not decided:
            continue
        # Only rewrite the whole key when a strong majority of its rows
        # agree, so the paired bot-response rows stay with their player rows.
        votes: dict[str, int] = defaultdict(int)
        for pid in decided.values():
            votes[pid] += 1
        winner, wcount = max(votes.items(), key=lambda kv: kv[1])
        # The evidence floor is per-ROW (temporal_assign already enforces
        # --min-evidence supporting chat rows); the key-level gate only
        # requires that a strict majority of the key's rows agree, so
        # paired bot rows move with their player rows.
        if wcount > len(decided) / 2:
            rewrites.append((nk, winner))
            stats["rule3"] += 1

    stats["rule5"] = len(name_keys) - len(rewrites)
    return rewrites, stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", required=True, help="path to player_memories.db")
    ap.add_argument("--apply", action="store_true", help="write (default: dry-run)")
    ap.add_argument("--backend-dsn", default=None,
                    help="postgresql DSN for rule 4 (amc_player/amc_character)")
    ap.add_argument("--window-min", type=int, default=DEFAULT_WINDOW_MIN,
                    help="rule-3 temporal window minutes (default 30)")
    ap.add_argument("--min-evidence", type=int, default=DEFAULT_MIN_EVIDENCE,
                    help="rule-3 minimum supporting rows (default 3)")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    try:
        rewrites, stats = plan(conn, args.backend_dsn, args.window_min,
                               args.min_evidence)
        mode = "APPLY" if args.apply else "DRY-RUN"
        print(f"[{mode}] db={args.db}")
        print(f"  rule 2 (unique store evidence): {stats['rule2']} keys")
        print(f"  rule 3 (temporal attribution):  {stats['rule3']} keys")
        print(f"  rule 4 (unique backend match):  {stats['rule4']} keys")
        print(f"  rule 5 (left name-keyed):       {stats['rule5']} keys")
        for old, new in rewrites:
            print(f"  {old!r} -> {new}")
        if not rewrites:
            print("nothing to do")
            return 0
        if not args.apply:
            print("dry-run only; re-run with --apply to write")
            return 0
        cur = conn.cursor()
        cur.execute("BEGIN")
        total = 0
        for old, new in rewrites:
            cur.execute(
                "UPDATE player_memory SET player_id = ? WHERE player_id = ? "
                "AND source = 'game_chat'",
                (new, old),
            )
            total += cur.rowcount
        conn.commit()
        print(f"applied: {total} rows rewritten across {len(rewrites)} keys")
        cur.execute("PRAGMA integrity_check")
        ok = cur.fetchone()[0]
        print(f"integrity_check: {ok}")
        if ok != "ok":
            print("INTEGRITY FAILURE — restore from your backup", file=sys.stderr)
            return 1
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
