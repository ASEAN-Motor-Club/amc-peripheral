"""
Motor Town wiki knowledge base.

Authoritative game knowledge reader that parses the PUBLIC DokuWiki page store
(wiki.aseanmotorclub.com) directly from disk, replacing ``game_db`` (the ETL
SQLite ``gamedata.db``) as the bot's source of vehicle/cargo/part/delivery-point
game facts. The wiki is maintained + curated and is strictly richer than the
stale ETL DB (per-Mod volume/fragile/pickup, production *location names*,
per-vehicle axle info, installable parts, etc.).

Two roles, mirroring how a compact index + full content is fed to an LLM:

- ``get_index()``  -> a compact "title:" cross-category block injected into the
  prompt so the model knows what exists.
- ``lookup_*()``   -> parse a single page (main + auto_infobox + auto_details)
  into a structured dict, for on-demand retrieval (the ``run <verb>`` tools).

Pages live at ``WIKI_PAGES_PATH`` (default the live DokuWiki store). A name is
resolved to its file via an index built from each item's display name (the
infobox ``name = X`` field, falling back to the main page title, then the slug).
The store is world-readable on the same host, so no HTTP dependency.

Any synchronous parse run from the async bot MUST be wrapped in
``await asyncio.to_thread(...)``.
"""

import logging
import os
import re
from typing import Any, Optional

log = logging.getLogger(__name__)

WIKI_PAGES_PATH = os.environ.get(
    "WIKI_PAGES_PATH",
    "/var/lib/dokuwiki/wiki.aseanmotorclub.com/data/pages",
)

# Map a bot verb/category to the DokuWiki page namespace directory.
CATEGORIES = {
    "vehicle": "vehicles",
    "cargo": "cargos",
    "part": "parts",
    "delivery_point": "delivery_points",
    "cargo_space": "cargo_space",
    "cargo_type": "cargo_type",
}

# Cache built once per process: category -> {lower_display_key: slug}
_INDEX: Optional[dict[str, dict[str, str]]] = None

# Search corpus: category -> {slug: (name, title, body)} — lazily built once.
_SEARCH_CORPUS: Optional[dict[str, dict[str, tuple[str, str, str]]]] = None


# --------------------------------------------------------------------------- #
# Retrieval
# --------------------------------------------------------------------------- #
def _page_path(category: str, slug: str) -> str:
    """Return the filesystem path of a category's main page."""
    namespace = CATEGORIES.get(category, category)
    return os.path.join(WIKI_PAGES_PATH, namespace, f"{slug}.txt")


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def _slug_from_filename(page_path: str) -> str:
    """``.../vehicles/tuscan.txt`` -> ``tuscan``."""
    return os.path.splitext(os.path.basename(page_path))[0]


def _normalize(s: str) -> str:
    """Lowercase + collapse whitespace for matching keys."""
    return re.sub(r"\s+", " ", s.strip().lower())


def _display_name(slug: str, infobox: dict, main_title: str) -> str:
    """Best display name: infobox ``name`` -> main page title -> slug."""
    if infobox.get("name"):
        return str(infobox["name"]).strip()
    if main_title:
        return main_title.strip()
    return slug


def _build_index() -> dict[str, dict[str, str]]:
    """Build {category: {lower_display_key: slug}} from the page store.

    Scans each category's directory for main ``<slug>.txt`` pages (and their
    ``<slug>/auto_infobox.txt`` sub-pages when present). Multiple keys per
    slug: the display name, a lowercased version, and the raw slug.
    """
    global _INDEX
    if _INDEX is not None:
        return _INDEX

    index: dict[str, dict[str, str]] = {}
    for category, namespace in CATEGORIES.items():
        cat_index: dict[str, str] = {}
        dirpath = os.path.join(WIKI_PAGES_PATH, namespace)
        if not os.path.isdir(dirpath):
            log.warning("wiki category dir missing: %s", dirpath)
            index[category] = cat_index
            continue

        for entry in os.listdir(dirpath):
            if not entry.endswith(".txt"):
                continue
            slug = entry[: -len(".txt")]
            main_path = os.path.join(dirpath, entry)

            infobox: dict = {}
            main_title = ""
            try:
                text = _read_text(main_path)
            except OSError:
                continue
            m = re.search(r"^======\s*(.+?)\s*======\s*$", text, re.MULTILINE)
            if m:
                main_title = m.group(1)

            # Read the auto_infobox sub-page if present (richer than the title).
            infobox_path = os.path.join(dirpath, slug, "auto_infobox.txt")
            if os.path.isfile(infobox_path):
                try:
                    infobox = _parse_infobox(_read_text(infobox_path))
                except OSError:
                    infobox = {}

            name = _display_name(slug, infobox, main_title)
            for key in (name, _normalize(name), _normalize(slug), _normalize(main_title)):
                k = _normalize(key)
                if k:
                    cat_index.setdefault(k, slug)

        index[category] = cat_index

    _INDEX = index
    return index


def _build_search_corpus() -> dict[str, dict[str, tuple[str, str, str]]]:
    """Lazily build a cross-category search corpus once per process.

    Returns ``{category: {slug: (name, title, body)}}`` where ``name`` is the
    best display name, ``title`` the main page heading, and ``body`` the first
    non-directive paragraph. Reading every page's *details* sub-pages for a
    search would be needlessly heavy, so this only scans the main ``<slug>.txt``
    for the title + intro paragraph plus the infobox for the display name —
    enough for lexical keyword matching, and cheap enough to hold every page in
    memory once.
    """
    global _SEARCH_CORPUS
    if _SEARCH_CORPUS is not None:
        return _SEARCH_CORPUS

    corpus: dict[str, dict[str, tuple[str, str, str]]] = {}
    for category, namespace in CATEGORIES.items():
        dirpath = os.path.join(WIKI_PAGES_PATH, namespace)
        if not os.path.isdir(dirpath):
            continue
        cat: dict[str, tuple[str, str, str]] = {}
        for entry in os.listdir(dirpath):
            if not entry.endswith(".txt"):
                continue
            slug = entry[: -len(".txt")]
            main_path = os.path.join(dirpath, entry)
            try:
                text = _read_text(main_path)
            except OSError:
                continue
            main_title = ""
            m = re.search(r"^======\s*(.+?)\s*======\s*$", text, re.MULTILINE)
            if m:
                main_title = m.group(1)
            # First paragraph (not an infobox/page directive) is the intro body.
            body = ""
            for para in text.split("\n\n"):
                p = para.strip()
                if p and not p.startswith("{{") and not p.startswith("="):
                    body = p
                    break
            # Infobox display name for the canonical name.
            infobox: dict = {}
            infobox_path = os.path.join(dirpath, slug, "auto_infobox.txt")
            if os.path.isfile(infobox_path):
                try:
                    infobox = _parse_infobox(_read_text(infobox_path))
                except OSError:
                    infobox = {}
            name = _display_name(slug, infobox, main_title)
            cat[slug] = (name, main_title, body)
        corpus[category] = cat

    _SEARCH_CORPUS = corpus
    return corpus


def _resolve_slug(category: str, query: str) -> Optional[str]:
    """Resolve a user query to a category slug (case/whitespace-insensitive).

    Exact match first, then substring among display-name keys; falls back to a
    plain substring on the raw slug.
    """
    if not query:
        return None
    index = _build_index()
    cat = index.get(category, {})
    q = _normalize(query)
    if q in cat:
        return cat[q]
    # Substring match keyed by the normalized display name.
    for key, slug in cat.items():
        if q in key or key in q:
            return slug
    # Substring on raw slug.
    for slug in set(cat.values()):
        if q in _normalize(slug):
            return slug
    return None


# --------------------------------------------------------------------------- #
# Parsers
# --------------------------------------------------------------------------- #
def _parse_infobox(text: str) -> dict:
    """Parse a ``{{infobox>`` ... ``}}`` block into {field: value}.

    Fields are ``key = value`` lines. Curly-brace content is split on the first
    ``\\n`` delimiting ``>`` from the body; links ``[[ns:slug|Label]]`` resolve
    to ``Label``.
    """
    d: dict[str, str] = {}
    body = text.split("{{infobox>", 1)[-1]
    body = body.split("}}", 1)[0]
    for line in body.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Resolve DokuWiki [[...|Label]] links to their Label.
        links = re.findall(r"\[\[[^\]|]+\|([^\]]+)\]\]", value)
        if links:
            value = ", ".join(dict.fromkeys(links))
        if key:
            d[key] = value
    return d


def _cells(line: str) -> tuple[bool, list[str]] | None:
    """Split a DokuWiki table/header row.

    Returns ``(is_header, cells)``, or None if ``line`` is not a table row.
    Header rows look like ``^ a ^ b ^`` (cells split on ``^``); data rows look
    like ``| a | b |`` (cells split on ``|``). The cell separator ``|`` is
    ignored when it's inside a DokuWiki ``[[page|label]]`` link.
    """
    s = line.strip()
    if not s:
        return None
    if s.startswith("|") and s.endswith("|"):
        delimiter = "|"
        is_header = False
    elif s.startswith("^") and s.endswith("^"):
        delimiter = "^"
        is_header = True
    else:
        return None
    # Drop the outer delimiters; split on the top-level delimiter only
    # (skipping those inside [[...]] links).
    body = s[1:-1]
    cells: list[str] = []
    buf: list[str] = []
    depth = 0
    prev = ""
    for ch in body:
        if ch == "[" and prev == "[":
            depth += 1
        elif ch == "]" and prev == "]" and depth:
            depth -= 1
        if ch == delimiter and depth == 0:
            cells.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
        prev = ch
    cells.append("".join(buf).strip())
    return (is_header, cells)


def _clean_cell(cell: str) -> str:
    """Resolve DokuWiki [[ns:page|Label]] links to their Label; strip markup."""
    # Replace [[...|Label]] with Label
    cell = re.sub(r"\[\[[^\]|]+\|([^\]]+)\]\]", r"\1", cell)
    # Collapse remaining [[...|...]] to the bare target
    cell = re.sub(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", r"\1", cell)
    # Trim stray whitespace / normalize internal spaces
    return re.sub(r"\s+", " ", cell).strip()


def _parse_details(text: str) -> dict[str, Any]:
    """Parse an auto_details page into a structured dict.

    Top-level ``===== Section =====`` headings become keys. Under a section:
      - ``^ A ^ B ^`` header + ``| a | b |`` rows  -> [{'col': value}, ...]
      - ``  * [[..|Label]]`` / ``- item``            -> ['Label', ...]
      - ``==== Sub ====`` sub-heading               -> nested {Sub: [...]}
    A section value is a dict {sub_heading: content} when it has sub-headings,
    otherwise a flat list.
    """
    sections: dict[str, Any] = {}
    current: Optional[str] = None
    current_headers: list[str] = []
    current_rows: list[dict[str, Any]] = []
    current_bullets: list[str] = []
    current_sub: Optional[str] = None
    current_sub_items: list[dict[str, Any]] = []
    current_sub_headers: list[str] = []

    def _flush_sub() -> None:
        nonlocal current_sub, current_sub_items, current_sub_headers
        if current is not None and current_sub is not None:
            subs = sections.setdefault(current, {})
            if not isinstance(subs, dict):
                subs = {}
                sections[current] = subs
            subs[current_sub] = list(current_sub_items) if current_sub_items else []
        current_sub = None
        current_sub_items = []
        current_sub_headers = []

    def _flush() -> None:
        nonlocal current, current_headers, current_bullets
        _flush_sub()
        if current is not None:
            if not isinstance(sections.get(current), dict):
                if current_rows:
                    value: Any = [dict(r) for r in current_rows]
                else:
                    value = list(current_bullets)
                sections[current] = value
        current = None
        current_headers = []
        current_bullets = []
        current_rows.clear()

    for line in text.splitlines():
        line = line.rstrip()
        m = re.match(r"^={5,}\s*(.*?)\s*={5,}$", line)
        if m:
            _flush()
            current = m.group(1).strip()
            continue
        if current is None:
            continue

        # Sub-heading (==== Sub ====) nests under the current section.
        ms = re.match(r"^={4,}\s*(.*?)\s*={4,}$", line)
        if ms and not line.startswith("|") and not line.startswith("^"):
            _flush_sub()
            current_sub = ms.group(1).strip()
            current_sub_headers = []
            continue

        cells_info = _cells(line)
        if cells_info is None:
            # Bullet / list item (top-level only)
            if line.lstrip().startswith("*") or line.lstrip().startswith("-"):
                item = line.lstrip()[1:].strip()
                links = re.findall(r"\[\[[^\]|]+\|([^\]]+)\]\]", item)
                current_bullets.append(links[0] if links else item)
            continue

        is_header_row, cells = cells_info
        if is_header_row:
            if current_sub is not None:
                current_sub_headers = cells
            else:
                current_headers = cells
            continue

        # Data row
        row: dict[str, Any] = {}
        headers = current_sub_headers if current_sub is not None else current_headers
        for i, cell in enumerate(cells):
            col = headers[i] if i < len(headers) else str(i)
            row[col] = _clean_cell(cell)
        if current_sub is not None:
            current_sub_items.append(row)
        else:
            current_rows.append(row)

    _flush()
    return sections


# --------------------------------------------------------------------------- #
# Public lookups
# --------------------------------------------------------------------------- #
def _load_page(category: str, slug: str) -> Optional[dict[str, Any]]:
    """Parse one category page (main + auto_infobox + auto_details) to a dict."""
    main_path = _page_path(category, slug)
    if not os.path.isfile(main_path):
        return None

    details: dict = {}
    infobox: dict = {}
    main_title = ""
    body = ""
    try:
        text = _read_text(main_path)
    except OSError:
        return None

    m = re.search(r"^======\s*(.+?)\s*======\s*$", text, re.MULTILINE)
    if m:
        main_title = m.group(1)
    # The first paragraph (the "X is a Y in Motor Town" blurb) is body.
    for para in text.split("\n\n"):
        p = para.strip()
        if p and not p.startswith("{{") and not p.startswith("="):
            body = p
            break

    ns = CATEGORIES.get(category, category)
    for sub, attr in (("auto_infobox", "infobox"), ("auto_details", "details")):
        sub_path = os.path.join(WIKI_PAGES_PATH, ns, slug, f"{sub}.txt")
        if os.path.isfile(sub_path):
            try:
                sub_text = _read_text(sub_path)
            except OSError:
                continue
            if attr == "infobox":
                infobox = _parse_infobox(sub_text)
            else:
                details = _parse_details(sub_text)

    name = _display_name(slug, infobox, main_title)
    return {
        "category": category,
        "slug": slug,
        "name": name,
        "title": main_title,
        "infobox": infobox,
        "body": body,
        "details": details,
    }


def _lookup(category: str, name: str) -> dict:
    """Resolve name -> page dict, or {'error': ...} on miss."""
    slug = _resolve_slug(category, name)
    if not slug:
        return {"error": f"No {category.replace('_', ' ')} found matching '{name}'"}
    page = _load_page(category, slug)
    if not page:
        return {"error": f"No {category.replace('_', ' ')} page for '{name}'"}
    return page


def lookup_vehicle(name: str) -> dict:
    """Full vehicle wiki page: infobox + specs + capabilities + default parts."""
    return _lookup("vehicle", name)


def lookup_cargo(name: str) -> dict:
    """Full cargo wiki page: specs + compatible spaces + production chain."""
    return _lookup("cargo", name)


def lookup_part(name: str) -> dict:
    """Full part wiki page: type/cost/stats + installable vehicles."""
    return _lookup("part", name)


def lookup_delivery_point(name: str) -> dict:
    """Full delivery-point wiki page: imports/exports + recipes + demand."""
    return _lookup("delivery_point", name)


def lookup_cargo_space(name: str) -> dict:
    """Cargo space type page (cargos/vehicles/parts that use it)."""
    return _lookup("cargo_space", name)


def lookup_cargo_type(name: str) -> dict:
    """Cargo type page (all cargos of that type, weights, payments)."""
    return _lookup("cargo_type", name)


def compare_vehicles(names: list[str]) -> list[dict]:
    """Side-by-side comparison of multiple vehicles (their pages), drops misses."""
    out = []
    for n in names:
        result = lookup_vehicle(n)
        if "error" not in result:
            out.append(result)
    return out


def _sanitize_query(query: str) -> str:
    """Strip control/NUL chars and normalize a search term for lexical matching.

    Mirrors the lexical-sanitize step of both DeepSeek Harness and Hermes: no
    synonym generation, no stemming, no query embedding — just trim, drop
    reserved/control chars, collapse whitespace, lowercase. The raw term then
    goes straight into a substring match.
    """
    cleaned = re.sub(r"[\x00-\x1f\x7f]", " ", query)
    return _normalize(cleaned)


def search_wiki(query: str, limit: int = 8) -> dict:
    """Plain lexical (substring) cross-category search — no embeddings, no query
    expansion.

    Identifies what an unknown term refers to when the caller doesn't yet know
    the right category (e.g. ``search_wiki('air city')`` → the ``vehicle`` Air
    City bus). The FULL sanitized term is matched as a substring against each
    page's name, then title, then slug, then description, in that priority
    order — there is no synonym/stem/embedding step. Any recall gap is the
    caller's to close by retrying a different phrasing (the model is coached to
    do this via the tool description). Returns matches across every category so
    the caller can then use the targeted ``lookup_*`` verb for full details.

    Returns:
        dict with ``results: [{category, slug, name, title}]`` or
        ``{"error": ...}`` for an empty query.
    """
    q = _sanitize_query(query)
    if not q:
        return {"error": "Search query required."}
    corpus = _build_search_corpus()

    hits: list[tuple[int, str, str, str, str]] = []  # (priority, cat, slug, name, title)
    for category, pages in corpus.items():
        for slug, (name, title, body) in pages.items():
            n_name = _normalize(name)
            n_title = _normalize(title)
            n_slug = _normalize(slug)
            n_body = _normalize(body)
            if q in n_name:
                prio = 1
            elif q in n_title:
                prio = 2
            elif q in n_slug:
                prio = 3
            elif q in n_body:
                prio = 4
            else:
                continue
            hits.append((prio, category, slug, name, title))

    hits.sort(key=lambda x: (x[0], x[1], x[2]))
    results = [
        {"category": c, "slug": s, "name": n, "title": t}
        for _, c, s, n, t in hits[:limit]
    ]
    if not results:
        return {"results": [], "note": f"No wiki pages matched '{query}'."}
    return {"results": results, "count": len(results)}


# --------------------------------------------------------------------------- #
# Prompt index + schema guide
# --------------------------------------------------------------------------- #
def get_index(limit_chars: int = 4000) -> str:
    """Compact cross-category knowledge index for the system prompt.

    Lists counts per category and a sample of display names, sized to fit the
    prompt. The model uses this to know what `run <verb>` can retrieve.
    """
    index = _build_index()
    lines = ["## Game Wiki Knowledge", "Game data is served from the wiki. Use the "
             "`run` tool's vehicle/cargo/part/deliverypoint/cargospace/cargotype verbs."]
    total = 0
    used = len("\n".join(lines))
    for category, cat_index in index.items():
        slugs = sorted(set(cat_index.values()))
        total += len(slugs)
        sample = ", ".join(_load_display_name(category, s) for s in slugs[:6])
        line = f"- {category.replace('_', ' ')} ({len(slugs)}): {sample}..."
        if used + len(line) > limit_chars:
            break
        lines.append(line)
        used += len(line)
    lines.append(f"({total} wiki pages indexed)")
    return "\n".join(lines)


def _load_display_name(category: str, slug: str) -> str:
    page = _load_page(category, slug)
    return page["name"] if page else slug


def get_schema_description() -> str:
    """Guide text describing the wiki knowledge layer for tool descriptions."""
    return (
        "Game knowledge comes from the Motor Town wiki page store at "
        f"{WIKI_PAGES_PATH}. Look up vehicles, cargos, parts, delivery points, "
        "cargo space types and cargo types with the `run` verbs (vehicle <name>, "
        "cargo <name>, part <name>, deliverypoint <name>, cargospace <type>, "
        "cargotype <type>, compare <v1,v2>). Each returns the curated wiki page "
        "with its Specifications / Capabilities / Default Parts / Production / "
        "Installable lists — the most current + comprehensive game data."
    )


def validate_schema() -> bool:
    """Check the page store is reachable and populated."""
    index = _build_index()
    return any(index.values())