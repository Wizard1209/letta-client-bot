"""
Info handlers for serving markdown notes (privacy, security, help, contact, about).
"""

import argparse
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

from letta_bot.main import CONFIG

LOGGER = logging.getLogger(__name__)


def load_note(note_name: str, info_directory: str) -> str:
    """
    Load markdown note from letta_bot/notes/{info_directory}/.

    Args:
        note_name: Name of the note file (without .md extension)
        info_directory: Subdirectory name under letta_bot/notes/

    Returns:
        Content of the markdown file, or error message if not found
    """
    # Get the letta_bot directory (parent of handlers)
    letta_bot_dir = Path(__file__).parent.parent
    note_path = letta_bot_dir / 'notes' / info_directory / f'{note_name}.md'

    if not note_path.exists():
        LOGGER.warning(f'Note file not found: {note_path}')
        return f"ℹ️ Note '{note_name}' is not available."

    try:
        return note_path.read_text(encoding='utf-8')
    except Exception as e:
        LOGGER.error(f'Error reading note {note_path}: {e}')
        return f'❌ Error loading note: {e}'


def init_info_handlers(dp: Dispatcher, bot: Bot, args: argparse.Namespace) -> None:
    """
    Initialize handlers for informational markdown notes.

    Args:
        dp: Aiogram Dispatcher instance
        bot: Aiogram Bot instance
        args: Command line arguments
    """
    # Determine info directory from args or config
    info_dir = args.info_dir or CONFIG.info_dir

    if not info_dir:
        LOGGER.warning(
            'Info handlers not initialized: no info directory specified '
            '(set INFO_DIR env var or use --info-dir argument)'
        )
        return

    @dp.message(Command('privacy'))
    async def privacy_handler(message: Message) -> None:
        """Display privacy policy and data handling information."""
        content = load_note('privacy', info_dir)
        await message.answer(content)

    @dp.message(Command('security'))
    async def security_handler(message: Message) -> None:
        """Display security practices and information."""
        content = load_note('security', info_dir)
        await message.answer(content)

    @dp.message(Command('help'))
    async def help_handler(message: Message) -> None:
        """Display help documentation and available commands."""
        content = load_note('help', info_dir)
        await message.answer(content)

    @dp.message(Command('about'))
    async def about_handler(message: Message) -> None:
        """Display information about the bot."""
        content = load_note('about', info_dir)
        await message.answer(content)

    @dp.message(Command('contact'))
    async def contact_handler(message: Message) -> None:
        """Display contact and support information."""
        content = load_note('contact', info_dir)
        await message.answer(content)

    LOGGER.info(f'Info handlers initialized with info directory: {info_dir}')
