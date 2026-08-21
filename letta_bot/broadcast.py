"""Bot-level messaging: admin notifications and user broadcasts."""

import logging
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from letta_bot.config import CONFIG

LOGGER = logging.getLogger(__name__)


async def notify_admins(bot: Bot, **kwargs: Any) -> None:  # noqa: ANN401
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
            except (TelegramBadRequest, TelegramForbiddenError):
                LOGGER.warning(
                    'Admin %d unreachable (not started or blocked), skipping',
                    admin_id,
                )


# TODO: Add notify_users() for sending to specific users
# TODO: Add broadcast_all() for sending to all registered users
