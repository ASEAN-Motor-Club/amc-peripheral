"""Plain-text, Chroma-free durable memory for Annie.

Architecture-revamp substrate (freeman, 2026-08-20): ALL of Annie's knowledge
and memories live in plain text — no SQL queries, no vector databases. This
is the memory half: an agent-writable store of Markdown-body DokuWiki ``.txt``
pages under the public page store's ``memory/`` namespace, so memories are
web-renderable (native GFM via ``$conf['syntax']=\"dw+md\"``, DokuWiki
``======`` headings render reliably) and curated ``core/`` stays read-only to
the bot.

This mirrors ``MemoryStore`` (the SQLite+Chroma variant in ``wiki/memory.py``)
but drops both: durability is the filesystem, recall is a pure lexical search
(the wiki_kb/search_wiki mechanism: sanitize -> full-phrase substring -> rank
by field priority). No embedding layer, no retrieval dependency, no SQL.

Public API is intentionally compatible with ``MemoryStore`` so
``KnowledgeCog`` can construct either interchangeably:
``write_fact / delete / list_facts / recall / self_block``.
"""

from __future__ import annotations

import logging
import os
import re

from amc_peripheral.settings import PLAIN_MEMORY_PATH

log = logging.getLogger(__name__)

# Category -> subdirectory under the memory root.
# 'self'  -> standing "who I am" (always injected every turn)
# 'fact'  -> durable community/player/entity facts (recalled on demand)
# 'player'-> per-player memories (one file per player)
# 'event' -> per-event / incident notes
_CATEGORY_DIRS = {"self": "self", "fact": "facts", "player": "players", "event": "events"}

# DokuWiki page-ID charset allows [a-z0-9 _ - . :]; strip everything else
# (same constraint wiki_sync.py's slug mapper respects).
_SLUG_KEEP = re.compile(r"[^a-z0-9 _\-.:]")


def _slugify(title: str) -> str:
    """Turn a title into a filesystem-safe, DokuWiki-safe slug."""
    slug = _SLUG_KEEP.sub("", title.strip().lower())
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    return slug or "untitled"


def _page_path(root: str, category: str, slug: str) -> str:
    """Resolve a memory page's path, asserting it stays inside the root."""
    sub = _CATEGORY_DIRS.get(category, "facts")
    path = os.path.realpath(os.path.join(root, sub, f"{slug}.txt"))
    if not path.startswith(os.path.realpath(root) + os.sep) and path != os.path.realpath(root):
        raise ValueError(f"refusing memory path outside root: {path}")
    return path


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


class PlainTextMemory:
    """Durable, agent-writable plain-text memory over the wiki memory/ store.

    Files are Markdown-body DokuWiki ``.txt`` pages. A write lands as::

        ====== <Title> ======
        (category + summary block)
        <content markdown>

    Recall is lexical: sanitize the query, match it as a full phrase,
    rank by field priority (title > body), return the top matches.
    """

    SELF_CATEGORY = "self"
    FACT_CATEGORY = "fact"

    def __init__(self, root: str | None = None, category_dirs: dict[str, str] | None = None):
        self.root = os.path.realpath(root) if root else os.path.realpath(PLAIN_MEMORY_PATH)
        self.sub = category_dirs or _CATEGORY_DIRS
        for sub in set(self.sub.values()):
            os.makedirs(os.path.join(self.root, sub), exist_ok=True)

    # ------------------------------------------------------------------ #
    # Writes / deletes
    # ------------------------------------------------------------------ #
    def write_fact(
        self,
        title: str,
        content: str,
        category: str = "fact",
        summary: str = "",
    ) -> int:
        """Upsert a durable fact page as a plain-text file. Returns a stable
        pseudo-id (built from the slug) for compatibility with the MemoryStore
        callers that expect an int page id."""
        if not title or not content:
            raise ValueError("'title' and 'content' are required")
        if category not in self.sub:
            category = self.FACT_CATEGORY
        slug = _slugify(title)
        path = self._page_path(category, slug)

        lines = [f"====== {title} ======\n"]
        if summary:
            lines.append(f"*Summary:* {summary}\n")
        lines.append("")
        lines.append(content.rstrip("\n"))
        lines.append("")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return hash((category, slug)) % (2**31)

    def delete(self, title: str) -> bool:
        """Delete a memory page by title across all categories. True if gone."""
        slug = _slugify(title)
        for category in self.sub:
            path = self.page_path(category, slug, real=True)
            if os.path.isfile(path):
                os.remove(path)
                return True
        return False

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    def list_facts(self, category: str | None = None, limit: int = 50) -> list[dict]:
        """List memory pages (title, category, summary, content) in a category."""
        cats = [category] if category else list(self.sub)
        out: list[dict] = []
        for cat in cats:
            if cat not in self.sub:
                continue
            d = os.path.join(self.root, self.sub[cat])
            if not os.path.isdir(d):
                continue
            for fn in sorted(os.listdir(d)):
                if not fn.endswith(".txt"):
                    continue
                path = os.path.join(d, fn)
                try:
                    text = open(path, encoding="utf-8", errors="replace").read()
                except OSError:
                    continue
                slug = fn[: -len(".txt")]
                title, summary = _title_and_summary(text)
                out.append(
                    {
                        "title": title or slug,
                        "slug": slug,
                        "category": cat,
                        "summary": summary,
                        "content": text,
                    }
                )
        out.sort(key=lambda p: p["title"].lower())
        return out[:limit]

    def recall(self, query: str, n_results: int = 5) -> list[dict]:
        """Lexical full-phrase recall over memory/index pages.

        Matches the plain-text search mechanism the wiki_kb ``search`` verb
        uses: sanitize the query, then a literal substring match against each
        page's title, then body; ranked by field priority. No embeddings.
        """
        if not query:
            return []
        q = _normalize(query)
        if not q:
            return []
        scored: list[tuple[int, dict]] = []
        for cat in self.sub:
            d = os.path.join(self.root, self.sub[cat])
            if not os.path.isdir(d):
                continue
            for fn in os.listdir(d):
                if not fn.endswith(".txt"):
                    continue
                path = os.path.join(d, fn)
                try:
                    text = open(path, encoding="utf-8", errors="replace").read()
                except OSError:
                    continue
                normalized = _normalize(text)
                if q not in normalized:
                    continue
                slug = fn[: -len(".txt")]
                title, summary = _title_and_summary(text)
                # simple priority: full-phrase hit in the heading = strongest;
                # in the slug = strong; fall back to body occurrence.
                if q in _normalize(title or slug):
                    score = 3
                elif q in _normalize(slug):
                    score = 2
                else:
                    score = 1
                scored.append(
                    (
                        -score,
                        {
                            "page_id": hash((cat, slug)) % (2**31),
                            "title": title or slug,
                            "slug": slug,
                            "category": cat,
                            "content": text,
                            "summary": summary,
                        },
                    )
                )
        scored.sort(key=lambda t: (t[0], t[1]["title"].lower()))
        return [s[1] for s in scored[:n_results]]

    def self_block(self, limit_chars: int = 1500) -> str:
        """Render Annie's standing self-facts as a compact injected block.

        Matches MemoryStore.self_block: joins the ``self/`` pages' body.
        Empty string when there is nothing stored.
        """
        lines: list[str] = []
        budget = limit_chars
        d = os.path.join(self.root, self.sub[self.SELF_CATEGORY])
        if not os.path.isdir(d):
            return ""
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".txt"):
                continue
            text = open(os.path.join(d, fn), encoding="utf-8", errors="replace").read()
            body = _body(text).strip()
            if not body:
                continue
            if budget <= 0:
                break
            if len(body) > budget:
                body = body[:budget]
                budget = 0
            else:
                budget -= len(body) + 1
            lines.append(body)
        return "\n".join(lines).strip()

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def page_path(self, category: str, slug: str, real: bool = False) -> str:
        sub = self.sub.get(category, "facts")
        path = os.path.join(self.root, sub, f"{slug}.txt")
        return os.path.realpath(path) if real else path

    def _page_path(self, category: str, slug: str) -> str:
        return self.page_path(category, slug, real=False)


# module-level helpers (importable for tests)
def _title_and_summary(text: str) -> tuple[str, str]:
    """Pull the ``====== Title ======`` heading and ``*Summary:*`` line out of
    a memory page's text."""
    title = ""
    m = re.search(r"^======\s*(.+?)\s*======\s*$", text, re.MULTILINE)
    if m:
        title = m.group(1).strip()
    summary = ""
    m = re.search(r"^\*Summary:\*\s*(.+?)\s*$", text, re.MULTILINE)
    if m:
        summary = m.group(1).strip()
    return title, summary


def _body(text: str) -> str:
    """Return a memory page's body: drop the leading ``====== title ======``
    heading and the ``*Summary:*`` line."""
    lines = text.splitlines()
    out: list[str] = []
    for ln in lines:
        if re.match(r"^======\s+.+?\s*======\s*$", ln):
            continue
        if ln.startswith("*Summary:*"):
            continue
        out.append(ln)
    return "\n".join(out)