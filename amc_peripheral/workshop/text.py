"""Small text rules shared by every member-authored field.

One rule set for profiles, item titles and summaries, collection titles and
descriptions, tags and comments. If a rule changes it changes here, so the
fields cannot drift apart.

What is removed, and why:

* C0 and C1 control characters, DEL and soft hyphen — they render as nothing or
  as garbage and can break layout.
* Unicode format characters: zero-width U+200B-U+200F, bidi overrides
  U+202A-U+202E and U+2066-U+2069, word joiner U+2060-U+2064, BOM U+FEFF. A bidi
  override reverses rendered text (spoofing), and a zero-width character inside
  a URL stops the URL rule from matching it.
* Invisible whitespace (NBSP, U+2000-U+200A, U+3000 and friends) becomes a
  normal space, so a field made only of those is empty rather than blank.
* URLs, with or without a scheme, and @everyone / @here. A public field is a
  free link farm and a free ping otherwise.
"""

from __future__ import annotations

import re

# Characters that should not exist in a public field at all.
_CONTROL = re.compile(
    "["
    "\x00-\x08\x0b\x0c\x0e-\x1f"  # C0, keeping \t and \n
    "\x7f-\x9f"  # DEL and C1
    "\u00ad"  # soft hyphen
    "\u200b-\u200f"  # zero width space/joiners and bidi marks
    "\u202a-\u202e"  # bidi embedding and override
    "\u2060-\u2064"  # word joiner and invisible operators
    "\u2066-\u2069"  # bidi isolates
    "\ufeff"  # BOM
    "]"
)

# Whitespace that reads as nothing on screen.
_ZSPACE = re.compile("[\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]")

# Common top-level domains, so "v1.2" and "Mr.T" are not mistaken for hosts.
_TLDS = (
    "com|net|org|io|gg|ly|co|me|dev|app|xyz|info|biz|tv|link|site|online|"
    "store|club|id|sg|my|th|vn|ph|to|cc|ru|cn|jp|kr|de|uk|us|ca|au"
)

_URL = re.compile(
    r"(?:"
    r"(?:https?|hxxps?|ftp)://\S+"
    r"|www\.\S+"
    rf"|\b[\w-]+(?:\.[\w-]+)*\.(?:{_TLDS})\b(?:/\S*)?"
    r")",
    re.IGNORECASE,
)

_MENTION = re.compile(r"@(?:everyone|here)\b", re.IGNORECASE)

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")

_SPACES = re.compile(r"[ \t]{2,}")
_NEWLINES = re.compile(r"\n{3,}")

# Combining marks live in these blocks; a run of them stacked on one letter
# ("zalgo") is unreadable and can make a page look broken.
_MARK = re.compile(
    "[\u0300-\u036f\u1ab0-\u1aff\u1dc0-\u1dff\u20d0-\u20ff\ufe20-\ufe2f]"
)
MARK_RATIO = 0.2
MARK_FLOOR = 10


def _strip_marks(text: str, *, field: str) -> str:
    marks = len(_MARK.findall(text))
    if marks < MARK_FLOOR:
        return text
    visible = len(_MARK.sub("", text))
    if marks > MARK_RATIO * max(visible, 1):
        raise ValueError(f"{field} has too many combining marks.")
    return text


def _scrub(value: str | None) -> str:
    """Everything both rules share, before whitespace and length handling."""
    text = value or ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Format characters first: removing them is what makes
    # "h<zero-width>ttps://" collapse into something the URL rule can see.
    text = _CONTROL.sub("", text)
    text = _ZSPACE.sub(" ", text)
    text = _URL.sub(" ", text)
    text = _MENTION.sub("", text)
    return text


def clean_text(value: str | None, *, limit: int, field: str) -> str:
    """Trim, drop controls, format characters and URLs, collapse spaces, cap length.

    URLs are stripped rather than rendered: a public field is a free link farm
    otherwise, and the club already has a place to share links.
    """
    text = _scrub(value)
    text = _SPACES.sub(" ", text)
    text = " ".join(text.split())
    text = _strip_marks(text, field=field)
    if len(text) > limit:
        raise ValueError(f"{field} is limited to {limit} characters.")
    return text


def clean_multiline(
    value: str | None,
    *,
    limit: int,
    field: str,
    lines_limit: int = 20,
) -> str:
    """Like :func:`clean_text` but keeps paragraph breaks.

    Comments and summaries read as prose; collapsing every newline would deliver
    them as one long line.
    """
    text = _scrub(value)
    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = _NEWLINES.sub("\n\n", text)
    text = "\n".join(_SPACES.sub(" ", line).strip() for line in text.split("\n")).strip(
        "\n"
    )
    text = _strip_marks(text, field=field)
    if not text.strip():
        raise ValueError(f"{field} is required.")
    if len(text) > limit:
        raise ValueError(f"{field} is limited to {limit} characters.")
    if text.count("\n") + 1 > lines_limit:
        raise ValueError(f"{field} is limited to {lines_limit} lines.")
    return text


def slugify(title: str, *, fallback: str = "collection") -> str:
    slug = _SLUG_STRIP.sub("-", title.lower()).strip("-")[:60].strip("-")
    return slug or fallback
