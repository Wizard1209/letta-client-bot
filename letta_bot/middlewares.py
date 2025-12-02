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
from letta_bot.queries.upsert_user_async_edgeql import upsert_user
from letta_bot.utils import async_cache

LOGGER = logging.getLogger(__name__)

upsert_user_cached = async_cache(ttl=43200)(upsert_user)


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


class UserMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, object]], Awaitable[object]],
        event: TelegramObject,
        data: dict[str, object],
    ) -> object | None:
        gel_client = data.get('gel_client')
        if not gel_client:
            LOGGER.error('gel_client not found in middleware data')
            return None

        # Get user from event
        from_user = event.from_user

        if not from_user:
            return await handler(event, data)

        user_model = {
            'telegram_id': from_user.id,
            'is_bot': from_user.is_bot,
            'first_name': from_user.first_name,
            'last_name': from_user.last_name,
            'username': from_user.username,
            'language_code': from_user.language_code,
        }

        user = await upsert_user_cached(gel_client, **user_model)
        data['user'] = user

        # LOGGER.info(f'User upserted: {user.id}') #

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
    db_middleware = DBMiddleware(gel_client)

    dp.message.outer_middleware.register(db_middleware)
    dp.callback_query.outer_middleware.register(db_middleware)

    dp.message.outer_middleware.register(UserMiddleware())
    dp.callback_query.outer_middleware.register(UserMiddleware())

    dp.message.middleware(IdentityMiddleware())
    dp.callback_query.middleware(IdentityMiddleware())
