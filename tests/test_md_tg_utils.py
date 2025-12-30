"""Tests for md_tg.utils module."""

import pytest

from md_tg.utils import utf16_len

# ============================================================================
# TESTS: utf16_len function
# ============================================================================


@pytest.mark.parametrize(
    'text,expected',
    [
        # Empty and whitespace
        ('', 0),
        (' ', 1),
        ('   ', 3),
        ('\n', 1),
        ('\r\n', 2),
        # ASCII (1 UTF-16 unit each)
        ('a', 1),
        ('Hello', 5),
        ('Hello, World!', 13),
        ('123', 3),
        # Cyrillic (1 UTF-16 unit each)
        ('Привет', 6),
        ('Мир', 3),
        # Chinese/Japanese (1 UTF-16 unit each)
        ('你好', 2),
        ('世界', 2),
        ('こんにちは', 5),
        # Emoji (2 UTF-16 units each - surrogate pairs)
        ('🔥', 2),
        ('😀', 2),
        ('🌍', 2),
        ('👍', 2),
        # Multiple emoji
        ('🔥🔥', 4),
        ('😀😀😀', 6),
        # Mixed content
        ('Hello 🌍', 8),  # 6 + 2
        ('Test 😀 emoji', 13),  # 5 + 2 + 6
        ('Привет 👍', 9),  # 7 + 2
        # Special characters
        ('a\nb\nc', 5),  # newlines
        ('tab\there', 8),  # tab
        ('quote"test"', 11),  # quotes
        # Combined scenarios
        ('Hello 世界 🌍!', 12),  # 'Hello ' (6) + '世界' (2) + ' ' (1) + '🌍' (2) + '!' (1)
        ('🔥火🔥', 5),  # '🔥' (2) + '火' (1) + '🔥' (2)
    ],
)
def test_utf16_len_various_characters(text: str, expected: int) -> None:
    """Test utf16_len with various character types."""
    assert utf16_len(text) == expected, f'Failed for: {text!r}'


def test_utf16_len_consistency_with_encoding() -> None:
    """Test that utf16_len matches actual UTF-16 LE encoding length."""
    test_strings = [
        'Hello',
        '🔥🔥🔥',
        'Привет мир',
        '你好世界',
        'Mixed: Hello 🌍 世界',
    ]

    for text in test_strings:
        expected = len(text.encode('utf-16-le')) // 2
        actual = utf16_len(text)
        assert actual == expected, f'Mismatch for {text!r}: {actual} != {expected}'


def test_utf16_len_telegram_limits() -> None:
    """Test utf16_len with Telegram message length limits.

    Telegram API limits:
    - Message text: 4096 UTF-16 units
    - Caption: 1024 UTF-16 units
    """
    # Exactly at limit
    text_4096_ascii = 'x' * 4096
    assert utf16_len(text_4096_ascii) == 4096

    # Emoji at limit (2048 emoji = 4096 units)
    text_4096_emoji = '🔥' * 2048
    assert utf16_len(text_4096_emoji) == 4096

    # Over limit
    text_over = 'x' * 4097
    assert utf16_len(text_over) == 4097


def test_utf16_len_surrogate_pairs() -> None:
    """Test utf16_len with various surrogate pair characters."""
    # Different emoji types (all use surrogate pairs)
    surrogate_pairs = [
        '🔥',  # Fire (U+1F525)
        '😀',  # Grinning face (U+1F600)
        '🌍',  # Earth (U+1F30D)
        '👨‍👩‍👧‍👦',  # Family emoji (multiple surrogates + ZWJ)
        '🏴󠁧󠁢󠁥󠁮󠁧󠁿',  # Flag (multiple code points)
    ]

    for char in surrogate_pairs:
        length = utf16_len(char)
        # All emoji should be >= 2 UTF-16 units
        assert length >= 2, f'{char!r} should be >= 2 UTF-16 units, got {length}'


def test_utf16_len_edge_cases() -> None:
    """Test utf16_len edge cases."""
    # Null character
    assert utf16_len('\x00') == 1

    # Unicode escapes
    assert utf16_len('\u0041') == 1  # 'A'
    assert utf16_len('\u4e00') == 1  # Chinese character

    # Long strings
    long_text = 'a' * 10000
    assert utf16_len(long_text) == 10000

    # Mixed line endings
    mixed = 'line1\nline2\r\nline3\r'
    assert utf16_len(mixed) == len('line1\nline2\r\nline3\r')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
