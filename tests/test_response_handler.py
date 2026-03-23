"""Tests for response_handler formatting and merge_with_entity fixes.

Covers:
- _make_code_fence: backtick escaping for nested code blocks
- merge_with_entity(parse_markdown=False): plain text in wrapping entity
- Large content chunking for reasoning and tool call messages
"""

import json

from aiogram.utils.formatting import Italic

from letta_bot.response_handler import (
    _format_tool_call,
    _make_code_fence,
)
from letta_bot.utils import merge_with_entity
from md_tg import markdown_to_telegram
from md_tg.config import DEFAULT_CONFIG
from md_tg.utils import utf16_len

MAX_CHUNK_LENGTH = DEFAULT_CONFIG.max_chunk_length


def _assert_all_chunks_within_limit(
    chunks: list[tuple[str, list[object]]],
) -> None:
    """Verify all chunks respect Telegram's 4096 limit and entity bounds."""
    for i, (text, entities) in enumerate(chunks):
        text_len = utf16_len(text)
        assert text_len <= MAX_CHUNK_LENGTH, (
            f'Chunk {i} exceeds limit: {text_len} > {MAX_CHUNK_LENGTH}'
        )
        for entity in entities:
            assert entity.offset + entity.length <= text_len, (  # type: ignore[union-attr]
                f'Chunk {i} entity {entity.type} out of bounds'  # type: ignore[union-attr]
            )


# ============================================================================
# _make_code_fence
# ============================================================================


def test_make_code_fence_escapes_inner_backticks() -> None:
    """Fence must be longer than any backtick run inside content."""
    # No backticks -> ```
    result_0 = _make_code_fence('code', 'py')
    assert result_0.startswith('```py\n')
    assert result_0.endswith('\n```')

    # Single backtick -> ```  (unchanged)
    assert _make_code_fence('use `x` here', 'py').startswith('```py\n')

    # Triple backticks inside -> ````
    content_3 = 'before\n```\ninner\n```\nafter'
    result_3 = _make_code_fence(content_3, 'diff')
    assert result_3.startswith('````diff\n')
    assert result_3.endswith('````')
    assert content_3 in result_3

    # Quadruple backticks inside -> `````
    content_4 = '````\ndeep\n````'
    result_4 = _make_code_fence(content_4, '')
    assert result_4.startswith('`````\n')
    assert result_4.endswith('`````')


# ============================================================================
# merge_with_entity(parse_markdown=False): reasoning
# ============================================================================


def test_merge_no_markdown_no_inner_entities() -> None:
    """parse_markdown=False must produce no inner entities."""
    content = '**bold** `code` [link](https://example.com)'
    chunks = merge_with_entity(
        header=Italic('Header:'),
        content=content,
        entity_type='expandable_blockquote',
        parse_markdown=False,
    )

    _, entities = chunks[0]
    entity_types = {e.type for e in entities}
    assert 'bold' not in entity_types
    assert 'code' not in entity_types
    assert 'text_link' not in entity_types
    assert 'expandable_blockquote' in entity_types


def test_merge_no_markdown_blockquote_covers_all_content() -> None:
    """Blockquote entity must span from header end to text end."""
    content = 'Line 1\nLine 2\nLine 3'
    chunks = merge_with_entity(
        header=Italic('Header:'),
        content=content,
        entity_type='expandable_blockquote',
        parse_markdown=False,
    )

    text, entities = chunks[0]
    bq = next(e for e in entities if e.type == 'expandable_blockquote')

    text_utf16 = text.encode('utf-16-le')
    bq_text = text_utf16[bq.offset * 2 : (bq.offset + bq.length) * 2].decode('utf-16-le')
    assert 'Line 1' in bq_text
    assert 'Line 3' in bq_text


# ============================================================================
# Large content: chunks within Telegram limit
# ============================================================================


def test_large_reasoning_chunks_within_limit() -> None:
    """Large reasoning (parse_markdown=False) must split and stay within limit."""
    content = '\n\n'.join(f'Section {i}: ' + 'a' * 300 for i in range(50))
    assert len(content) > MAX_CHUNK_LENGTH

    chunks = merge_with_entity(
        header=Italic('Agent reasoning:'),
        content=content,
        entity_type='expandable_blockquote',
        parse_markdown=False,
    )

    assert len(chunks) >= 2, 'Expected multiple chunks'
    _assert_all_chunks_within_limit(chunks)

    # Every chunk must have exactly one expandable_blockquote
    for i, (_, entities) in enumerate(chunks):
        bq = [e for e in entities if e.type == 'expandable_blockquote']
        assert len(bq) == 1, f'Chunk {i} missing blockquote'

    # No inner formatting entities
    for _, entities in chunks:
        for e in entities:
            assert e.type in ('expandable_blockquote', 'italic')


def test_large_tool_diff_chunks_within_limit() -> None:
    """Large memory str_replace diff must split and stay within limit."""
    old = '\n'.join(f'line {i}: old content here' for i in range(300))
    new = '\n'.join(f'line {i}: new content here' for i in range(300))

    result = _format_tool_call(
        'memory',
        json.dumps(
            {
                'command': 'str_replace',
                'path': '/memories/large_block',
                'old_string': old,
                'new_string': new,
            }
        ),
    )
    assert isinstance(result, str)

    chunks = markdown_to_telegram(result)
    assert len(chunks) >= 2, 'Expected large diff to split'
    _assert_all_chunks_within_limit(chunks)


def test_tool_diff_with_inner_backticks_single_pre() -> None:
    """Diff containing ``` must render as single pre block, not broken."""
    result = _format_tool_call(
        'memory',
        json.dumps(
            {
                'command': 'str_replace',
                'path': '/memories/test',
                'old_string': '```\nold code\n```',
                'new_string': '```\nnew code\n```',
            }
        ),
    )
    assert isinstance(result, str)

    chunks = markdown_to_telegram(result)
    pre_count = sum(len([e for e in entities if e.type == 'pre']) for _, entities in chunks)
    assert pre_count == 1, (
        f'Expected exactly 1 pre entity across all chunks, got {pre_count}'
    )


# ============================================================================
# memory create: backticks and chunking
# ============================================================================


def test_memory_create_with_inner_backticks_single_pre() -> None:
    """memory create with ``` in file_text must render as single pre block."""
    result = _format_tool_call(
        'memory',
        json.dumps(
            {
                'command': 'create',
                'path': '/memories/test',
                'description': 'test block',
                'file_text': (
                    'Use the API:\n\n'
                    '```python\nimport requests\n```\n\n'
                    'Then configure:\n\n'
                    '```json\n{"key": "value"}\n```'
                ),
            }
        ),
    )
    assert isinstance(result, str)

    chunks = markdown_to_telegram(result)
    for _, entities in chunks:
        pre_entities = [e for e in entities if e.type == 'pre']
        assert len(pre_entities) <= 1, (
            f'Inner backticks broke fence: {len(pre_entities)} pre entities'
        )


def test_memory_create_large_content_chunks_within_limit() -> None:
    """Large memory create file_text must split and stay within limit."""
    file_text = '\n'.join(f'line {i}: content here' for i in range(300))

    result = _format_tool_call(
        'memory',
        json.dumps(
            {
                'command': 'create',
                'path': '/memories/large_block',
                'description': 'large block',
                'file_text': file_text,
            }
        ),
    )
    assert isinstance(result, str)

    chunks = markdown_to_telegram(result)
    assert len(chunks) >= 2, 'Expected large content to split'
    _assert_all_chunks_within_limit(chunks)


# ============================================================================
# archival_memory_insert: backticks and chunking
# ============================================================================


def test_archival_insert_with_inner_backticks_single_pre() -> None:
    """archival_memory_insert with ``` in content must render as single pre."""
    result = _format_tool_call(
        'archival_memory_insert',
        json.dumps(
            {
                'content': (
                    'Use the API:\n\n'
                    '```python\nimport requests\n```\n\n'
                    'Then configure:\n\n'
                    '```json\n{"key": "value"}\n```'
                ),
                'tags': ['test'],
            }
        ),
    )
    assert isinstance(result, str)

    chunks = markdown_to_telegram(result)
    for _, entities in chunks:
        pre_entities = [e for e in entities if e.type == 'pre']
        assert len(pre_entities) <= 1, (
            f'Inner backticks broke fence: {len(pre_entities)} pre entities'
        )


def test_archival_insert_large_content_chunks_within_limit() -> None:
    """Large archival_memory_insert must split and stay within limit."""
    content = '\n'.join(f'line {i}: archival content' for i in range(300))

    result = _format_tool_call(
        'archival_memory_insert',
        json.dumps({'content': content}),
    )
    assert isinstance(result, str)

    chunks = markdown_to_telegram(result)
    assert len(chunks) >= 2, 'Expected large content to split'
    _assert_all_chunks_within_limit(chunks)
