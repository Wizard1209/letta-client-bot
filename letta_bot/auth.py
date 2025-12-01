from itertools import groupby
import logging
from uuid import UUID

from aiogram import Bot, Router
from aiogram.filters.command import Command
from aiogram.types import Message
from aiogram.utils.formatting import Code, Text, as_list
from gel import AsyncIOExecutor

from letta_bot.client import create_agent_from_template, get_or_create_letta_identity
from letta_bot.filters import AdminOnlyFilter
from letta_bot.queries.create_identity_async_edgeql import (
    create_identity as create_identity_query,
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


auth_router = Router(name=__name__)


@auth_router.message(Command('pending'), AdminOnlyFilter)
async def pending_command(message: Message, gel_client: AsyncIOExecutor) -> None:
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
                f'  Resource ID: {req.resource_id}\n',
                '  → ',
                Code(f'/allow {req.id}'),
                '\n\n',
            )
        )

    await message.answer(as_list(*response_lines).as_markdown())


@auth_router.message(Command('allow'), AdminOnlyFilter)
async def allow_command(message: Message, bot: Bot, gel_client: AsyncIOExecutor) -> None:
    """Approve a user's authorization request."""
    if not message.text:
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(Text('Usage: /allow <request_uuid>').as_markdown())
        return

    try:
        request_id = UUID(parts[1])
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
        if resource_type == ResourceType.ACCESS_IDENTITY:
            user_message = (
                '✅ Your request for identity access has been approved!\n\n'
                'Once your assistant will be available I will let you know'
            )
        else:
            user_message = (
                '✅ Your new assistant is ready!\n\nJust type a message to start chatting!'
            )
        await bot.send_message(
            chat_id=result.user.telegram_id,
            text=Text(user_message).as_markdown(),
        )
    except Exception as e:
        LOGGER.error(f'Failed to notify user {result.user.telegram_id} about approval: {e}')


@auth_router.message(Command('deny'), AdminOnlyFilter)
async def deny_command(message: Message, bot: Bot, gel_client: AsyncIOExecutor) -> None:
    """Deny a user's authorization request."""
    if not message.text:
        return

    parts = message.text.split(maxsplit=2)
    if len(parts) < 2:
        await message.answer(Text('Usage: /deny <request_uuid> [reason]').as_markdown())
        return

    try:
        request_id = UUID(parts[1])
    except (ValueError, IndexError):
        await message.answer(
            Text('Invalid request_uuid. Must be a valid UUID.').as_markdown()
        )
        return

    reason = parts[2] if len(parts) > 2 else None

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
        Text(f'❌ Authorization request denied: {request_id}{reason_msg}\n').as_markdown()
    )

    # Notify user of denial with reason
    try:
        user_message_parts = ['❌ Your authorization request has been denied.']
        if reason:
            user_message_parts.append(f'\n\nReason: {reason}')
        user_message_parts.append(
            '\n\nYou can submit a new request using /newassistant or /botaccess if needed.'
        )

        await bot.send_message(
            chat_id=result.user.telegram_id,
            text=Text(''.join(user_message_parts)).as_markdown(),
        )
    except Exception as e:
        LOGGER.error(f'Failed to notify user {result.user.telegram_id} about denial: {e}')


@auth_router.message(Command('revoke'), AdminOnlyFilter)
async def revoke_command(message: Message, bot: Bot, gel_client: AsyncIOExecutor) -> None:
    """Revoke a user's access (identity only)."""
    if not message.text:
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(Text('Usage: /revoke <telegram_id>').as_markdown())
        return

    try:
        telegram_id = int(parts[1])
    except ValueError:
        await message.answer(Text('Invalid telegram_id. Must be an integer.').as_markdown())
        return

    # Revoke user identity access only
    result = await revoke_user_access_query(gel_client, telegram_id=telegram_id)

    if not result:
        await message.answer(
            Text(f'No authorization requests found for user {telegram_id}').as_markdown()
        )
        return

    await message.answer(
        Text(
            f'🚫 Access revoked for user {telegram_id} ({len(result)} request(s) updated)\n'
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
                'You can submit a new request using /newassistant or '
                '/botaccess if you wish to regain access.'
            ).as_markdown(),
        )
    except Exception as e:
        LOGGER.error(f'Failed to notify user {telegram_id} about revocation: {e}')


@auth_router.message(Command('users'), AdminOnlyFilter)
async def users_command(message: Message, gel_client: AsyncIOExecutor) -> None:
    """List active users."""
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
            response_lines.append(f'  └─ {req.resource_type.value}: {req.resource_id}\n')

    await message.answer(Text(''.join(response_lines)).as_markdown())
