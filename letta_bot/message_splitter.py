"""Message splitting utilities for handling Telegram's message length limits.

This module provides utilities to split long messages while preserving aiogram formatting.
Uses aiogram's native Text slicing to maintain formatting trees (Bold, Italic, Code, etc.).
"""

from aiogram.types import Message
from aiogram.utils.formatting import Text

# Telegram hard limit is 4096, we use buffer for safety
SAFE_MAX_LENGTH = 4000


def find_split_point(text: str, max_pos: int) -> int:
    """Find optimal split point before max_pos.

    Boundary priority: newline > dot > character

    Args:
        text: Plain text to analyze for split point
        max_pos: Maximum position to split at

    Returns:
        Position to split at (inclusive of boundary character)
    """
    if max_pos >= len(text):
        return len(text)

    # Priority 1: Newline boundary
    split = text.rfind('\n', 0, max_pos)
    if split > max_pos * 0.75:  # Accept if reasonably close (75%+)
        return split + 1  # Include the newline

    # Priority 2: Dot boundary (sentence end)
    split = text.rfind('.', 0, max_pos)
    if split > max_pos * 0.8:  # Accept if reasonably close (80%+)
        return split + 1  # Include the dot

    # Priority 3: Hard split at max_pos
    return max_pos


def split_message(content: Text, max_length: int = SAFE_MAX_LENGTH) -> list[Text]:
    """Split formatted message at natural boundaries.

    Preserves all aiogram formatting (Bold, Italic, Code, etc.) by using
    Text's native slicing. Splits at newlines or dots when possible.

    Args:
        content: Formatted Text object to split
        max_length: Maximum length per chunk (default 4000)

    Returns:
        List of Text chunks, each under max_length

    Example:
        >>> from aiogram.utils.formatting import Text, Bold
        >>> content = Text(Bold('Long text...'), '...')
        >>> chunks = split_message(content)
        >>> for chunk in chunks:
        ...     await message.answer(**chunk.as_kwargs())
    """
    if len(content) <= max_length:
        return [content]

    # Render to plain text for boundary detection
    # Note: _collect_entities=False skips entity collection for performance
    plain_text, _ = content.render(_collect_entities=False)

    chunks: list[Text] = []
    pos = 0

    while pos < len(plain_text):
        # Calculate how much text we can take
        remaining = len(plain_text) - pos
        max_chunk = min(max_length, remaining)

        # Find smart split point in the substring
        split_at = find_split_point(plain_text[pos:], max_chunk)
        end = pos + split_at

        # Slice the formatted Text object (preserves formatting tree)
        chunk = content[pos:end]
        if len(chunk) > 0:  # Avoid empty chunks
            chunks.append(chunk)

        pos = end

    return chunks


async def send_long_message(message: Message, content: Text) -> None:
    """Send message, automatically splitting if it exceeds Telegram limits.

    Args:
        message: Telegram message to reply to
        content: Formatted Text content to send

    Example:
        >>> content = Text(Bold('Agent response:'), '\\n\\n', long_response)
        >>> await send_long_message(message, content)
    """
    for chunk in split_message(content):
        await message.answer(**chunk.as_kwargs())
