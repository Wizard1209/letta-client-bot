"""Bot-level messaging: admin notifications and user broadcasts."""

from aiogram import Bot

from letta_bot.config import CONFIG


async def notify_admins(bot: Bot, message: str) -> None:
    """Send notification message to all configured admins.

    Args:
        bot: Telegram Bot instance
        message: Message text to send (supports MarkdownV2)
    """
    if CONFIG.admin_ids is not None:
        for admin_id in CONFIG.admin_ids:
            await bot.send_message(admin_id, message)


# TODO: Add notify_users() for sending to specific users
# TODO: Add broadcast_all() for sending to all registered users
