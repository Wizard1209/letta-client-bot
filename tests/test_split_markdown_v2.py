import pytest

from letta_bot.response_handler import split_markdown_v2


def test_short_and_deterministic():
    """Short text should not be split and output should be deterministic."""
    text = 'Hello **world**! This is a _test_ message with `code`.'
    result1 = split_markdown_v2(text, limit=100)
    result2 = split_markdown_v2(text, limit=100)

    # Should not be split
    assert len(result1) == 1
    # Should be deterministic
    assert result1 == result2
    # Should preserve the original text
    assert result1[0] == text


@pytest.mark.parametrize(
    'recommended_margin, safety_margin',
    [(400, 50), (50, 10)],
)
def test_split_behavior_with_different_margins(recommended_margin, safety_margin):
    """Long text should split properly; smaller margins produce more chunks."""
    text = ('Line of words ' * 40 + '\n') * 50  # ~20k chars
    result = split_markdown_v2(
        text,
        limit=500,
        recommended_margin=recommended_margin,
        safety_margin=safety_margin,
    )
    assert len(result) > 1, 'Text exceeding limit should be split'

    # For smaller margins, splitting should be more aggressive
    if recommended_margin < 400:
        default = split_markdown_v2(text, limit=500)
        assert len(result) >= len(default)


@pytest.mark.parametrize('token', ['*', '_', '`', '~', '```'])
def test_markdown_tokens_preserved_and_balanced(token):
    """Ensure markdown tokens remain balanced and correctly closed across splits."""
    if token == '```':
        text = f'{token}' + ('code ' * 1000) + f'{token}'
    else:
        text = f'{token}word{token} ' * 500

    chunks = split_markdown_v2(text, limit=500)

    # Ensure text integrity
    assert ''.join(chunks) == text

    # For code fences, verify proper closure per chunk (except last)
    if token == '```':
        for chunk in chunks[:-1]:
            assert chunk.endswith('```'), 'Chunk should close code block properly'


def test_handles_escaped_tokens_correctly():
    """Escaped markdown tokens should not be treated as formatting markers."""
    text = 'Escaped \\*not italic\\* but *italic*.'
    result = split_markdown_v2(text)

    assert ''.join(result) == text
    assert '\\*not italic\\*' in result[0]
    assert '*italic*' in result[0]


def test_nested_markdown_tokens():
    """Ensure nested markdown tokens are handled properly."""
    text = '*italic **and bold** text* repeated ' * 100
    chunks = split_markdown_v2(text, limit=300)
    assert ''.join(chunks) == text


def test_empty_input_returns_single_chunk():
    """Empty input should return a single empty string chunk."""
    assert split_markdown_v2('') == ['']


def test_large_code_block_splits_into_two_chunks():
    """Verify that a large code block splits correctly with proper closure/reopening."""
    # Build text: 400 'a' chars + newline + code block with 4000 chars + newline + 400 'a' chars
    # Total: 400 + 1 + 3 (```) + 4000 + 3 (```) + 1 + 400 = 4808 chars
    # Should split into 2 chunks with default limit of 4096
    prefix = 'a' * 400
    code_content = 'x' * 4000
    suffix = 'a' * 400
    text = f'{prefix}\n```{code_content}```\n{suffix}'

    chunks = split_markdown_v2(text, limit=4096)

    # Should split into exactly 2 chunks
    assert len(chunks) == 2, f'Expected 2 chunks, got {len(chunks)}'

    # Each chunk should respect the limit
    assert all(
        len(chunk) <= 4096 for chunk in chunks
    ), 'All chunks should be within limit'

    # First chunk should close the code block properly
    assert chunks[0].endswith('```'), 'First chunk should close code block'

    # Second chunk should reopen the code block
    assert chunks[1].startswith('```'), 'Second chunk should reopen code block'

    # Joined chunks should equal original text
    assert ''.join(chunks) == text, 'Joined chunks should match original text'

    # Verify the prefix is in first chunk and suffix is in second chunk
    assert chunks[0].startswith(prefix), 'First chunk should start with prefix'
    assert chunks[1].endswith(suffix), 'Second chunk should end with suffix'
