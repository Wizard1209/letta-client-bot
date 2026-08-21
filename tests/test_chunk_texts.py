"""Tests for chunk_texts generator."""

from aiogram.utils.formatting import Code, Text

from letta_bot.utils import chunk_texts


def test_single_chunk_when_small() -> None:
    """All parts fit in one chunk."""
    parts = [Text('Header'), Text('Item 1'), Text('Item 2')]
    chunks = list(chunk_texts(parts))
    assert len(chunks) == 1
    text, _ = chunks[0]
    assert 'Header' in text
    assert 'Item 1' in text
    assert 'Item 2' in text


def test_splits_when_exceeds_max_len() -> None:
    """Parts exceeding max_len are split into multiple chunks."""
    # Each item ~50 chars, max_len=100 → should split
    parts = [Text(f'Item {i}: ' + 'x' * 40) for i in range(5)]
    chunks = list(chunk_texts(parts, max_len=100))
    assert len(chunks) > 1

    # All items present across all chunks
    all_text = '\n'.join(text for text, _ in chunks)
    for i in range(5):
        assert f'Item {i}' in all_text


def test_entities_offsets_correct() -> None:
    """Entity offsets are adjusted correctly when parts are merged."""
    parts = [Text('Hello '), Text('World ', Code('123'))]
    chunks = list(chunk_texts(parts))
    assert len(chunks) == 1

    text, entities = chunks[0]
    # Code('123') should have an entity
    assert len(entities) == 1
    entity = entities[0]
    # Verify the entity points to '123' in the combined text
    # text = "Hello \nWorld 123" (with separator \n)
    assert text[entity.offset : entity.offset + entity.length] == '123'


def test_empty_input() -> None:
    """Empty input yields nothing."""
    chunks = list(chunk_texts([]))
    assert chunks == []


def test_single_large_part_still_yielded() -> None:
    """A single part larger than max_len is still yielded (not dropped)."""
    parts = [Text('x' * 5000)]
    chunks = list(chunk_texts(parts, max_len=100))
    assert len(chunks) == 1
    assert len(chunks[0][0]) == 5000


def test_custom_separator() -> None:
    """Custom separator is used between parts."""
    parts = [Text('A'), Text('B'), Text('C')]
    chunks = list(chunk_texts(parts, separator=' | '))
    assert len(chunks) == 1
    assert chunks[0][0] == 'A | B | C'
