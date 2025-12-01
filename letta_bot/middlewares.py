from collections.abc import Awaitable, Callable
import logging

from aiogram import BaseMiddleware, Dispatcher
from aiogram.dispatcher.flags import get_flag
from aiogram.types import CallbackQuery, Message
from aiogram.types.base import TelegramObject
from aiogram.utils.formatting import Text
from gel import AsyncIOExecutor

from letta_bot.queries.get_allowed_identity_async_edgeql import (
    get_allowed_identity as get_allowed_identity_query,
)
from letta_bot.queries.get_identity_async_edgeql import (
    get_identity as get_identity_query,
)

LOGGER = logging.getLogger(__name__)


class DBMiddleware(BaseMiddleware):
    def __init__(self, client: AsyncIOExecutor) -> None:
        super().__init__()
        self.client = client

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, object]], Awaitable[object]],
        event: TelegramObject,
        data: dict[str, object],
    ) -> object:
        data['gel_client'] = self.client
        return await handler(event, data)


class IdentityMiddleware(BaseMiddleware):
    """Middleware that checks if user has allowed identity access.

    If check passes, injects identity into handler data.
    If check fails, sends error message and blocks handler execution.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, object]], Awaitable[object]],
        event: TelegramObject,
        data: dict[str, object],
    ) -> object | None:
        # Check if handler requires identity check
        if not get_flag(data, 'require_identity'):
            return await handler(event, data)

        # Only process Message and CallbackQuery events
        if not isinstance(event, (Message, CallbackQuery)):
            return await handler(event, data)

        # Get user from event
        from_user = event.from_user
        if not from_user:
            return None

        # Get gel_client from data (injected by DBMiddleware)
        gel_client = data.get('gel_client')
        if not gel_client:
            LOGGER.error('gel_client not found in middleware data')
            return None

        # Check if user has allowed identity
        if not await get_allowed_identity_query(gel_client, telegram_id=from_user.id):
            await event.answer(
                Text('You need to request bot access first using /botaccess').as_markdown()
            )
            return None

        # Fetch identity
        identity_list = await get_identity_query(gel_client, telegram_id=from_user.id)
        if not identity_list:
            # This shouldn't happen if get_allowed_identity returned True
            LOGGER.error(
                f'Identity not found for user {from_user.id} despite having allowed access'
            )
            await event.answer(
                Text('Error: Identity not found. Please contact admin.').as_markdown()
            )
            return None

        # Inject identity into handler data
        data['identity'] = identity_list[0]
        return await handler(event, data)


def setup_middlewares(dp: Dispatcher, gel_client: AsyncIOExecutor) -> None:
    dp.message.outer_middleware.register(DBMiddleware(gel_client))
    dp.callback_query.outer_middleware.register(DBMiddleware(gel_client))
    dp.message.middleware(IdentityMiddleware())
    dp.callback_query.middleware(IdentityMiddleware())
