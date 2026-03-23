"""Bot-level messaging: admin notifications and user broadcasts."""

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

from letta_bot.config import CONFIG

LOGGER = logging.getLogger(__name__)


async def notify_admins(bot: Bot, **kwargs) -> None:  # type: ignore[no-untyped-def]  # noqa: ANN003
    """Send notification message to all configured admins.

    Accepts kwargs from aiogram formatting utilities (.as_kwargs()).

    Args:
        bot: Telegram Bot instance
        **kwargs: Message parameters (text, entities, etc.) from .as_kwargs()
    """
    if CONFIG.admin_ids is not None:
        for admin_id in CONFIG.admin_ids:
            try:
                await bot.send_message(admin_id, **kwargs)
            except TelegramBadRequest:
                LOGGER.warning(
                    'Admin %d has not started the bot yet, skipping notification',
                    admin_id,
                )


# TODO: Add notify_users() for sending to specific users
# TODO: Add broadcast_all() for sending to all registered users
