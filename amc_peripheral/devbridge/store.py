"""SQLite storage for the AMC dev bridge.

Design notes that matter:

* Tokens are stored as SHA-256 digests. The plaintext lives in the enrolment row
  only until the mod has actually used it once (claim-once), then it is cleared.
  A lost local state therefore needs a fresh approval, not a silent reissue: the
  fingerprint alone must never be enough to obtain a credential.
* Enrolment is idempotent per device fingerprint: a restarted game, or a machine
  that lost its state BEFORE approval, gets the SAME claim code back instead of
  creating a second pending request.
* `auto_approve` skips the human entirely: the device gets a token the moment it
  enrols, and a device that re-enrols (lost state) gets its credential rotated
  instead of being stranded. Revocation still wins -- a revoked fingerprint is
  never reissued. In that mode the fingerprint is a self-asserted identity, not
  a vetted one, which is the whole point: the member is exposing their own
  machine, so they are the one granting access.
* One in-flight command per member, a bounded queue, and an expiry, so a dead
  client cannot accumulate a backlog.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS enrollments (
    secret       TEXT PRIMARY KEY,
    code         TEXT NOT NULL UNIQUE,
    fingerprint  TEXT NOT NULL UNIQUE,
    host         TEXT,
    mod          TEXT,
    status       TEXT NOT NULL DEFAULT 'pending',   -- pending|approved|denied
    token_hash   TEXT,
    token_plain  TEXT,                              -- cleared after first use
    created_at   REAL NOT NULL,
    decided_at   REAL,
    decided_by   TEXT
);

CREATE TABLE IF NOT EXISTS members (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    label        TEXT NOT NULL UNIQUE,
    discord_id   TEXT,
    token_hash   TEXT NOT NULL UNIQUE,
    fingerprint  TEXT NOT NULL UNIQUE,
    host         TEXT,
    mod          TEXT,
    created_at   REAL NOT NULL,
    revoked_at   REAL,
    last_seen_at REAL
);

CREATE TABLE IF NOT EXISTS commands (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id  INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    code       TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'queued',      -- queued|sent|done|error|expired
    created_at REAL NOT NULL,
    sent_at    REAL,
    result_at  REAL,
    result     TEXT,
    output     TEXT,
    error      TEXT
);

CREATE TABLE IF NOT EXISTS audit (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    at      REAL NOT NULL,
    actor   TEXT,
    action  TEXT NOT NULL,
    subject TEXT,
    detail  TEXT
);

CREATE INDEX IF NOT EXISTS idx_commands_member ON commands(member_id, id);
CREATE INDEX IF NOT EXISTS idx_commands_status ON commands(member_id, status);
"""


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _slug(host: str | None) -> str:
    """Readable, unique-ish label from a machine name."""
    raw = (host or "machine").strip()
    out = "".join(ch if (ch.isalnum() or ch in "-_") else "-" for ch in raw).strip("-").lower()
    return (out or "machine")[:40]


def _code() -> str:
    """Short, unambiguous claim code: XXXX-XXXX, no vowels, no 0/1."""
    alphabet = "BCDFGHJKLMNPQRSTVWXZ23456789"
    return "{}-{}".format(
        "".join(secrets.choice(alphabet) for _ in range(4)),
        "".join(secrets.choice(alphabet) for _ in range(4)),
    )


class BridgeStore:
    def __init__(self, path: str | Path, *, queue_cap: int = 8, command_ttl: int = 600):
        self.path = Path(path)
        self.queue_cap = queue_cap
        self.command_ttl = command_ttl
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        return c

    def _audit(self, c, action: str, actor=None, subject=None, detail=None) -> None:
        c.execute(
            "INSERT INTO audit (at, actor, action, subject, detail) VALUES (?,?,?,?,?)",
            (time.time(), actor, action, subject, detail),
        )

    # -- enrolment --------------------------------------------------------
    def enroll(
        self,
        fingerprint: str,
        host: str | None,
        mod: str | None,
        *,
        auto_approve: bool = False,
        label: str | None = None,
    ) -> dict:
        """Register a device. Idempotent: same fingerprint -> same code/secret.

        With `auto_approve`, the device is issued a token immediately and no
        human is involved. A revoked fingerprint is still refused.
        """
        if not fingerprint:
            raise ValueError("fingerprint required")
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM enrollments WHERE fingerprint = ?", (fingerprint,)
            ).fetchone()
            if row:
                out = {"code": row["code"], "secret": row["secret"], "status": row["status"]}
                if auto_approve:
                    member = c.execute(
                        "SELECT * FROM members WHERE fingerprint = ?", (fingerprint,)
                    ).fetchone()
                    if member is not None and member["revoked_at"] is not None:
                        return {"status": "revoked"}
                    if member is not None:
                        token = secrets.token_urlsafe(32)
                        c.execute(
                            "UPDATE members SET token_hash=?, host=?, mod=? WHERE id=?",
                            (_hash_token(token), host, mod, member["id"]),
                        )
                        c.execute(
                            "UPDATE enrollments SET status='approved', token_hash=?, token_plain=?"
                            " WHERE secret=?",
                            (_hash_token(token), token, row["secret"]),
                        )
                        out.update({"status": "approved", "token": token})
                        self._audit(c, "member.rotate", actor="self", subject=member["label"])
                return out
            secret = secrets.token_urlsafe(24)
            code = _code()
            while c.execute("SELECT 1 FROM enrollments WHERE code = ?", (code,)).fetchone():
                code = _code()
            c.execute(
                "INSERT INTO enrollments (secret, code, fingerprint, host, mod, created_at)"
                " VALUES (?,?,?,?,?,?)",
                (secret, code, fingerprint, host, mod, time.time()),
            )
            self._audit(c, "enroll.request", subject=fingerprint, detail=host)
            if not auto_approve:
                return {"code": code, "secret": secret, "status": "pending"}

            token = secrets.token_urlsafe(32)
            name = label or self._unique_label(c, _slug(host))
            c.execute(
                "UPDATE enrollments SET status='approved', token_hash=?, token_plain=?,"
                " decided_at=?, decided_by='self' WHERE secret=?",
                (_hash_token(token), token, time.time(), secret),
            )
            c.execute(
                "INSERT INTO members (label, discord_id, token_hash, fingerprint, host, mod, created_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (name, None, _hash_token(token), fingerprint, host, mod, time.time()),
            )
            self._audit(c, "enroll.auto", actor="self", subject=name, detail=fingerprint)
            return {"code": code, "secret": secret, "status": "approved", "token": token}

    @staticmethod
    def _unique_label(c, base: str) -> str:
        name, n = base, 2
        while c.execute("SELECT 1 FROM members WHERE label = ?", (name,)).fetchone():
            name = f"{base}-{n}"
            n += 1
        return name

    def enrollment(self, secret: str) -> dict | None:
        """What the mod polls. Carries the token only while it is unclaimed."""
        with self._conn() as c:
            row = c.execute("SELECT * FROM enrollments WHERE secret = ?", (secret,)).fetchone()
            if not row:
                return None
            out = {"status": row["status"]}
            if row["status"] == "approved" and row["token_plain"]:
                out["token"] = row["token_plain"]
            return out

    def approve(self, code: str, label: str, actor: str, discord_id: str | None = None) -> dict | None:
        """Approve a claim code. Creates or re-keys the member; returns the token ONCE."""
        code = (code or "").strip().upper()
        with self._conn() as c:
            row = c.execute("SELECT * FROM enrollments WHERE code = ?", (code,)).fetchone()
            if not row or row["status"] != "pending":
                return None

            existing = c.execute(
                "SELECT * FROM members WHERE fingerprint = ?", (row["fingerprint"],)
            ).fetchone()
            if existing and existing["revoked_at"] is not None:
                raise ValueError("this machine was revoked; clear the revocation first")

            token = secrets.token_urlsafe(32)
            now = time.time()
            c.execute(
                "UPDATE enrollments SET status='approved', token_hash=?, token_plain=?,"
                " decided_at=?, decided_by=? WHERE secret=?",
                (_hash_token(token), token, now, actor, row["secret"]),
            )
            if existing:
                # same machine, new credential: keep the identity, rotate the token
                label = existing["label"]
                c.execute(
                    "UPDATE members SET token_hash=?, host=?, mod=?, discord_id=?"
                    " WHERE id=?",
                    (_hash_token(token), row["host"], row["mod"], discord_id or existing["discord_id"],
                     existing["id"]),
                )
                self._audit(c, "member.rekey", actor=actor, subject=label)
            else:
                if c.execute("SELECT 1 FROM members WHERE label = ?", (label,)).fetchone():
                    raise ValueError("member label already exists")
                c.execute(
                    "INSERT INTO members (label, discord_id, token_hash, fingerprint, host, mod, created_at)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (label, discord_id, _hash_token(token), row["fingerprint"],
                     row["host"], row["mod"], now),
                )
                self._audit(c, "enroll.approve", actor=actor, subject=label,
                            detail=row["fingerprint"])
            return {"label": label, "token": token, "fingerprint": row["fingerprint"]}

    def deny(self, code: str, actor: str) -> bool:
        code = (code or "").strip().upper()
        with self._conn() as c:
            cur = c.execute(
                "UPDATE enrollments SET status='denied', decided_at=?, decided_by=?"
                " WHERE code=? AND status='pending'",
                (time.time(), actor, code),
            )
            if cur.rowcount:
                self._audit(c, "enroll.deny", actor=actor, subject=code)
            return bool(cur.rowcount)

    # -- members ----------------------------------------------------------
    def member_by_token(self, token: str, *, claim: bool = True) -> sqlite3.Row | None:
        """Resolve a token. The first successful use clears the stored plaintext."""
        if not token:
            return None
        h = _hash_token(token)
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM members WHERE token_hash = ? AND revoked_at IS NULL", (h,)
            ).fetchone()
            if not row:
                return None
            c.execute("UPDATE members SET last_seen_at = ? WHERE id = ?", (time.time(), row["id"]))
            if claim:
                c.execute("UPDATE enrollments SET token_plain=NULL WHERE token_hash=?", (h,))
            return row

    def member(self, label: str) -> sqlite3.Row | None:
        with self._conn() as c:
            return c.execute("SELECT * FROM members WHERE label = ?", (label,)).fetchone()

    def members(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM members ORDER BY label").fetchall()
            return [
                {
                    "label": r["label"],
                    "host": r["host"],
                    "mod": r["mod"],
                    "discord_id": r["discord_id"],
                    "created_at": r["created_at"],
                    "revoked": r["revoked_at"] is not None,
                    "last_seen_at": r["last_seen_at"],
                }
                for r in rows
            ]

    def revoke(self, label: str, actor: str) -> bool:
        with self._conn() as c:
            cur = c.execute(
                "UPDATE members SET revoked_at = ? WHERE label = ? AND revoked_at IS NULL",
                (time.time(), label),
            )
            if cur.rowcount:
                self._audit(c, "member.revoke", actor=actor, subject=label)
            return bool(cur.rowcount)

    def rename(self, label: str, new: str, actor: str) -> bool:
        """Give an auto-labelled machine a human name."""
        new = _slug(new)
        if not new:
            raise ValueError("empty name")
        with self._conn() as c:
            if not c.execute("SELECT 1 FROM members WHERE label = ?", (label,)).fetchone():
                return False
            if c.execute("SELECT 1 FROM members WHERE label = ?", (new,)).fetchone():
                raise ValueError("name already in use")
            c.execute("UPDATE members SET label = ? WHERE label = ?", (new, label))
            self._audit(c, "member.rename", actor=actor, subject=label, detail=new)
            return True

    def unrevoke(self, label: str, actor: str) -> bool:
        with self._conn() as c:
            cur = c.execute(
                "UPDATE members SET revoked_at = NULL WHERE label = ? AND revoked_at IS NOT NULL",
                (label,),
            )
            if cur.rowcount:
                self._audit(c, "member.unrevoke", actor=actor, subject=label)
            return bool(cur.rowcount)

    # -- commands ---------------------------------------------------------
    def queue_command(self, member_id: int, code: str) -> int:
        with self._conn() as c:
            inflight = c.execute(
                "SELECT COUNT(*) FROM commands WHERE member_id=? AND status IN ('queued','sent')",
                (member_id,),
            ).fetchone()[0]
            if inflight >= self.queue_cap:
                raise ValueError(f"queue full: {inflight} commands already pending")
            cur = c.execute(
                "INSERT INTO commands (member_id, code, created_at) VALUES (?,?,?)",
                (member_id, code, time.time()),
            )
            return int(cur.lastrowid or 0)

    def next_command(self, member_id: int, after: int = 0) -> dict | None:
        """Next queued command for this member, marked as sent."""
        with self._conn() as c:
            now = time.time()
            c.execute(
                "UPDATE commands SET status='expired' WHERE member_id=? AND status='queued'"
                " AND created_at < ?",
                (member_id, now - self.command_ttl),
            )
            row = c.execute(
                "SELECT * FROM commands WHERE member_id=? AND status='queued' AND id > ?"
                " ORDER BY id LIMIT 1",
                (member_id, after),
            ).fetchone()
            if not row:
                return None
            c.execute("UPDATE commands SET status='sent', sent_at=? WHERE id=?", (now, row["id"]))
            return {"id": row["id"], "code": row["code"]}

    def save_result(self, member_id: int, payload: dict) -> bool:
        cmd_id = payload.get("id")
        if not isinstance(cmd_id, int):
            return False
        with self._conn() as c:
            row = c.execute(
                "SELECT id FROM commands WHERE id=? AND member_id=?", (cmd_id, member_id)
            ).fetchone()
            if not row:
                return False
            ok = bool(payload.get("ok"))
            c.execute(
                "UPDATE commands SET status=?, result_at=?, result=?, output=?, error=? WHERE id=?",
                (
                    "done" if ok else "error",
                    time.time(),
                    json.dumps(payload.get("result")),
                    json.dumps(payload.get("output") or []),
                    payload.get("error"),
                    cmd_id,
                ),
            )
            return True

    def results(self, member_id: int | None, after: int = 0) -> list[dict]:
        with self._conn() as c:
            if member_id is None:
                rows = c.execute(
                    "SELECT * FROM commands WHERE id > ? AND status IN ('done','error','expired')"
                    " ORDER BY id LIMIT 100",
                    (after,),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM commands WHERE member_id=? AND id > ?"
                    " AND status IN ('done','error','expired') ORDER BY id LIMIT 100",
                    (member_id, after),
                ).fetchall()
            return [
                {
                    "id": r["id"],
                    "member_id": r["member_id"],
                    "status": r["status"],
                    "code": (r["code"] or "").splitlines()[0][:120] if r["code"] else "",
                    "result": json.loads(r["result"]) if r["result"] else None,
                    "output": json.loads(r["output"]) if r["output"] else [],
                    "error": r["error"],
                }
                for r in rows
            ]

    def pending(self, member_id: int) -> int:
        with self._conn() as c:
            return int(c.execute(
                "SELECT COUNT(*) FROM commands WHERE member_id=? AND status IN ('queued','sent')",
                (member_id,),
            ).fetchone()[0])
