"""Tests for md_tg converter - chunk limit validation.

All tests focus on the main requirement:
    Chunks MUST NOT exceed Telegram's 4096 UTF-16 character limit
    AND entities must stay within text boundaries.
"""

from aiogram.types import MessageEntity
import pytest

from md_tg.config import DEFAULT_CONFIG
from md_tg.converter import markdown_to_telegram
from md_tg.utils import utf16_len

MAX_CHUNK_LENGTH = DEFAULT_CONFIG.max_chunk_length


def _assert_chunks_within_limit(chunks: list[tuple[str, list[MessageEntity]]]) -> None:
    """Verify all chunks respect Telegram's 4096 limit and entity bounds.

    Args:
        chunks: List of (text, entities) tuples

    Raises:
        AssertionError: If any chunk exceeds limit or entity is out of bounds
    """
    for i, (text, entities) in enumerate(chunks):
        chunk_len = utf16_len(text)

        # Chunk must not exceed Telegram API limit
        assert chunk_len <= MAX_CHUNK_LENGTH, (
            f'Chunk {i} exceeds limit: {chunk_len} > {MAX_CHUNK_LENGTH}'
        )

        # All entities must be within text bounds
        text_len = utf16_len(text)
        for entity in entities:
            assert entity.offset + entity.length <= text_len, (
                f'Chunk {i} entity {entity.type} out of bounds: '
                f'offset={entity.offset}, length={entity.length}, text_len={text_len}'
            )


# ============================================================================
# Large code blocks (ASCII + emoji UTF-16)
# ============================================================================


@pytest.mark.parametrize(
    ('code_content', 'description'),
    [
        ('x' * 5000, 'ASCII'),
        ('🔥 ' * 2500, 'emoji (UTF-16 surrogate pairs)'),
    ],
)
def test_large_code_block_within_limit(code_content: str, description: str) -> None:
    """Large code blocks must not exceed 4096 limit.

    Tests both ASCII and emoji to ensure UTF-16 handling is correct.
    """
    markdown = f'```python\n{code_content}\n```'
    chunks = markdown_to_telegram(markdown)

    # Must produce multiple chunks for large content
    assert len(chunks) >= 2, f'Expected split for {description}'

    # Verify limits
    _assert_chunks_within_limit(chunks)


# ============================================================================
# Large paragraphs with inline formatting
# ============================================================================


def test_large_paragraph_with_inline_code_within_limit() -> None:
    """Large paragraphs with inline code must not exceed limit."""
    # Create paragraph exceeding limit with inline code
    inline_codes = ' '.join(f'`code{i}`' for i in range(1000))
    markdown = f'Text: {inline_codes}'

    chunks = markdown_to_telegram(markdown)

    # Should produce multiple chunks
    assert len(chunks) >= 2, 'Expected paragraph to split'

    # Verify limits
    _assert_chunks_within_limit(chunks)


def test_large_paragraph_with_mixed_formatting_within_limit() -> None:
    """Paragraphs with mixed formatting must preserve entity integrity."""
    # Paragraph with bold, italic, code
    parts = [f'**bold{i}** *italic{i}* `code{i}`' for i in range(500)]
    markdown = ' '.join(parts)

    chunks = markdown_to_telegram(markdown)

    # Verify limits
    _assert_chunks_within_limit(chunks)

    # Additional check: entities must have positive length
    for _, entities in chunks:
        for entity in entities:
            assert entity.length > 0, f'{entity.type} has zero length'


# ============================================================================
# Large lists
# ============================================================================


def test_large_list_within_limit() -> None:
    """Large lists must split without exceeding limit."""
    items = [
        f'Item {i} - description with enough text to ensure '
        f'the total content exceeds chunk limit'
        for i in range(200)
    ]
    markdown = '\n'.join(f'- {item}' for item in items)

    chunks = markdown_to_telegram(markdown)

    # Should produce multiple chunks
    assert len(chunks) >= 2, 'Expected list to split'

    # Verify limits
    _assert_chunks_within_limit(chunks)


# ============================================================================
# Large blockquotes
# ============================================================================


def test_large_blockquote_within_limit() -> None:
    """Large blockquotes must split without exceeding limit."""
    # Create blockquote with paragraphs exceeding limit
    paragraphs = [
        f'Paragraph {i} with some text to make it longer and exceed the limit'
        for i in range(100)
    ]
    markdown = '\n'.join(f'> {p}' for p in paragraphs)

    chunks = markdown_to_telegram(markdown)

    # Should produce multiple chunks
    assert len(chunks) >= 2, 'Expected blockquote to split'

    # Verify limits
    _assert_chunks_within_limit(chunks)


# ============================================================================
# Nested blockquotes
# ============================================================================


def test_nested_blockquote_within_limit() -> None:
    """Nested blockquotes must split without exceeding limit."""
    # Create nested blockquote
    inner_paragraphs = [f'Inner paragraph {i} with text' for i in range(50)]
    inner_blockquote = '\n'.join(f'>> {p}' for p in inner_paragraphs)

    outer_paragraphs = [f'Outer paragraph {i}' for i in range(50)]
    outer_lines = [f'> {p}' for p in outer_paragraphs]
    outer_lines.append(f'> {inner_blockquote}')

    markdown = '\n'.join(outer_lines)

    chunks = markdown_to_telegram(markdown)

    # Verify limits
    _assert_chunks_within_limit(chunks)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
