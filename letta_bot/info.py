"""
Info handlers for serving markdown notes (privacy, security, help, contact, about).
"""

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.utils.formatting import Text

from letta_bot.config import CONFIG

LOGGER = logging.getLogger(__name__)


def load_info_command_content(note_name: str) -> str:
    """
    Load markdown note from specified directory.

    Args:
        note_name: Name of the note file (without .md extension)

    Returns:
        Content of the markdown file, or error message if not found
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
        return Text(f"ℹ️ Note '{note_name}' is not available.").as_markdown()

    try:
        content = note_path.read_text(encoding='utf-8')
        return Text(content).as_markdown()
    except Exception as e:
        LOGGER.error(f'Error reading note {note_path}: {e}')
        return Text(f'❌ Error loading note: {e}').as_markdown()


def get_info_router() -> Router:
    """
    Initialize handlers for informational markdown notes.

    Args:
        dp: Aiogram Dispatcher instance
        bot: Aiogram Bot instance
    """
    info_router = Router(name=__name__)

    # TODO: should there be a function to create info command as whole?

    @info_router.message(Command('privacy'))
    async def privacy_handler(message: Message) -> None:
        """Display privacy policy and data handling information."""
        content = load_info_command_content('privacy')
        await message.answer(content)

    @info_router.message(Command('security'))
    async def security_handler(message: Message) -> None:
        """Display security practices and information."""
        content = load_info_command_content('security')
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

    LOGGER.info('Info handlers initialized')
    return info_router
