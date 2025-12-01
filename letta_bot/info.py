"""
Info handlers for commands serving information
"""

from functools import lru_cache
import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from letta_bot.config import CONFIG
from letta_bot.response_handler import _escape_markdown_v2, convert_to_telegram_markdown

LOGGER = logging.getLogger(__name__)


@lru_cache(maxsize=32)
def load_info_command_content(note_name: str) -> str:
    """
    Load markdown note from specified directory and convert to Telegram MarkdownV2.

    Note files should be written in standard Markdown format. This function
    automatically converts them to Telegram-compatible MarkdownV2 using the same
    conversion pipeline used for agent responses.

    Results are cached to avoid re-converting the same notes on every request.

    Args:
        note_name: Name of the note file (without .md extension)

    Returns:
        Telegram MarkdownV2 formatted content, or error message if not found
    """
    notes_dir = CONFIG.info_dir

    if not notes_dir.exists():
        LOGGER.critical(
            f'Info handlers not initialized: directory does not exist: {notes_dir}'
        )
        raise RuntimeError('Bot info directory doesnt exist')

    note_path = notes_dir / f'{note_name}.md'

    if not note_path.exists():
        LOGGER.warning(f'Note file not found: {note_path}')
        return _escape_markdown_v2(f"ℹ️ Note '{note_name}' is not available.")

    try:
        # Load standard markdown content and convert to Telegram MarkdownV2
        markdown_content = note_path.read_text(encoding='utf-8').strip()
        return convert_to_telegram_markdown(markdown_content)
    except Exception as e:
        LOGGER.error(f'Error reading note {note_path}: {e}')
        return _escape_markdown_v2(f'❌ Error loading note: {str(e)}')


info_router = Router(name=__name__)


# TODO: should there be a function to create info command as whole?
@info_router.message(Command('privacy'))
async def privacy_handler(message: Message) -> None:
    """Display privacy policy and data handling information."""
    content = load_info_command_content('privacy')
    await message.answer(content)


@info_router.message(Command('help'))
async def help_handler(message: Message) -> None:
    """Display help documentation and available commands."""
    content = load_info_command_content('help')
    await message.answer(content)


@info_router.message(Command('about'))
async def about_handler(message: Message) -> None:
    """Display information about the bot."""
    content = load_info_command_content('about')
    await message.answer(content)


@info_router.message(Command('contact'))
async def contact_handler(message: Message) -> None:
    """Display contact and support information."""
    content = load_info_command_content('contact')
    await message.answer(content)


@info_router.message(Command('changelog'))
async def changelog_handler(message: Message) -> None:
    """Display project changelog and version history."""
    content = load_info_command_content('changelog')
    await message.answer(content)
