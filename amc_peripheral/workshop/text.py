"""Small text rules shared by every member-authored field."""

from __future__ import annotations

import re

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_SPACES = re.compile(r"[ \t]{2,}")


def clean_text(value: str | None, *, limit: int, field: str) -> str:
    """Trim, drop control characters and URLs, collapse spaces, cap length.

    URLs are stripped rather than rendered: a public field is a free link farm
    otherwise, and the club already has a place to share links.
    """
    text = (value or "").strip()
    text = _CONTROL.sub("", text)
    text = _URL.sub("", text)
    text = _SPACES.sub(" ", text).strip()
    if len(text) > limit:
        raise ValueError(f"{field} is limited to {limit} characters.")
    return text


def slugify(title: str, *, fallback: str = "collection") -> str:
    slug = _SLUG_STRIP.sub("-", title.lower()).strip("-")[:60].strip("-")
    return slug or fallback
