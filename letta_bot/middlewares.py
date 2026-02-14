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
# Media Group Buffering
# =============================================================================


@dataclass
class PendingMediaGroup:
    """Buffered media group waiting for timeout before processing."""

    media_group_id: str
    messages: list[Message] = field(default_factory=list)
    caption: str | None = None
    status_message: Message | None = None
    timer_handle: asyncio.TimerHandle | None = None
    created_at: float = field(default_factory=time.time)


class MediaGroupBuffer:
    """Buffer for collecting media group items before processing.

    Telegram sends album items as separate messages with the same media_group_id.
    This buffer collects them and triggers processing after a timeout.
    """

    def __init__(self, process_timeout: float = 1.0) -> None:
        self._pending: dict[str, PendingMediaGroup] = {}
        self.process_timeout = process_timeout
        self._stale_threshold = 60.0  # Clean up groups older than 60s

    def add_item(
        self,
        media_group_id: str,
        message: Message,
        callback: Callable[[PendingMediaGroup], Awaitable[None]],
    ) -> PendingMediaGroup:
        """Add message to media group buffer.

        Args:
            media_group_id: Telegram media group ID
            message: Telegram message to buffer
            callback: Async function to call when timeout expires

        Returns:
            The PendingMediaGroup (for status message updates)
        """
        # No lock needed: all operations are sync (no await), atomic in asyncio
        if media_group_id in self._pending:
            pending = self._pending[media_group_id]
            pending.messages.append(message)

            # Update caption if this message has one and we don't have one yet
            if pending.caption is None and message.caption:
                pending.caption = message.caption

            # Reset timer
            if pending.timer_handle:
                pending.timer_handle.cancel()
        else:
            pending = PendingMediaGroup(
                media_group_id=media_group_id,
                messages=[message],
                caption=message.caption,
            )
            self._pending[media_group_id] = pending

        # Schedule processing
        loop = asyncio.get_running_loop()

        def create_callback_task(gid: str = media_group_id) -> None:
            asyncio.create_task(self._trigger_callback(gid, callback))

        pending.timer_handle = loop.call_later(
            self.process_timeout,
            create_callback_task,
        )

        return pending

    async def _trigger_callback(
        self,
        media_group_id: str,
        callback: Callable[[PendingMediaGroup], Awaitable[None]],
    ) -> None:
        """Trigger callback for media group processing."""
        pending = self.get_and_remove(media_group_id)
        if pending:
            try:
                await callback(pending)
            except Exception as e:
                LOGGER.exception('Media group callback error: %s', e)

    def get_and_remove(self, media_group_id: str) -> PendingMediaGroup | None:
        """Retrieve and remove a pending media group.

        Args:
            media_group_id: Telegram media group ID

        Returns:
            PendingMediaGroup if found, None otherwise
        """
        pending = self._pending.pop(media_group_id, None)
        if pending and pending.timer_handle:
            pending.timer_handle.cancel()
        return pending


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



class PhotoRateLimiter:
    """Rate limiter for photo uploads with separate limits for albums and single photos."""

    def __init__(
        self,
        single_max: int = 5,
        single_window: float = 60.0,
        album_max: int = 1,
        album_window: float = 60.0,
    ) -> None:
        self.single_max = single_max
        self.single_window = single_window
        self.album_max = album_max
        self.album_window = album_window
        self._single_requests: dict[int, list[float]] = {}
        self._album_requests: dict[int, list[float]] = {}
        self._last_cleanup = time.time()
        self._cleanup_interval = 300.0  # Clean up every 5 minutes

    def check_and_record_single(self, user_id: int) -> int | None:
        """Check and record single photo. Returns wait time or None."""
        self._maybe_cleanup()
        wait = self._check(
            user_id, self._single_requests, self.single_max, self.single_window
        )
        if wait is None:
            self._record(user_id, self._single_requests)
        return wait

    def check_and_record_album(self, user_id: int) -> int | None:
        """Check and record album. Returns wait time or None."""
        self._maybe_cleanup()
        wait = self._check(
            user_id, self._album_requests, self.album_max, self.album_window
        )
        if wait is None:
            self._record(user_id, self._album_requests)
        return wait

    def _check(
        self,
        user_id: int,
        storage: dict[int, list[float]],
        max_requests: int,
        window: float,
    ) -> int | None:
        """Check rate limit. Returns wait time in seconds or None if allowed."""
        now = time.time()
        timestamps = storage.get(user_id, [])

        # Remove expired timestamps
        timestamps = [t for t in timestamps if now - t < window]

        if timestamps:
            storage[user_id] = timestamps
        elif user_id in storage:
            # Remove empty entries to prevent memory growth
            del storage[user_id]

        if len(timestamps) >= max_requests:
            return int(window - (now - timestamps[0]))
        return None

    def _record(self, user_id: int, storage: dict[int, list[float]]) -> None:
        """Record a request timestamp."""
        now = time.time()
        if user_id not in storage:
            storage[user_id] = []
        storage[user_id].append(now)

    def _maybe_cleanup(self) -> None:
        """Periodically clean up stale user entries."""
        now = time.time()
        if now - self._last_cleanup < self._cleanup_interval:
            return

        self._last_cleanup = now
        max_window = max(self.single_window, self.album_window)

        for storage in (self._single_requests, self._album_requests):
            # Collect stale user IDs first, then remove (safe iteration)
            stale_users = [
                uid
                for uid, timestamps in storage.items()
                if not timestamps or now - timestamps[-1] > max_window
            ]
            for uid in stale_users:
                del storage[uid]


class MediaGroupBufferMiddleware(BaseMiddleware):
    """Buffers photo albums and processes them as a single request.

    For photo albums:
    - Collects all photos with same media_group_id
    - After timeout, injects aggregated data and calls handler with first message
    - Handler receives `media_group: PendingMediaGroup` with all photos
    - Rate limited: 1 album per minute per user

    For single photos:
    - Passes through to handler (no buffering)
    - Rate limited: 5 photos per minute per user

    For document/mixed albums:
    - Rejects with error message (sequential processing too slow)

    Args:
        buffer: MediaGroupBuffer instance for collecting items
        rate_limiter: PhotoRateLimiter for rate limiting (optional)
        reject_message: Message for non-photo albums

    Example:
        buffer = MediaGroupBuffer(process_timeout=1.0)
        dp.message.middleware(MediaGroupBufferMiddleware(buffer))
    """

    def __init__(
        self,
        buffer: MediaGroupBuffer,
        rate_limiter: PhotoRateLimiter | None = None,
        reject_message: str = '📄 Please send files one at a time.',
    ) -> None:
        self._buffer = buffer
        self._rate_limiter = rate_limiter
        self._reject_message = reject_message
        self._responded_groups: set[str] = set()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, object]], Awaitable[object]],
        event: TelegramObject,
        data: dict[str, object],
    ) -> object | None:
        # Only handle Message events
        if not isinstance(event, Message):
            return await handler(event, data)

        # Check for media group (album) FIRST — before content type check
        media_group_id = event.media_group_id
        if not media_group_id:
            # Single message — only handle photos with rate limiting
            if not event.photo:
                return await handler(event, data)

            user_id = event.from_user.id if event.from_user else None
            if user_id and self._rate_limiter:
                wait_time = self._rate_limiter.check_and_record_single(user_id)
                if wait_time is not None:
                    await event.answer(f'📷 Too many photos. Wait {wait_time}s.')
                    return None

            return await handler(event, data)

        # Album handling — check content type
        has_photo = bool(event.photo)
        has_document = bool(event.document)

        # Reject document albums (including mixed photo+document)
        if has_document or not has_photo:
            # No lock needed: no await between check/clear/add — atomic in asyncio
            if media_group_id in self._responded_groups:
                return None

            if len(self._responded_groups) > 100:
                self._responded_groups.clear()

            self._responded_groups.add(media_group_id)
            await event.answer(self._reject_message)
            return None

        # Photo album - buffer and process together
        # Capture handler and data for delayed callback
        captured_handler = handler
        # Shallow copy is safe: aiogram's data contains immutable refs (gel_client, bot)
        # and primitives. We only mutate our own 'media_group' key.
        captured_data = data.copy()
        rate_limiter = self._rate_limiter

        async def process_group(pending: PendingMediaGroup) -> None:
            """Process buffered photo album."""
            if not pending.messages:
                return

            # Use first message as the trigger
            first_message = pending.messages[0]
            first_user = first_message.from_user
            delete_status = True  # Whether to delete status message at the end

            async def notify_user(text: str) -> None:
                """Send feedback via status message or fallback to reply."""
                if pending.status_message:
                    with contextlib.suppress(TelegramAPIError):
                        await pending.status_message.edit_text(text)
                        return
                # Fallback: reply to first message
                with contextlib.suppress(TelegramAPIError):
                    await first_message.answer(text)

            # Check album rate limit (atomic check-and-record)
            if first_user and rate_limiter:
                wait_time = rate_limiter.check_and_record_album(first_user.id)
                if wait_time is not None:
                    await notify_user(f'📷 Too many albums. Wait {wait_time}s.')
                    return  # Don't delete - user needs to see rate limit message

            # Update status message to show processing
            if pending.status_message:
                with contextlib.suppress(TelegramAPIError):
                    await pending.status_message.edit_text(
                        f'⏳ Processing {len(pending.messages)} photo(s)...'
                    )

            # Inject media_group into handler data
            captured_data['media_group'] = pending

            try:
                await captured_handler(first_message, captured_data)
            except Exception as e:
                LOGGER.exception(
                    'Album handler error: %s, telegram_id=%s',
                    e,
                    first_user.id if first_user else 'unknown',
                )
                await notify_user('❌ Failed to process photos')
                delete_status = False  # Keep error message visible

            # Clean up status message (only on success)
            if delete_status and pending.status_message:
                with contextlib.suppress(TelegramAPIError):
                    await pending.status_message.delete()

        # Add to buffer
        pending = self._buffer.add_item(media_group_id, event, process_group)

        # Send status message for first item only
        if len(pending.messages) == 1:
            try:
                pending.status_message = await event.answer('📷 Receiving photos...')
            except Exception as e:
                LOGGER.warning('Failed to send status message: %s', e)

        # Block handler - will be called via callback
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
            if hasattr(event, 'answer'):
                await event.answer(self.message.format(wait=wait_time))
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

    # Media group handling:
    # - Photo albums: buffer and process together (1 album per minute)
    # - Single photos: pass through with rate limit (5 per minute)
    # - Document albums: reject (sequential processing too slow)
    media_group_buffer = MediaGroupBuffer(process_timeout=1.0)
    photo_rate_limiter = PhotoRateLimiter(
        single_max=5,
        single_window=10.0,
        album_max=1,
        album_window=10.0,
    )
    dp.message.middleware(
        MediaGroupBufferMiddleware(
            buffer=media_group_buffer,
            rate_limiter=photo_rate_limiter,
            reject_message='📄 Please send files one at a time.',
        )
    )

    # Inner middleware - identity and agent checks
    dp.message.middleware(IdentityMiddleware())
    dp.callback_query.middleware(IdentityMiddleware())

    dp.message.middleware(AgentMiddleware())
    dp.callback_query.middleware(AgentMiddleware())
