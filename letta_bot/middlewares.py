from collections.abc import Awaitable, Callable
import logging
from typing import cast

from aiogram import BaseMiddleware, Dispatcher
from aiogram.dispatcher.flags import get_flag
from aiogram.types import CallbackQuery, Message
from aiogram.types.base import TelegramObject
from aiogram.utils.formatting import Text
from gel import AsyncIOExecutor
from letta_client import NotFoundError

from letta_bot.client import client, get_agent_identity_ids, get_default_agent
from letta_bot.queries.get_allowed_identity_async_edgeql import (
    get_allowed_identity as get_allowed_identity_query,
)
from letta_bot.queries.get_identity_async_edgeql import (
    GetIdentityResult,
    get_identity as get_identity_query,
)
from letta_bot.queries.set_selected_agent_async_edgeql import (
    set_selected_agent as set_selected_agent_query,
)
from letta_bot.queries.upsert_user_async_edgeql import upsert_user
from letta_bot.utils import async_cache

LOGGER = logging.getLogger(__name__)

upsert_user_cached = async_cache(ttl=43200)(upsert_user)


class UserMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, object]], Awaitable[object]],
        event: TelegramObject,
        data: dict[str, object],
    ) -> object:
        # Get gel_client from data (injected via Dispatcher workflow_data)
        gel_client = cast(AsyncIOExecutor, data['gel_client'])

        # Skip user tracking for events without from_user (channel posts, service messages).
        # User tracking is optional analytics - handlers work without it.
        from_user = getattr(event, 'from_user', None)
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

        # Required for business logic - require Message or CallbackQuery
        if not isinstance(event, (Message, CallbackQuery)):
            raise TypeError(
                f'require_identity flag on unsupported event type: {type(event).__name__}'
            )

        # Required for business logic - require from_user, type already verified
        if not event.from_user:
            raise ValueError('require_identity: event has no from_user')

        # Get gel_client from data (injected via Dispatcher workflow_data)
        gel_client = cast(AsyncIOExecutor, data['gel_client'])
        telegram_id = event.from_user.id

        # Authorization - check if user has allowed identity
        if not await get_allowed_identity_query(gel_client, telegram_id=telegram_id):
            await event.answer(
                **Text('❌ No access — use /new or /access to request').as_kwargs()
            )
            return None

        # Business logic - identity must exist if authorized
        identity_list = await get_identity_query(gel_client, telegram_id=telegram_id)
        if not identity_list:
            raise RuntimeError(f'Identity not found for authorized user {telegram_id}')

        # Inject identity into handler data
        data['identity'] = cast(GetIdentityResult, identity_list[0])

        return await handler(event, data)


class AgentMiddleware(BaseMiddleware):
    """Middleware that ensures user has a valid selected agent.

    Prerequisites: IdentityMiddleware must run first (provides identity in data).

    If check passes, injects agent_id into handler data.
    If check fails, sends error message and blocks handler execution.

    Behavior:
    1. If no selected_agent: auto-selects the oldest agent
    2. If selected_agent exists: validates it still belongs to identity
    3. If validation fails: tries to auto-select another agent
    4. If no agents available: sends error and blocks handler
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, object]], Awaitable[object]],
        event: TelegramObject,
        data: dict[str, object],
    ) -> object | None:
        # Check if handler requires agent check
        if not get_flag(data, 'require_agent'):
            return await handler(event, data)

        if not get_flag(data, 'require_identity'):
            LOGGER.critical('require_agent middleware without identity')
            raise RuntimeError('require_agent middleware without identity')

        # Required for business logic - require Message or CallbackQuery
        if not isinstance(event, (Message, CallbackQuery)):
            raise TypeError(
                f'require_identity flag on unsupported event type: {type(event).__name__}'
            )

        # Required for business logic - require from_user, type already verified
        if not event.from_user:
            raise ValueError('require_agent: event has no from_user')

        # Get gel_client from data (injected via Dispatcher workflow_data)
        gel_client = cast(AsyncIOExecutor, data['gel_client'])
        # Get identity from data (injected by IdentityMiddleware)
        identity = cast(GetIdentityResult, data['identity'])

        # TODO: streamline all the selection logic, i believe it could be much cleaner
        agent_id: str | None = identity.selected_agent
        reselect = False

        if agent_id:
            # Validate agent still belongs to user
            try:
                identity_ids = await get_agent_identity_ids(agent_id)
                if identity.identity_id not in identity_ids:
                    agent_id = None
                    reselect = True
            except NotFoundError:
                # Agent was deleted
                agent_id = None
                reselect = True

        if agent_id is None:
            try:
                agent_id = await get_default_agent(identity.identity_id)
                agent = await client.agents.retrieve(agent_id)
                # Save newly selected agent
                await set_selected_agent_query(
                    gel_client, identity_id=identity.identity_id, agent_id=agent_id
                )
                if reselect:
                    msg = f'🔄 Switched to {agent.name} (previous unavailable)'
                else:
                    msg = f'🤖 Auto-selected assistant {agent.name}'
                await event.answer(**Text(msg).as_kwargs())
            except IndexError:
                # Authorization - no agents available
                await event.answer(
                    **Text('❌ No assistants yet — use /new to request one').as_kwargs()
                )
                return None

        # Inject agent_id into handler data
        data['agent_id'] = agent_id
        return await handler(event, data)


def setup_middlewares(dp: Dispatcher) -> None:
    """Register all middlewares.

    Requires gel_client in dispatcher's workflow_data:
        dp = Dispatcher(gel_client=gel_client)
    """
    dp.message.outer_middleware.register(UserMiddleware())
    dp.callback_query.outer_middleware.register(UserMiddleware())

    dp.message.middleware(IdentityMiddleware())
    dp.callback_query.middleware(IdentityMiddleware())

    dp.message.middleware(AgentMiddleware())
    dp.callback_query.middleware(AgentMiddleware())
