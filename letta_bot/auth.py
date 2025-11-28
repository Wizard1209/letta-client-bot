from collections.abc import Callable
from functools import wraps
from itertools import groupby
import logging
from uuid import UUID

from aiogram import Bot, Router
from aiogram.filters.command import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.formatting import Code, Text, as_list
from gel import AsyncIOExecutor as GelClient

from letta_bot.client import create_agent_from_template, get_or_create_letta_identity
from letta_bot.config import CONFIG
from letta_bot.queries.create_identity_async_edgeql import (
    create_identity as create_identity_query,
)
from letta_bot.queries.get_allowed_identity_async_edgeql import (
    get_allowed_identity as get_allowed_identity_query,
)
from letta_bot.queries.get_identity_async_edgeql import (
    get_identity as get_identity_query,
)
from letta_bot.queries.list_auth_requests_by_status_async_edgeql import (
    AuthStatus02,
    list_auth_requests_by_status as list_auth_requests_by_status_query,
)
from letta_bot.queries.resolve_auth_request_async_edgeql import (
    AuthStatus,
    ResourceType,
    resolve_auth_request as resolve_auth_request_query,
)
from letta_bot.queries.revoke_user_access_async_edgeql import (
    revoke_user_access as revoke_user_access_query,
)

LOGGER = logging.getLogger(__name__)


def admin_only(func: Callable) -> Callable:  # type: ignore[type-arg]
    """Decorator to restrict command to admin users only."""

    @wraps(func)
    async def wrapper(message: Message) -> None:
        if not message.from_user or message.from_user.id not in (CONFIG.admin_ids or []):
            await message.answer(Text('⛔ Access denied').as_markdown())
            return
        await func(message)

    return wrapper


# TODO: fix typing
def require_identity(
    gel_client: GelClient,
) -> Callable:  # type: ignore
    """Decorator to check identity access and inject identity object into handler.

    Verifies that the user has allowed identity access, fetches the identity,
    and passes it as 'identity' kwarg to the decorated handler.

    Args:
        gel_client: Gel database client for queries

    Returns:
        Decorator function that injects identity into handler kwargs
    """

    def decorator(func: Callable) -> Callable:  # type: ignore
        @wraps(func)
        async def wrapper(*args, **kwargs):  # type: ignore  # noqa: ANN002, ANN003, ANN202
            # Extract message or callback from args
            event = args[0] if args else None
            if not isinstance(event, (Message, CallbackQuery)):
                raise TypeError('First argument must be Message or CallbackQuery')

            # Get user from event
            from_user = event.from_user
            if not from_user:
                return None

            # Check if user has allowed identity
            if not await get_allowed_identity_query(gel_client, telegram_id=from_user.id):
                await event.answer(
                    Text(
                        'You need to request identity access first using /request_identity'
                    ).as_markdown()
                )
                return None

            # Fetch identity
            identity_list = await get_identity_query(gel_client, telegram_id=from_user.id)
            if not identity_list:
                # This shouldn't happen if get_allowed_identity returned True
                LOGGER.error(
                    f'Identity not found for user {from_user.id} '
                    'despite having allowed access'
                )
                await event.answer(
                    Text('Error: Identity not found. Please contact admin.').as_markdown()
                )
                return None

            # Inject identity into kwargs
            return await func(*args, identity=identity_list[0], **kwargs)

        return wrapper

    return decorator


def get_auth_router(bot: Bot, gel_client: GelClient) -> Router:
    """Create and return auth router with admin command handlers."""
    auth_router = Router(name=__name__)

    @auth_router.message(Command('admin'))
    @admin_only
    async def admin(message: Message) -> None:
        if not message.text:
            return

        parts = message.text.split(maxsplit=2)
        subcommand = parts[1].lower() if len(parts) > 1 else None

        match subcommand:
            case 'pending':
                await handle_pending(message, gel_client, bot)
            case 'allow':
                await handle_allow(message, gel_client, bot, parts)
            case 'deny':
                await handle_deny(message, gel_client, bot, parts)
            case 'revoke':
                await handle_revoke(message, gel_client, bot, parts)
            case 'list':
                await handle_list(message, gel_client)
            case _:
                await message.answer(
                    Text(
                        'Unknown subcommand. Available: pending, allow, deny, list, revoke'
                    ).as_markdown()
                )

    async def handle_pending(message: Message, gel_client: GelClient, bot: Bot) -> None:
        """List all pending authorization requests"""
        pending_requests = await list_auth_requests_by_status_query(
            gel_client, status=AuthStatus02.PENDING
        )

        if not pending_requests:
            await message.answer(Text('No pending authorization requests.').as_markdown())
            return

        response_lines = [Text('📋 Pending Authorization Requests:\n\n')]
        for req in pending_requests:
            user = req.user
            username_str = f'@{user.username}' if user.username else 'no username'
            response_lines.append(
                Text(
                    f'• User: {user.full_name or user.first_name} ({username_str})\n',
                    f'  Telegram ID: {user.telegram_id}\n',
                    '  Request ID: ',
                    Code(req.id),
                    '\n',
                    f'  Resource: {req.resource_type.value}\n',
                    f'  Resource ID: {req.resource_id}\n\n',
                    # TODO: Add approve and revoke command?
                )
            )

        await message.answer(as_list(*response_lines).as_markdown())

    async def handle_allow(
        message: Message, gel_client: GelClient, bot: Bot, parts: list[str]
    ) -> None:
        """Approve a user's authorization request"""
        if len(parts) < 3:
            await message.answer(Text('Usage: /admin allow <request_uuid>').as_markdown())
            return

        try:
            request_id = UUID(parts[2])
        except (ValueError, IndexError):
            await message.answer(
                Text('Invalid request_uuid. Must be a valid UUID.').as_markdown()
            )
            return

        result = await resolve_auth_request_query(
            gel_client, id=request_id, auth_status=AuthStatus.ALLOWED
        )

        if not result:
            await message.answer(Text(f'Request {request_id} not found').as_markdown())
            return

        resource_type, resource_id = result.resource_type, result.resource_id

        match resource_type:
            # NOTE: For now requested only if user doesn't have allowed identity
            case ResourceType.ACCESS_IDENTITY:
                # TODO: check if identity exists
                identity_result = await get_identity_query(
                    gel_client, telegram_id=result.user.telegram_id
                )
                if not identity_result:
                    # if identity doesn't exist create identity with letta
                    name, id_ = resource_id.rsplit(':', 1)
                    # TODO: change identity prefix based on local or prod env
                    letta_identity = await get_or_create_letta_identity(
                        identifier_key=f'tg-{id_}', name=name
                    )
                    await create_identity_query(
                        gel_client,
                        telegram_id=int(id_),
                        identifier_key=letta_identity.identifier_key,
                        # TODO: ask "Why two identity IDs and why
                        # the first one is optional in SDK and used for access"
                        identity_id=letta_identity.id or letta_identity.identifier_key,
                    )
            case ResourceType.CREATE_AGENT_FROM_TEMPLATE:
                identity_result = await get_identity_query(
                    gel_client, telegram_id=result.user.telegram_id
                )
                if not identity_result:
                    # TODO: Handle case when user doesn't have identity
                    # should create identity first
                    raise NotImplementedError(
                        'Cannot create agent from template without identity'
                    )
                await create_agent_from_template(
                    template_id=resource_id, identity_id=identity_result[0].identity_id
                )

        await message.answer(
            Text(f'✅ Authorization request approved: {request_id}\n').as_markdown()
        )

        # Notify user of approval
        try:
            resource_description = (
                'identity access'
                if resource_type == ResourceType.ACCESS_IDENTITY
                else f'assistant from template {resource_id}'
            )
            await bot.send_message(
                chat_id=result.user.telegram_id,
                text=Text(
                    f'✅ Your request for {resource_description} has been approved!\n\n'
                    'You can now use the bot.'
                ).as_markdown(),
            )
        except Exception as e:
            LOGGER.error(
                f'Failed to notify user {result.user.telegram_id} about approval: {e}'
            )

    async def handle_deny(
        message: Message, gel_client: GelClient, bot: Bot, parts: list[str]
    ) -> None:
        """Deny a user's authorization request"""
        if len(parts) < 3:
            await message.answer(
                Text('Usage: /admin deny <request_uuid> [reason]').as_markdown()
            )
            return

        try:
            request_id = UUID(parts[2])
        except (ValueError, IndexError):
            await message.answer(
                Text('Invalid request_uuid. Must be a valid UUID.').as_markdown()
            )
            return

        reason = parts[3] if len(parts) > 3 else None

        # Update request status to denied
        result = await resolve_auth_request_query(
            gel_client, id=request_id, auth_status=AuthStatus.DENIED
        )

        if not result:
            await message.answer(Text(f'Request {request_id} not found').as_markdown())
            return

        # TODO: Store denial reason in database (update AuthorizationRequest.response field)

        reason_msg = f' Reason: {reason}' if reason else ''
        await message.answer(
            Text(
                f'❌ Authorization request denied: {request_id}{reason_msg}\n'
            ).as_markdown()
        )

        # Notify user of denial with reason
        try:
            user_message_parts = ['❌ Your authorization request has been denied.']
            if reason:
                user_message_parts.append(f'\n\nReason: {reason}')
            user_message_parts.append(
                '\n\nYou can submit a new request using /request_identity or '
                '/new_assistant if needed.'
            )

            await bot.send_message(
                chat_id=result.user.telegram_id,
                text=Text(''.join(user_message_parts)).as_markdown(),
            )
        except Exception as e:
            LOGGER.error(
                f'Failed to notify user {result.user.telegram_id} about denial: {e}'
            )

    async def handle_revoke(
        message: Message, gel_client: GelClient, bot: Bot, parts: list[str]
    ) -> None:
        # NOTE: Revoke only identity access

        """Revoke a user's access"""
        if len(parts) < 3:
            await message.answer(Text('Usage: /admin revoke <telegram_id>').as_markdown())
            return

        try:
            telegram_id = int(parts[2])
        except ValueError:
            await message.answer(
                Text('Invalid telegram_id. Must be an integer.').as_markdown()
            )
            return

        # Revoke user identity access only
        result = await revoke_user_access_query(gel_client, telegram_id=telegram_id)

        if not result:
            await message.answer(
                Text(
                    f'No authorization requests found for user {telegram_id}'
                ).as_markdown()
            )
            return

        await message.answer(
            Text(
                f'🚫 Access revoked for user {telegram_id} '
                f'({len(result)} request(s) updated)\n'
            ).as_markdown()
        )

        # Notify user of revocation
        try:
            await bot.send_message(
                chat_id=telegram_id,
                text=Text(
                    '🚫 Your access to the bot has been revoked.\n\n'
                    'If you believe this was done in error, '
                    'please contact the administrator.\n'
                    'You can submit a new request using /request_identity '
                    'if you wish to regain access.'
                ).as_markdown(),
            )
        except Exception as e:
            LOGGER.error(f'Failed to notify user {telegram_id} about revocation: {e}')

    async def handle_list(message: Message, gel_client: GelClient) -> None:
        """List active users"""
        all_requests = await list_auth_requests_by_status_query(
            gel_client, status=AuthStatus02.ALLOWED
        )

        if not all_requests:
            await message.answer(Text('No active users.').as_markdown())
            return

        response_lines = ['👥 Active Users:\n']

        # Group by telegram_id (DB already returns sorted by telegram_id)
        for _, requests in groupby(all_requests, key=lambda r: r.user.telegram_id):
            # Convert iterator to list to use first item and iterate again
            requests_list = list(requests)
            user = requests_list[0].user
            username_str = f'@{user.username}' if user.username else 'no username'
            response_lines.append(
                f'• {user.full_name or user.first_name} ({username_str})\n'
                f'  Telegram ID: {user.telegram_id}\n'
            )

            # List all accesses for this user
            for req in requests_list:
                response_lines.append(
                    f'  └─ {req.resource_type.value}: {req.resource_id}\n'
                )

        await message.answer(Text(''.join(response_lines)).as_markdown())

    LOGGER.info('Auth handlers initialized')
    return auth_router
