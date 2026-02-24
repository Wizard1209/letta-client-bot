"""Bot command menu registration.

Loads command definitions from deploy/commands.json and registers them
with Telegram via bot.set_my_commands() for appropriate scopes.
"""

import json
import logging
from pathlib import Path

from aiogram import Bot
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
)

from letta_bot.config import CONFIG

LOGGER = logging.getLogger(__name__)

COMMANDS_FILE = Path(__file__).resolve().parent.parent / 'deploy' / 'commands.json'


async def register_commands(bot: Bot) -> None:
    """Register bot commands for user and admin scopes."""
    if not COMMANDS_FILE.exists():
        LOGGER.warning(
            'Commands file not found: %s. Skipping command registration.',
            COMMANDS_FILE,
        )
        return

    data = json.loads(COMMANDS_FILE.read_text(encoding='utf-8'))

    user_commands = [
        BotCommand(command=cmd['command'], description=cmd['description'])
        for cmd in data['user_commands']
    ]
    admin_commands = [
        BotCommand(command=cmd['command'], description=cmd['description'])
        for cmd in data['admin_commands']
    ]

    await bot.set_my_commands(
        commands=user_commands,
        scope=BotCommandScopeAllPrivateChats(),
    )
    LOGGER.info('Registered %d user commands', len(user_commands))

    if not CONFIG.admin_ids:
        LOGGER.info('No admin IDs configured. Skipping admin command registration.')
        return

    combined_commands = user_commands + admin_commands
    for admin_id in CONFIG.admin_ids:
        await bot.set_my_commands(
            commands=combined_commands,
            scope=BotCommandScopeChat(chat_id=admin_id),
        )
    LOGGER.info(
        'Registered %d admin commands for %d admin(s)',
        len(combined_commands),
        len(CONFIG.admin_ids),
    )


async def set_revoked_commands(bot: Bot, chat_id: int) -> None:
    """Set commands for revoked user: all user commands plus /export."""
    data = json.loads(COMMANDS_FILE.read_text(encoding='utf-8'))
    commands = [
        BotCommand(command=cmd['command'], description=cmd['description'])
        for cmd in data['user_commands']
    ]
    commands.append(BotCommand(command='export', description='Export your assistants'))
    await bot.set_my_commands(
        commands=commands,
        scope=BotCommandScopeChat(chat_id=chat_id),
    )


async def clear_user_commands(bot: Bot, chat_id: int) -> None:
    """Clear per-user command override, falling back to default menu."""
    await bot.delete_my_commands(scope=BotCommandScopeChat(chat_id=chat_id))
