"""
Motor Town motorpedia (in-game Help/Encyclopedia) lookup module.

The motorpedia is the game's built-in guide collection (the `Helps` DataTable),
compiled from the client PAK into `knowledge_guides/motorpedia_guide.md`.

Two roles, mirroring how a compact index + full content is fed to an LLM:

- ``get_index()``  -> a compact "title: brief description" block injected into the
  prompt so the model knows what articles exist.
- ``lookup(topic)`` -> returns the full text of the article matching a topic, for
  on-demand retrieval (the `run motorpedia <topic>` verb).

The index (titles + one-line summaries) rides in every prompt; the full article
body is only fetched when relevant — the same compact-index + on-demand pattern
Hermes uses for skills.
"""

import logging
import os
import re

log = logging.getLogger(__name__)

GUIDE_PATH = os.path.join(
    os.path.dirname(__file__), "knowledge_guides", "motorpedia_guide.md"
)

_cache: dict[str, str] | None = None


def _load() -> dict[str, str]:
    """Parse motorpedia_guide.md into {title: body}."""
    global _cache
    if _cache is not None:
        return _cache
    articles: dict[str, str] = {}
    try:
        with open(GUIDE_PATH, "r", encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        log.warning("motorpedia guide not found at %s", GUIDE_PATH)
        _cache = articles
        return articles

    lines = text.splitlines()
    current: str | None = None
    body: list[str] = []
    for line in lines:
        if line.startswith("## "):
            if current:
                articles[current] = "\n".join(body).strip()
            current = line[3:].strip()
            body = []
        else:
            body.append(line)
    if current:
        articles[current] = "\n".join(body).strip()

    _cache = articles
    log.info("Loaded %d motorpedia articles from %s", len(articles), GUIDE_PATH)
    return articles


def _brief(body: str, maxlen: int = 110) -> str:
    """One-line plain-text summary of an article body."""
    t = body.replace("\n", " ")
    t = re.sub(r"<[^>]+>", "", t)          # rich-text tags
    t = re.sub(r"\*+", "", t)              # bold markers
    t = re.sub(r"\[image:[^\]]*\]", "", t) # image placeholders
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > maxlen:
        t = t[:maxlen].rstrip() + "…"
    return t


def get_index(limit_chars: int = 4000) -> str:
    """Compact 'title: brief description' block for the system prompt."""
    articles = _load()
    if not articles:
        return ""
    lines = [
        "## Motorpedia (In-Game Help/Encyclopedia)",
        "The game's built-in guide articles. Use the `run` tool verb "
        "'motorpedia <topic>' to fetch the full text of a matching article.",
    ]
    budget = limit_chars
    for title, body in articles.items():
        entry = f"- {title}: {_brief(body)}"
        if budget <= 0:
            break
        if len(entry) > budget:
            break
        budget -= len(entry) + 1
        lines.append(entry)
    return "\n".join(lines)


def lookup(topic: str) -> str:
    """Return the full text of the motorpedia article matching ``topic``.

    Matching order: exact title, title substring, then best keyword overlap
    on title+body. Returns a list of available titles when nothing matches.
    """
    articles = _load()
    if not articles:
        return "Motorpedia is not loaded."

    topic = (topic or "").strip().lower()
    if not topic:
        return "Error: topic required. Usage: motorpedia <topic>"

    # 1. exact title
    for title, body in articles.items():
        if title.lower() == topic:
            return f"{title}\n\n{body}"

    # 2. title substring
    for title, body in articles.items():
        if topic in title.lower():
            return f"{title}\n\n{body}"

    # 3. keyword overlap, weighting title matches much higher than body matches.
    _STOP = {
        "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
        "is", "are", "be", "it", "you", "your", "how", "what", "when", "where",
        "why", "can", "do", "does", "doesn", "not", "no", "any", "use", "some",
        "that", "this", "by", "at", "from", "as", "has", "have", "i", "me",
    }
    words = set(re.findall(r"[a-z0-9]+", topic)) - _STOP
    if not words:
        available = ", ".join(articles.keys())
        return f"No motorpedia article matched '{topic.strip()}'. Available topics: {available}"

    best_title: str | None = None
    best_body: str | None = None
    best_score = 0
    for title, body in articles.items():
        title_words = set(re.findall(r"[a-z0-9]+", title.lower()))
        hay_words = set(re.findall(r"[a-z0-9]+", re.sub(r"<[^>]+>", "", body).lower()))
        tscore = len(words & title_words) * 10      # a title match dominates
        bscore = len(words & hay_words)             # body keyword overlap
        score = tscore + bscore
        if score > best_score:
            best_score = score
            best_title, best_body = title, body
    # Title hit (tscore >= 10) OR a strong body match (>=2 keywords) is meaningful.
    if best_title and (best_score >= 10 or best_score >= 2):
        return f"{best_title}\n\n{best_body}"

    available = ", ".join(articles.keys())
    return f"No motorpedia article matched '{topic.strip()}'. Available topics: {available}"
