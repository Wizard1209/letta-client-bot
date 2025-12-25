"""Configuration and data models for Markdown to Telegram conversion."""

from dataclasses import dataclass
from typing import NotRequired, TypedDict


class MessageEntity(TypedDict):
    """Telegram MessageEntity structure.

    Follows Bot API spec: https://core.telegram.org/bots/api#messageentity

    This is a TypedDict for minimal overhead and direct compatibility
    with Telegram API (which expects plain dicts).

    Required fields:
        type: Type of entity (bold, italic, code, pre, text_link, etc.)
        offset: Offset in UTF-16 code units to the start of the entity
        length: Length in UTF-16 code units

    Optional fields:
        url: For text_link only, URL that will be opened after user taps on the text
        language: For pre only, the programming language of the entity text
    """

    type: str
    offset: int
    length: int
    url: NotRequired[str]
    language: NotRequired[str]


@dataclass(frozen=True)
class MarkdownConfig:
    """Configuration for Markdown rendering.

    This is an immutable dataclass with sensible defaults.
    All emoji can be customized or set to empty string to disable.

    Attributes:
        head_level_1: Emoji for H1 heading (default: 📌)
        head_level_2: Emoji for H2 heading (default: ✏️)
        head_level_3: Emoji for H3 heading (default: 📚)
        head_level_4: Emoji for H4 heading (default: 🔖)
        head_level_5: Emoji for H5 heading (default: 📎)
        head_level_6: Emoji for H6 heading (default: 📝)
        task_completed: Emoji for completed task (default: ✅)
        task_uncompleted: Emoji for uncompleted task (default: ☑️)
        link_reference: Emoji for reference links (default: 🔗, set to '' to disable)
        image_emoji: Emoji for images (default: 🖼️)
        max_chunk_length: Maximum length of a single chunk in UTF-16 code units
                         (default: 4096, Telegram's message length limit)
    """

    # Heading level emojis (Telegram entities don't support headings)
    head_level_1: str = '\N{PUSHPIN}'  # 📌
    head_level_2: str = '\N{PENCIL}'  # ✏️
    head_level_3: str = '\N{BOOKS}'  # 📚
    head_level_4: str = '\N{BOOKMARK}'  # 🔖
    head_level_5: str = '\N{PAPERCLIP}'  # 📎
    head_level_6: str = '\N{MEMO}'  # 📝

    # Task list emojis (checkboxes)
    task_completed: str = '\N{WHITE HEAVY CHECK MARK}'  # ✅
    task_uncompleted: str = '\N{BALLOT BOX WITH CHECK}'  # ☑️

    # Link reference emoji (for reference-style links like [text][ref])
    # Set to empty string '' to disable the indicator
    link_reference: str = '\N{LINK SYMBOL}'  # 🔗

    # Image emoji (for ![alt](src) images)
    image_emoji: str = '\N{FRAME WITH PICTURE}'  # 🖼️

    # Visual separators
    # Setext heading underline (for Heading\n=====)
    setext_underline_char: str = '─'  # Box drawing char (U+2500)
    setext_underline_length: int = 19  # Length of setext underline

    thematic_break_char: str = '—'
    thematic_break_length: int = 8

    # Maximum chunk length in UTF-16 code units (Telegram API limit)
    # Telegram allows max 4096 characters per message
    # Chunking is implemented in converter.py via AST-based block splitting
    max_chunk_length: int = 4096


# Default configuration instance
DEFAULT_CONFIG = MarkdownConfig()
