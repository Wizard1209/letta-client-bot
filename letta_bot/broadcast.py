"""Bot-level messaging: admin notifications and user broadcasts."""

from aiogram import Bot

from letta_bot.config import CONFIG


async def notify_admins(bot: Bot, **kwargs) -> None:  # type: ignore[no-untyped-def]  # noqa: ANN003
    """Send notification message to all configured admins.

    Accepts kwargs from aiogram formatting utilities (.as_kwargs()).

    Args:
        bot: Telegram Bot instance
        **kwargs: Message parameters (text, entities, etc.) from .as_kwargs()
    """
    if CONFIG.admin_ids is not None:
        for admin_id in CONFIG.admin_ids:
            await bot.send_message(admin_id, **kwargs)


# TODO: Add notify_users() for sending to specific users
# TODO: Add broadcast_all() for sending to all registered users
