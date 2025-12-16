"""Global error handler for unrecoverable exceptions.

Ensures users always get feedback when something goes wrong,
and errors are properly logged for debugging.
"""

import contextlib
import html
import logging
import traceback

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, ErrorEvent, Message

from letta_bot.config import CONFIG

LOGGER = logging.getLogger(__name__)


async def global_error_handler(event: ErrorEvent, bot: Bot) -> bool:
    """Handle all unhandled exceptions.

    Logs error with full traceback and tries to notify the user.
    """
    error = event.exception
    update = event.update
    error_class = type(error).__name__

    # Log full traceback
    LOGGER.exception('Unhandled %s: %s', error_class, error, exc_info=error)

    # Try to notify user
    trigger_event = None
    if update:
        trigger_event = update.message or update.callback_query or update.edited_message

    if trigger_event:
        try:
            if isinstance(trigger_event, Message):
                msg = f'❌ An {error_class} occurred. Please try again later.'
                await trigger_event.answer(msg)
            elif isinstance(trigger_event, CallbackQuery):
                await trigger_event.answer(f'❌ {error_class} occurred', show_alert=True)
        except TelegramAPIError as e:
            LOGGER.warning('Failed to notify user about error: %s', e)

    # Notify admins (optional, controlled by NOTIFY_ADMINS_ON_ERROR env var)
    if CONFIG.notify_admins_on_error and CONFIG.admin_ids:
        tb = ''.join(traceback.format_exception(type(error), error, error.__traceback__))
        if len(tb) > 3000:
            tb = tb[:1500] + '\n...\n' + tb[-1000:]

        user_info = 'Unknown'
        from_user = getattr(trigger_event, 'from_user', None)
        if from_user:
            user_info = f'{from_user.id}'

        msg = (
            f'🚨 <b>Bot Error</b>\n\n'
            f'<b>User:</b> {html.escape(user_info)}\n'
            f'<b>Type:</b> {html.escape(error_class)}\n'
            f'<b>Error:</b> {html.escape(str(error)[:300])}\n\n'
            f'<pre>{html.escape(tb)}</pre>'
        )

        for admin_id in CONFIG.admin_ids:
            with contextlib.suppress(TelegramAPIError):
                await bot.send_message(admin_id, msg, parse_mode='HTML')

    return True


def setup_error_handler(dp: Dispatcher) -> None:
    """Register global error handler."""
    dp.errors.register(global_error_handler)
