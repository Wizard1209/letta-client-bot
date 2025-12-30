"""Markdown to Telegram message entities converter.

This module provides functionality to convert Markdown text into Telegram-compatible
plain text with message entities (formatting).

Example:
    >>> from md_tg import markdown_to_telegram
    >>> text, entities = markdown_to_telegram("**Bold** and *italic* text")
    >>> print(text)
    Bold and italic text
    >>> # Returns list of MessageEntity dicts (TypedDict)
    >>> print(entities[0]['type'])
    bold
"""

from md_tg.config import DEFAULT_CONFIG, MarkdownConfig
from md_tg.converter import markdown_to_telegram

__version__ = '0.1.0'

__all__ = [
    'markdown_to_telegram',
    'MarkdownConfig',
    'DEFAULT_CONFIG',
]
