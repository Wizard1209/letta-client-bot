"""Utility functions for Markdown to Telegram conversion."""


def utf16_len(text: str) -> int:
    """Calculate length in UTF-16 code units (for Telegram API).

    Telegram API uses UTF-16 for calculating offsets and lengths in MessageEntity.
    This function returns the proper length needed for entity calculations.

    Args:
        text: Input text string

    Returns:
        Length in UTF-16 code units

    Examples:
        >>> utf16_len("Hello")
        5
        >>> utf16_len("🌍")
        2
        >>> utf16_len("Привет")
        6
    """
    return len(text.encode('utf-16-le')) // 2
