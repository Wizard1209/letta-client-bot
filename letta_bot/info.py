"""
Info handlers for commands serving information
"""

from functools import lru_cache
import logging
import re

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from letta_bot.config import CONFIG
from letta_bot.response_handler import send_markdown_message

LOGGER = logging.getLogger(__name__)


@lru_cache(maxsize=32)
def load_info_command_content(note_name: str) -> str:
    """
    Load markdown note from specified directory.

    Note files should be written in standard Markdown format.

    Results are cached to avoid re-reading the same notes on every request.

    Args:
        note_name: Name of the note file (without .md extension)

    Returns:
        Standard Markdown content, or error message if not found
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
        return f"ℹ️ Note '{note_name}' is not available."

    try:
        # Load standard markdown content
        markdown_content = note_path.read_text(encoding='utf-8').strip()
        return markdown_content
    except Exception as e:
        LOGGER.error(f'Error reading note {note_path}: {e}')
        return f'❌ Error loading note: {str(e)}'


info_router = Router(name=__name__)


# TODO: should there be a function to create info command as whole?
@info_router.message(Command('privacy'))
async def privacy_handler(message: Message) -> None:
    """Display privacy policy and data handling information."""
    content = load_info_command_content('privacy')
    await send_markdown_message(message, content)


@info_router.message(Command('help'))
async def help_handler(message: Message) -> None:
    """Display help documentation and available commands."""
    content = load_info_command_content('help')
    await send_markdown_message(message, content)


@info_router.message(Command('about'))
async def about_handler(message: Message) -> None:
    """Display information about the bot."""
    content = load_info_command_content('about')
    await send_markdown_message(message, content)


@info_router.message(Command('contact'))
async def contact_handler(message: Message) -> None:
    """Display contact and support information."""
    content = load_info_command_content('contact')
    await send_markdown_message(message, content)


def _extract_latest_changelog(content: str) -> str:
    """Extract only the latest version section from changelog.

    Keeps header, [Latest additions], and most recent versioned section.
    Matches version headers like **[1.1.0] - 2025-12-09**

    Args:
        content: Standard Markdown changelog content

    Returns:
        Truncated changelog with only latest sections
    """
    # Match version headers: **[X.X.X]...**  (standard Markdown)
    version_pattern = re.compile(
        r'^\*\*\[\d+\.\d+\.\d+\].*\*\*$',
        re.MULTILINE,
    )

    matches = list(version_pattern.finditer(content))

    if len(matches) < 2:
        return content

    # Cut off at the second version header
    return content[: matches[1].start()].rstrip()


@info_router.message(Command('changelog'))
async def changelog_handler(message: Message) -> None:
    """Display project changelog and version history."""
    content = load_info_command_content('changelog')
    content = _extract_latest_changelog(content)
    await send_markdown_message(message, content)
