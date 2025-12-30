"""Tests for md_tg renderer - entity types and UTF-16 correctness."""

from aiogram.types import MessageEntity
import pytest

from md_tg import markdown_to_telegram
from md_tg.utils import utf16_len

# ============================================================================
# Basic entity types
# ============================================================================


@pytest.mark.parametrize(
    ('markdown', 'expected_entity_type'),
    [
        ('**bold**', 'bold'),
        ('*italic*', 'italic'),
        ('~~strikethrough~~', 'strikethrough'),
        ('`code`', 'code'),
        ('[Link](https://example.com)', 'text_link'),
        ('```python\ncode\n```', 'pre'),
        ('> quote', 'blockquote'),
        ('<div>\nhtml\n</div>', 'pre'),
        ('<strong>inline</strong>', 'code'),
    ],
)
def test_entity_types(markdown: str, expected_entity_type: str) -> None:
    """Basic entity types must be generated correctly."""
    chunks = markdown_to_telegram(markdown)
    _, entities = chunks[0]

    entity_types = [e.type for e in entities]
    assert expected_entity_type in entity_types, (
        f'Expected {expected_entity_type} entity in {entity_types}'
    )


# ============================================================================
# Inline code trailing whitespace
# ============================================================================


def test_inline_code_trailing_space_excluded_from_entity() -> None:
    """Inline code entity must exclude trailing whitespace.

    Per Telegram API: entity length must NOT include trailing whitespace.
    """
    chunks = markdown_to_telegram('Text with `code ` here')
    text, entities = chunks[0]

    code_entity = next(e for e in entities if e.type == 'code')
    offset = code_entity.offset
    length = code_entity.length
    entity_text = text[offset : offset + length]

    # Entity must NOT include trailing space
    assert not entity_text.endswith(' '), (
        f'Code entity includes trailing space: {entity_text!r}'
    )
    assert entity_text == 'code', f'Expected "code", got {entity_text!r}'


@pytest.mark.parametrize('trailing', [' ', '\n', '\t', '  \n'])
def test_inline_code_various_trailing_whitespace(trailing: str) -> None:
    """All types of trailing whitespace must be excluded."""
    markdown = f'`code{trailing}` text'
    chunks = markdown_to_telegram(markdown)
    text, entities = chunks[0]

    code_entity = next(e for e in entities if e.type == 'code')
    offset = code_entity.offset
    length = code_entity.length
    entity_text = text[offset : offset + length]

    assert entity_text == 'code', f'Expected "code", got {entity_text!r}'


def test_entity_length_excludes_trailing_whitespace_next_offset_includes() -> None:
    """Telegram API requirement from https://core.telegram.org/api/entities#entity-length

    Note: the length of an entity must NOT include the length of trailing newlines
    or whitespaces, rtrim entities before computing their length: however, the next
    offset must include the length of newlines or whitespaces that precede it.

    Uses inline code because mistune preserves trailing spaces in code spans.
    """
    markdown = '`code ` and `more`'
    chunks = markdown_to_telegram(markdown)
    text, entities = chunks[0]

    code_entities = [e for e in entities if e.type == 'code']
    assert len(code_entities) == 2, f'Expected 2 code entities, got {len(code_entities)}'

    # Helper to extract entity text using UTF-16 offsets
    def extract_entity_text(entity: MessageEntity) -> str:
        text_utf16 = text.encode('utf-16-le')
        offset_bytes = entity.offset * 2
        length_bytes = entity.length * 2
        return text_utf16[offset_bytes : offset_bytes + length_bytes].decode('utf-16-le')

    first_text = extract_entity_text(code_entities[0])
    second_text = extract_entity_text(code_entities[1])

    # Entity length must NOT include trailing whitespace
    assert first_text == 'code', f'Expected "code", got {first_text!r}'
    assert second_text == 'more', f'Expected "more", got {second_text!r}'

    # Next offset must INCLUDE preceding whitespace
    first_end = code_entities[0].offset + code_entities[0].length
    gap = code_entities[1].offset - first_end
    expected_gap = utf16_len('  and ')  # Trailing space from first + " and "

    assert gap == expected_gap, (
        f'Gap between entities: {gap} != {expected_gap}. '
        f'Next offset must include preceding whitespace!'
    )


# ============================================================================
# Link URL validation (security)
# ============================================================================


@pytest.mark.parametrize(
    ('markdown', 'should_have_link', 'expected_text_fragment'),
    [
        # Valid URLs
        ('[HTTP](http://example.com)', True, 'HTTP'),
        ('[HTTPS](https://example.com)', True, 'HTTPS'),
        ('[TG](tg://resolve?domain=test)', True, 'TG'),
        # Invalid: localhost/loopback (security) - rendered as text with URL
        ('[Localhost](http://localhost)', False, 'Localhost (http://localhost)'),
        ('[Loopback](http://127.0.0.1)', False, 'Loopback (http://127.0.0.1)'),
        # Invalid: unsupported schemes - rendered as text with URL
        ('[Anchor](#introduction)', False, 'Anchor (#introduction)'),
        ('[Relative](page.html)', False, 'Relative (page.html)'),
        ('[Mail](mailto:test@example.com)', False, 'Mail (mailto:test@example.com)'),
    ],
)
def test_link_url_validation(
    markdown: str, should_have_link: bool, expected_text_fragment: str
) -> None:
    """Only valid URLs create text_link entities (security).

    Telegram requires publicly accessible HTTP/HTTPS URLs or tg:// scheme.
    Rejects: fragments, relative paths, localhost, 127.0.0.1, mailto, etc.
    Invalid URLs are rendered as plain text with URL in parentheses.
    """
    chunks = markdown_to_telegram(markdown)
    text, entities = chunks[0]

    link_entities = [e for e in entities if e.type == 'text_link']

    if should_have_link:
        assert len(link_entities) == 1, f'Expected text_link for {markdown}'
    else:
        assert len(link_entities) == 0, f'Expected NO text_link for {markdown}'

    # Check that expected text fragment is present
    assert expected_text_fragment in text, (
        f'Expected {expected_text_fragment!r} in {text!r}'
    )


def test_link_url_attribute() -> None:
    """text_link entity must have url attribute."""
    chunks = markdown_to_telegram('[Google](https://google.com)')
    _, entities = chunks[0]

    link_entity = next(e for e in entities if e.type == 'text_link')
    assert link_entity.url is not None, 'text_link entity missing url attribute'
    assert link_entity.url == 'https://google.com'


# ============================================================================
# Code blocks with language preservation
# ============================================================================


@pytest.mark.parametrize(
    ('markdown', 'expected_language'),
    [
        ('```python\ncode\n```', 'python'),
        ('```javascript\ncode\n```', 'javascript'),
        ('```rust\ncode\n```', 'rust'),
        ('```\ncode\n```', None),
        ('<div>html</div>', 'html'),
    ],
)
def test_code_block_language_preservation(
    markdown: str, expected_language: str | None
) -> None:
    """Code block language must be preserved in entity."""
    chunks = markdown_to_telegram(markdown)
    _, entities = chunks[0]

    pre_entity = next(e for e in entities if e.type == 'pre')

    if expected_language:
        assert pre_entity.language is not None, 'pre entity missing language attribute'
        assert pre_entity.language == expected_language
    else:
        assert pre_entity.language is None, 'pre entity should not have language'


# ============================================================================
# UTF-16 offset correctness with emoji
# ============================================================================


def test_utf16_offsets_with_emoji() -> None:
    """Entity offsets must be correct with emoji (2 UTF-16 units).

    Telegram API uses UTF-16 for entity offsets. Emoji are 2 UTF-16 units.
    """
    chunks = markdown_to_telegram('Hello 🔥 **world**')
    text, entities = chunks[0]

    # Find bold entity
    bold_entity = next(e for e in entities if e.type == 'bold')

    # Extract text using UTF-16 offsets
    text_utf16 = text.encode('utf-16-le')
    offset_bytes = bold_entity.offset * 2  # Each UTF-16 unit is 2 bytes
    length_bytes = bold_entity.length * 2
    entity_text_bytes = text_utf16[offset_bytes : offset_bytes + length_bytes]
    entity_text = entity_text_bytes.decode('utf-16-le')

    # Entity text must match
    assert 'world' in entity_text, f'Expected "world", got {entity_text!r}'


def test_utf16_entity_bounds_with_unicode() -> None:
    """All entities must be within UTF-16 text bounds."""
    # Mixed content: emoji, Cyrillic, Chinese, formatting
    markdown = '🔥 Привет **世界** `code` 😀'
    chunks = markdown_to_telegram(markdown)
    text, entities = chunks[0]

    text_len_utf16 = utf16_len(text)

    for entity in entities:
        # Entity must not exceed text length
        assert entity.offset + entity.length <= text_len_utf16, (
            f'Entity {entity.type} out of bounds: '
            f'offset={entity.offset}, length={entity.length}, '
            f'text_len={text_len_utf16}'
        )


# ============================================================================
# Multiple entities in sequence
# ============================================================================


def test_multiple_entities_sequence() -> None:
    """Multiple entities in sequence must have correct offsets."""
    chunks = markdown_to_telegram('**bold** then *italic* then `code`')
    text, entities = chunks[0]

    # Should have 3 entities
    assert len(entities) == 3, f'Expected 3 entities, got {len(entities)}'

    # All entity types must be present
    entity_types = {e.type for e in entities}
    assert entity_types == {'bold', 'italic', 'code'}

    # Entities must be ordered by offset
    for i in range(len(entities) - 1):
        assert entities[i].offset <= entities[i + 1].offset, (
            'Entities not ordered by offset'
        )


# ============================================================================
# List and task list rendering
# ============================================================================


@pytest.mark.parametrize(
    ('markdown', 'expected_text'),
    [
        # Regular lists
        ('- Item', '• Item'),
        ('1. Item', '1. Item'),
        # Task lists
        ('- [ ] Todo', '☑ Todo'),
        ('- [x] Done', '✅ Done'),
    ],
)
def test_list_items(markdown: str, expected_text: str) -> None:
    """List items and task lists must render with correct prefixes."""
    chunks = markdown_to_telegram(markdown)
    text, _ = chunks[0]
    assert expected_text in text


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
