import asyncio
from collections.abc import Awaitable, Callable
import contextlib
from dataclasses import dataclass, field
import logging
import time
from typing import cast

from aiogram import BaseMiddleware, Dispatcher
from aiogram.dispatcher.flags import get_flag
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message
from aiogram.types.base import TelegramObject
from aiogram.utils.formatting import Text
from gel import AsyncIOExecutor
from letta_client import NotFoundError
from letta_client.types.agent_state import AgentState

from letta_bot.client import client, get_oldest_agent_by_user
from letta_bot.config import CONFIG
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


# =============================================================================
# Photo Buffering
# =============================================================================


@dataclass
class PendingPhotoBatch:
    """Buffered photo batch waiting for timeout before processing."""

    messages: list[Message] = field(default_factory=list)
    status_message: Message | None = None
    timer_handle: asyncio.TimerHandle | None = None


class PhotoBuffer:
    """Buffer photos by user_id, fire after timeout with no new photos.

    Every photo message is buffered for `process_timeout` seconds.
    After timeout, the collected batch is passed to the callback as list[Message].
    """

    def __init__(self, process_timeout: float = 1.0) -> None:
        self._pending: dict[int, PendingPhotoBatch] = {}
        self.process_timeout = process_timeout

    def add_photo(
        self,
        user_id: int,
        message: Message,
        callback: Callable[[list[Message]], Awaitable[None]],
    ) -> PendingPhotoBatch:
        """Add photo message to user's buffer.

        Returns:
            The PendingPhotoBatch (for status message updates)
        """
        # No lock needed: all operations are sync (no await), atomic in asyncio
        if user_id in self._pending:
            pending = self._pending[user_id]
            pending.messages.append(message)

            # Reset timer on each new photo
            if pending.timer_handle:
                pending.timer_handle.cancel()
        else:
            pending = PendingPhotoBatch(messages=[message])
            self._pending[user_id] = pending

        # Schedule processing
        loop = asyncio.get_running_loop()

        def create_callback_task(uid: int = user_id) -> None:
            asyncio.create_task(self._trigger_callback(uid, callback))

        pending.timer_handle = loop.call_later(
            self.process_timeout,
            create_callback_task,
        )

        return pending

    async def _trigger_callback(
        self,
        user_id: int,
        callback: Callable[[list[Message]], Awaitable[None]],
    ) -> None:
        """Trigger callback for photo batch processing."""
        pending = self._pending.pop(user_id, None)
        if pending:
            if pending.timer_handle:
                pending.timer_handle.cancel()
            try:
                await callback(pending.messages)
            except Exception as e:
                LOGGER.exception('Photo batch callback error: %s', e)


# =============================================================================
# Agent Resolution Helpers
# =============================================================================

AGENT_INCLUDE = ['agent.tags', 'agent.secrets']


async def _validate_selected_agent(
    agent_id: str,
    telegram_id: int,
) -> AgentState | None:
    """Validate agent exists and user has access via identity tag.

    Returns:
        AgentState if valid, None if not found or user doesn't have access
    """
    try:
        agent = await client.agents.retrieve(
            agent_id,
            include=AGENT_INCLUDE,  # type: ignore[arg-type]
        )
    except NotFoundError:
        return None

    identity_tag = f'identity-tg-{telegram_id}'
    if not agent.tags or identity_tag not in agent.tags:
        return None

    return agent


async def _set_secrets(agent: AgentState) -> None:
    """Inject required secrets if missing."""
    has_token = any(s.key == 'TELEGRAM_BOT_TOKEN' for s in (agent.secrets or []))
    if not has_token:
        LOGGER.info(f'Injecting TELEGRAM_BOT_TOKEN for agent {agent.id}')
        await client.agents.update(
            agent.id, secrets={'TELEGRAM_BOT_TOKEN': CONFIG.telegram_bot_token}
        )


class PhotoBufferMiddleware(BaseMiddleware):
    """Buffers all photo messages by user_id before processing.

    Every photo is buffered for 1s. After timeout, the collected batch
    (1 or more photos) is passed to the handler as `photos: list[Message]`.

    Rate limiting should be handled by a separate RateLimitMiddleware
    registered before this middleware in the chain.

    Args:
        buffer: PhotoBuffer instance for collecting photos

    Example:
        buffer = PhotoBuffer(process_timeout=1.0)
        dp.message.middleware(PhotoBufferMiddleware(buffer))
    """

    def __init__(self, buffer: PhotoBuffer) -> None:
        self._buffer = buffer

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, object]], Awaitable[object]],
        event: TelegramObject,
        data: dict[str, object],
    ) -> object | None:
        # Only intercept Message events with photos
        if not isinstance(event, Message) or not event.photo:
            return await handler(event, data)

        user = event.from_user
        if not user:
            return await handler(event, data)

        user_id = user.id

        # Capture handler and data for delayed callback
        captured_handler = handler
        # Shallow copy is safe: aiogram's data contains immutable refs
        captured_data = data.copy()

        async def process_batch(messages: list[Message]) -> None:
            """Process buffered photo batch."""
            if not messages:
                return

            first_message = messages[0]
            first_user = first_message.from_user

            # Find status message from the pending batch (already deleted from buffer)
            # We stored it on the batch object, but it's gone now.
            # Use the status_message we captured via closure.
            status_msg = batch_status_message

            # Update status to show processing
            if status_msg:
                with contextlib.suppress(TelegramAPIError):
                    await status_msg.edit_text(f'⏳ Processing {len(messages)} photo(s)...')

            # Inject photos list into handler data
            captured_data['photos'] = messages

            delete_status = True
            try:
                await captured_handler(first_message, captured_data)
            except Exception as e:
                LOGGER.exception(
                    'Photo batch handler error: %s, telegram_id=%s',
                    e,
                    first_user.id if first_user else 'unknown',
                )
                if status_msg:
                    with contextlib.suppress(TelegramAPIError):
                        await status_msg.edit_text('❌ Failed to process photos')
                delete_status = False

            # Clean up status message on success
            if delete_status and status_msg:
                with contextlib.suppress(TelegramAPIError):
                    await status_msg.delete()

        # Add to buffer
        pending = self._buffer.add_photo(user_id, event, process_batch)

        # Send status message for first photo only
        batch_status_message: Message | None = None
        if len(pending.messages) == 1:
            try:
                status = await event.answer('📷 Receiving photos...')
                pending.status_message = status
                batch_status_message = status
            except Exception as e:
                LOGGER.warning('Failed to send status message: %s', e)
        else:
            # Subsequent photos: use existing status message
            batch_status_message = pending.status_message

        # Block handler — will be called via callback after timeout
        return None


class RateLimitMiddleware(BaseMiddleware):
    """Universal rate limiter with configurable event filtering.

    Args:
        max_requests: Maximum requests allowed in window
        window_seconds: Time window in seconds
        key_func: Function to extract rate limit key (default: user_id)
        predicate: Function to check if event should be rate limited (default: always)
        message: Message template for rate limit response (use {wait} placeholder)

    Examples:
        # Rate limit all messages
        RateLimitMiddleware(max_requests=10, window_seconds=60)

        # Rate limit only documents
        RateLimitMiddleware(
            max_requests=3,
            window_seconds=60,
            predicate=lambda e: hasattr(e, 'document') and e.document,
            message='📄 Too many uploads. Wait {wait}s.'
        )

        # Rate limit by chat instead of user
        RateLimitMiddleware(
            max_requests=20,
            window_seconds=60,
            key_func=lambda e: e.chat.id
        )
    """

    def __init__(
        self,
        max_requests: int = 10,
        window_seconds: float = 60.0,
        key_func: Callable[[TelegramObject], int | str | None] | None = None,
        predicate: Callable[[TelegramObject], bool] | None = None,
        message: str = 'Too many requests. Please wait {wait}s.',
    ) -> None:
        self.max_requests = max_requests
        self.window = window_seconds
        self.key_func = key_func or self._default_key
        self.predicate = predicate or (lambda _: True)
        self.message = message
        self._requests: dict[int | str, list[float]] = {}

    @staticmethod
    def _default_key(event: TelegramObject) -> int | None:
        """Extract user_id from event."""
        from_user = getattr(event, 'from_user', None)
        if from_user:
            return int(from_user.id)
        return None

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, object]], Awaitable[object]],
        event: TelegramObject,
        data: dict[str, object],
    ) -> object | None:
        # Skip if predicate returns False
        if not self.predicate(event):
            return await handler(event, data)

        # Get rate limit key
        key = self.key_func(event)
        if key is None:
            return await handler(event, data)

        now = time.time()

        # Get/create timestamps list
        timestamps = self._requests.setdefault(key, [])

        # Remove expired timestamps
        timestamps[:] = [t for t in timestamps if now - t < self.window]

        # Check limit
        if len(timestamps) >= self.max_requests:
            wait_time = int(self.window - (now - timestamps[0]))
            if isinstance(event, Message):
                await event.reply(self.message.format(wait=wait_time))
            return None

        # Record request
        timestamps.append(now)

        return await handler(event, data)


class UserMiddleware(BaseMiddleware):
    """Registers/updates users in database."""

    def __init__(self) -> None:
        self._user_locks: dict[int, asyncio.Lock] = {}

    def _get_user_lock(self, telegram_id: int) -> asyncio.Lock:
        """Get or create lock for a specific user.

        No async lock needed: dict check + set has no await in between,
        so it's atomic in asyncio's single-threaded event loop.
        """
        if telegram_id not in self._user_locks:
            self._user_locks[telegram_id] = asyncio.Lock()
        return self._user_locks[telegram_id]

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

        # Per-user lock prevents concurrent upserts (album messages arrive together)
        user_lock = self._get_user_lock(from_user.id)
        async with user_lock:
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
    """Resolve user to a ready-to-use agent.

    Linear state machine:
    1. RESOLVE    → get agent (existing or default)
    2. SET_SECRETS → inject token if missing
    3. PERSIST    → save selection if changed
    4. NOTIFY     → inform user if changed
    5. INJECT     → data['agent_id']
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
            raise RuntimeError('require_agent flag requires require_identity flag')

        # Required for business logic - require Message or CallbackQuery
        if not isinstance(event, (Message, CallbackQuery)):
            raise TypeError(
                f'require_agent flag on unsupported event type: {type(event).__name__}'
            )

        # Required for business logic - require from_user, type already verified
        if not event.from_user:
            raise ValueError('require_agent: event has no from_user')

        # Get gel_client from data (injected via Dispatcher workflow_data)
        gel_client = cast(AsyncIOExecutor, data['gel_client'])
        # Get identity from data (injected by IdentityMiddleware)
        identity = cast(GetIdentityResult, data['identity'])
        telegram_id = event.from_user.id

        # 1. RESOLVE: existing selection → default
        agent: AgentState | None = None
        selection_changed = False

        if identity.selected_agent:
            agent = await _validate_selected_agent(identity.selected_agent, telegram_id)

        if agent is None:
            try:
                agent_id = await get_oldest_agent_by_user(telegram_id)
            except IndexError:
                await event.answer(
                    **Text('❌ No assistants yet — use /new to request one').as_kwargs()
                )
                return None
            agent = await client.agents.retrieve(
                agent_id,
                include=AGENT_INCLUDE,  # type: ignore[arg-type]
            )
            selection_changed = True

        # 2. SET_SECRETS
        await _set_secrets(agent)

        # 3. PERSIST
        if selection_changed:
            await set_selected_agent_query(
                gel_client, telegram_id=telegram_id, agent_id=agent.id
            )

        # 4. NOTIFY
        if selection_changed:
            was_reselect = identity.selected_agent is not None
            msg = (
                f'🔄 Switched to {agent.name} (previous unavailable)'
                if was_reselect
                else f'🤖 Auto-selected assistant {agent.name}'
            )
            await event.answer(**Text(msg).as_kwargs())

        # 5. INJECT
        data['agent_id'] = agent.id
        return await handler(event, data)


def setup_middlewares(dp: Dispatcher) -> None:
    """Register all middlewares.

    Requires gel_client in dispatcher's workflow_data:
        dp = Dispatcher(gel_client=gel_client)
    """
    # Outer middleware - user tracking
    dp.message.outer_middleware.register(UserMiddleware())
    dp.callback_query.outer_middleware.register(UserMiddleware())

    # Document rate limiting (1 per 10s per user)
    dp.message.middleware(
        RateLimitMiddleware(
            max_requests=1,
            window_seconds=10.0,
            predicate=lambda e: isinstance(e, Message) and bool(e.document),
            message="📄 Your document accepted, we can't process more documents"
            ' for {wait}s.',
        )
    )

    # Photo rate limiting (10 photos per 10s per user)
    dp.message.middleware(
        RateLimitMiddleware(
            max_requests=10,
            window_seconds=10.0,
            predicate=lambda e: isinstance(e, Message) and bool(e.photo),
            message='📷 Your previous photos are being processed. Resend this in {wait}s.',
        )
    )

    # Photo buffering (all photos buffered 1s by user_id)
    photo_buffer = PhotoBuffer(process_timeout=1.0)
    dp.message.middleware(PhotoBufferMiddleware(buffer=photo_buffer))

    # Inner middleware - identity and agent checks
    dp.message.middleware(IdentityMiddleware())
    dp.callback_query.middleware(IdentityMiddleware())

    dp.message.middleware(AgentMiddleware())
    dp.callback_query.middleware(AgentMiddleware())
