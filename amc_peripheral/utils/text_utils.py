import re


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
