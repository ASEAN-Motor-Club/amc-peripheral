"""Player identity & alias index built from the player_memories SQLite store.

The raw ``player_memory`` table records every message under whatever ids and
display names the player had at the time. One person commonly appears under
several fragments:

* the Steam game ``player_id`` (e.g. ``76561198864278343``)
* a linked Discord ``discord_user_id`` (e.g. ``1253991831260237898``)
* many display names over time (``frozenblaze``, ``[M] frozenblaze``,
  ``commander``, ``[M] commander``, ...)

memory/player_index.py collapses those fragments into a single canonical
record per person (union-find over the player_id <-> discord_user_id links),
then lets you resolve "who is <name>?" by any alias — including nicknames the
player asked the bot to use ("call me commander from now on"). This is what
lets the bot answer "do you know frozenblaze?" instead of only remembering the
person who is currently speaking to it.

The index is read-only and opens the DB with ``mode=ro`` so it can never
contend with the live bot's writes.
"""

import re
import sqlite3
from collections import defaultdict
from typing import ClassVar

from amc_peripheral.settings import MEMORY_DB_PATH

# Role / clan tags the game prefixes to a name, e.g. [M], [C10], [MC10], [RM].
_TAG_RE = re.compile(r"^\s*\[[^\]]+\]\s+")

# "call me <X> from now on" / "call me <X>" — the player telling the bot what
# to address them as.
_NICK_RE = re.compile(
    r"call\s+me\s+(.+?)(?:\s+from\s+now\s+on|\s+instead|[,.]|$)", re.IGNORECASE
)


def _normalize_name(name: str) -> str:
    """Lowercase and strip role/clan bracket prefixes for matching."""
    return _TAG_RE.sub("", name).strip().lower()


def _strip_tags(name: str) -> str:
    return _TAG_RE.sub("", name).strip()


class PlayerRecord:
    """Canonical view of one person across all their identity fragments."""

    __slots__ = (
        "_name_counts",
        "aliases",
        "discord_ids",
        "first_seen",
        "ids",
        "key",
        "last_seen",
        "message_count",
        "normalized_names",
    )

    def __init__(self, key: str):
        self.key = key
        self.ids: set[str] = set()  # all player_id values (game + discord-as-id)
        self.discord_ids: set[str] = set()  # linked discord_user_id values
        self.aliases: list[str] = []  # raw display names ever seen
        self.normalized_names: set[str] = set()
        self.message_count = 0
        self.first_seen: str | None = None
        self.last_seen: str | None = None
        self._name_counts: dict[str, int] = {}

    def add_usage(self, player_name: str, ts: str | None, n: int = 1):
        raw = _strip_tags(player_name) or player_name
        # "Bot" is the reserved name for bot responses; drop it and empties.
        if raw.lower() == "bot" or not raw:
            return
        if raw not in self.aliases:
            self.aliases.append(raw)
        self._name_counts[raw.lower()] = self._name_counts.get(raw.lower(), 0) + n
        self.normalized_names.add(raw.lower())
        self.message_count += n
        if ts:
            if self.first_seen is None or ts < self.first_seen:
                self.first_seen = ts
            if self.last_seen is None or ts > self.last_seen:
                self.last_seen = ts

    def _display_name(self) -> str:
        """Most-used alias, falling back to the identity key."""
        if not self._name_counts:
            return self.key
        best = self.key
        best_n = -1
        for name, count in self._name_counts.items():
            if count > best_n:
                best, best_n = name, count
        return best

    def summary(self, requested_nickname: str | None = None) -> dict:
        """Return a compact, LLM-friendly dict."""
        name = self._display_name()
        out = {
            "name": (
                requested_nickname
                if requested_nickname and requested_nickname != name.lower()
                else name
            ),
            "aliases": sorted(set(self.aliases)),
            "game_ids": sorted(i for i in self.ids if i not in self.discord_ids),
            "discord_ids": sorted(self.discord_ids),
            "message_count": self.message_count,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
        }
        if requested_nickname:
            out["requested_nickname"] = requested_nickname
        return out


class PlayerIndex:
    """Name / alias -> canonical player resolution over the memory store."""

    def __init__(self, db_path: str = MEMORY_DB_PATH):
        self.db_path = db_path
        self._records: list[PlayerRecord] = []
        # name (normalized) -> list of record keys, for lookup
        self._name_index: dict[str, list[str]] = defaultdict(list)
        # id (player_id or discord id) -> record key
        self._id_index: dict[str, str] = {}

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def _load(self) -> None:
        """(Re)build the identity index from the memory store."""
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT player_id, player_name, discord_user_id,
                       COUNT(*) AS n,
                       MIN(timestamp) AS first_seen,
                       MAX(timestamp) AS last_seen
                FROM player_memory
                GROUP BY player_id, player_name
                """
            ).fetchall()
        finally:
            conn.close()

        # Union-find over player_id <-> discord_user_id so the Discord-linked
        # game identity and the discord-as-player_id identity merge into one.
        parent: dict[str, str] = {}

        def find(x: str) -> str:
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: str, b: str) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        for row in rows:
            pid = row["player_id"]
            union(pid, pid)
            did = row["discord_user_id"]
            if did:
                union(pid, did)

        records: dict[str, PlayerRecord] = {}
        for row in rows:
            root = find(row["player_id"])
            rec = records.get(root)
            if rec is None:
                rec = records[root] = PlayerRecord(root)
            rec.ids.add(row["player_id"])
            did = row["discord_user_id"]
            if did:
                rec.ids.add(did)
                rec.discord_ids.add(did)
            rec.add_usage(
                row["player_name"], row["last_seen"] or row["first_seen"], row["n"]
            )
            # player_id also act as aliases for lookup-by-id
            self._id_index.setdefault(row["player_id"], root)
            if did:
                self._id_index.setdefault(did, root)

        self._records = list(records.values())
        self._name_index = defaultdict(list)
        for rec in self._records:
            for name in rec.normalized_names:
                self._name_index[name].append(rec.key)

    def _ensure_loaded(self) -> None:
        if not self._records:
            self._load()

    def lookup(self, query: str, limit: int = 3) -> list[dict]:
        """Resolve a name/id to the best-matching player record summaries."""
        self._ensure_loaded()
        q = _normalize_name(query)
        if not q:
            return []

        # 1) exact id match
        if query in self._id_index:
            key = self._id_index[query]
            return [self._summary_for(key)]

        # 2) exact normalized name match
        if q in self._name_index:
            keys = self._name_index[q]
            return [self._summary_for(k) for k in keys[:limit]]

        # 3) substring / fuzzy match, ranked by closeness then activity
        scored: list[tuple[int, int, str]] = []
        for rec in self._records:
            for name in rec.normalized_names:
                if q in name or name in q:
                    if name == q:
                        score = 0
                    elif name.startswith(q):
                        score = 1
                    else:
                        score = 2
                    scored.append((score, rec.message_count, rec.key))
        # dedupe per record keeping best score
        best: dict[str, tuple[int, int]] = {}
        for score, count, key in scored:
            if key not in best or (score, -count) < (best[key][0], -best[key][1]):
                best[key] = (score, count)
        ranked = sorted(best.items(), key=lambda kv: (kv[1][0], -kv[1][1]))
        return [self._summary_for(k) for k, _ in ranked[:limit]]

    def _summary_for(self, key: str) -> dict:
        rec = next(r for r in self._records if r.key == key)
        nick = self._requested_nickname(rec)
        return rec.summary(nick)

    # Nickname-preference extraction
    _NICK_STOPWORDS: ClassVar[set[str]] = {
        "me",
        "by",
        "with",
        "from",
        "now",
        "on",
        "my",
        "your",
        "the",
        "a",
        "an",
        "to",
        "for",
        "of",
        "at",
        "in",
        "and",
        "or",
        "no",
        "not",
        "only",
        "just",
        "please",
        "u",
        "ur",
        "you",
        "call",
        "callsign",
        "pleasejust",
    }

    def _requested_nickname(self, rec: PlayerRecord) -> str | None:
        """Return the player's most recent explicit 'call me X from now on / instead'."""
        conn = self._connect()
        try:
            ids = list(rec.ids)
            if not ids:
                return None
            placeholders = ",".join("?" * len(ids))
            rows = conn.execute(
                f"""
                SELECT message FROM player_memory
                WHERE player_id IN ({placeholders})
                  AND is_bot_response = 0
                  AND (message LIKE '%call me%from now on%'
                       OR message LIKE '%call me%instead%')
                ORDER BY timestamp DESC LIMIT 12
                """,
                ids,
            ).fetchall()
        finally:
            conn.close()

        for row in rows:
            msg = row["message"] or ""
            m = _NICK_RE.search(msg)
            if not m:
                continue
            token = self._nickname_token(m.group(1))
            if token is not None:
                return token
        return None

    def _nickname_token(self, captured: str) -> str | None:
        """First non-stopword token after 'call me' (the intended nickname)."""
        for word in captured.split():
            w = _normalize_name(word)
            if w and w not in self._NICK_STOPWORDS:
                return w
        return None
