from letta_bot.response_handler import split_markdown_v2


def test_split_markdown_v2() -> None:
    assert split_markdown_v2('') == [''], 'Empty string should return a single empty chunk'

    short = 'Hello, *world!*'
    chunks = split_markdown_v2(short, limit=4096)
    assert chunks == [short], 'Short text should not be split'
    assert len(chunks) == 1, 'Should produce exactly one chunk'

    long_text = 'a' * 4200
    chunks = split_markdown_v2(long_text, limit=4096)
    assert len(chunks) == 2, 'Should split into exactly two chunks'
    assert all(len(c) <= 4096 for c in chunks), 'All chunks must respect the limit'

    md_text = '**bold** and *italic* ' * 300
    chunks = split_markdown_v2(md_text, limit=4096)
    assert len(chunks) >= 2, 'Should produce multiple chunks'
    assert all(len(c) <= 4096 for c in chunks), 'All chunks must respect the limit'
    for c in chunks:
        assert c.count('*') % 2 == 0, 'Unbalanced Markdown markers in chunk'

    prefix = 'a' * 400
    code_content = 'x' * 4000
    suffix = 'a' * 400
    text = f'{prefix}\n```{code_content}```\n{suffix}'
    chunks = split_markdown_v2(text, limit=4096)
    assert len(chunks) == 2, f'Expected 2 chunks, got {len(chunks)}'
    assert all(len(chunk) <= 4096 for chunk in chunks), 'All chunks should be within limit'
    assert chunks[0].endswith('```'), 'First chunk should close code block'
    assert chunks[1].startswith('```'), 'Second chunk should reopen code block'
    assert chunks[0].startswith(prefix), 'First chunk should start with prefix'
    assert chunks[1].endswith(suffix), 'Second chunk should end with suffix'

    reconstructed = ''.join(chunks).replace('``````', '```')
    assert prefix in reconstructed, 'Prefix must appear in reconstructed text'
    assert suffix in reconstructed, 'Suffix must appear in reconstructed text'

    exact = 'b' * 4096
    chunks = split_markdown_v2(exact, limit=4096)
    assert len(chunks) == 1, 'Exact limit text should not split'
    assert chunks[0] == exact, 'Chunk must equal the original text'

    text = 'This is escaped: \\*not bold\\*' * 300
    chunks = split_markdown_v2(text, limit=4096)
    assert all(c.count('*') % 2 == 0 for c in chunks)

    text = 'a' * 10000
    chunks = split_markdown_v2(text, limit=4096)
    assert all(len(c) <= 4096 for c in chunks), 'Chunk exceeds limit'
    assert ''.join(chunks) == text, 'Reconstructed text mismatch'
