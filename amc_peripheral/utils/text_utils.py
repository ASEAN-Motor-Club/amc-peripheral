import re


# Removes Unicode emoji glyphs so Annie's replies never contain characters the
# in-game Motor Town chat can't render (they come through as blank squares).
# Covers pictographs/emoticons/transport (U+1F000-1FAFF), misc symbols +
# dingbats (U+2600-27BF), emoji-presentation variation selector (VS16), the
# zero-width joiner (ZWJ sequences), regional-indicator flag pairs, and
# skin-tone modifiers. ASCII emoticons and kaomoji like ":)" or "(◕‿◕)" are NOT
# in these ranges, so they pass through untouched.
_EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"  # emoticons, pictographs, transport & symbols ext-A
    "\u2600-\u27BF"          # misc symbols + dingbats
    "\uFE0F"                 # emoji presentation (variation selector-16)
    "\u200D"                 # zero-width joiner (ZWJ sequences)
    "\U0001F1E6-\U0001F1FF"  # regional indicator symbols (flag pairs)
    "\U0001F3FB-\U0001F3FF"  # emoji skin-tone modifiers
    "]"
)


def strip_emoji(text: str | None) -> str:
    """Return ``text`` with Unicode emoji glyphs removed (ASCII emoticons kept)."""
    return _EMOJI_RE.sub("", text or "")


def truncate_reply(text: str | None, limit: int = 140) -> str:
    """Shorten a bot game-chat reply to ``limit`` chars, cutting at a word boundary.

    Game-chat replies must stay brief (output spec: under 140 characters).
    Cuts at the last whole word and appends an ASCII ellipsis ("..." renders
    fine in-game, unlike the U+2026 glyph). Combined with ``strip_emoji``
    applied inside ``announce_in_game``, the final message is always <= limit.
    """
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    head = text[: limit - 3]
    cut = head.rsplit(" ", 1)[0].rstrip() or head
    return cut + "..."


def is_code_block_open(text):
    """Return True if there's an unclosed code block in the text."""
    return text.count("```") % 2 == 1


def split_markdown(text, max_length=2000):
    """
    Split markdown text into chunks of up to max_length characters,
    ensuring that code blocks (and similar formatting) are not broken.
    """
    # Split by paragraphs while preserving the delimiters (empty lines)
    parts = re.split(r"(\n\s*\n)", text)
    chunks = []
    current_chunk = ""

    for part in parts:
        # Check if adding this part would exceed the maximum allowed length
        if len(current_chunk) + len(part) > max_length:
            if is_code_block_open(current_chunk):
                # If we're in the middle of a code block, close it in the current chunk.
                current_chunk += "\n```"
                chunks.append(current_chunk)
                # Start the next chunk by reopening the code block.
                current_chunk = "```\n" + part
            else:
                chunks.append(current_chunk)
                current_chunk = part
        else:
            current_chunk += part

    # Append any remaining text, closing an unclosed code block if necessary.
    if current_chunk:
        if is_code_block_open(current_chunk):
            current_chunk += "\n```"
        chunks.append(current_chunk)

    return chunks
