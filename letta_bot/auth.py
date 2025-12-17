from itertools import groupby
import logging
from uuid import UUID

from aiogram import Bot, Router
from aiogram.filters.callback_data import CallbackData
from aiogram.filters.command import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.formatting import Code, Text, as_list
from aiogram.utils.keyboard import InlineKeyboardBuilder
from gel import AsyncIOExecutor
from letta_client import APIError

from letta_bot.broadcast import notify_admins
from letta_bot.client import (
    attach_identity_to_agent,
    client,
    create_agent_from_template,
    get_agent_identity_ids,
    get_agent_owner_telegram_id,
    get_or_create_letta_identity,
)
from letta_bot.config import CONFIG
from letta_bot.filters import AdminOnlyFilter
from letta_bot.letta_sdk_extensions import list_templates
from letta_bot.queries.check_pending_request_async_edgeql import (
    check_pending_request as check_pending_request_query,
)
from letta_bot.queries.create_auth_request_async_edgeql import (
    create_auth_request as create_auth_request_query,
)
from letta_bot.queries.create_identity_async_edgeql import (
    create_identity as create_identity_query,
)
from letta_bot.queries.get_allowed_identity_async_edgeql import (
    get_allowed_identity as get_allowed_identity_query,
)
from letta_bot.queries.get_auth_request_by_id_async_edgeql import (
    AuthStatus as AuthStatus03,
    get_auth_request_by_id as get_auth_request_by_id_query,
)
from letta_bot.queries.get_identity_async_edgeql import (
    GetIdentityResult,
    get_identity as get_identity_query,
)
from letta_bot.queries.get_identity_request_status_async_edgeql import (
    get_identity_request_status as get_identity_request_status_query,
)
from letta_bot.queries.get_pending_requests_by_agent_async_edgeql import (
    get_pending_requests_by_agent as get_pending_requests_by_agent_query,
)
from letta_bot.queries.get_user_by_telegram_id_async_edgeql import (
    get_user_by_telegram_id as get_user_by_telegram_id_query,
)
from letta_bot.queries.is_registered_async_edgeql import (
    is_registered as is_registered_query,
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
from letta_bot.queries.update_auth_request_status_async_edgeql import (
    update_auth_request_status as update_auth_request_status_query,
)
from letta_bot.utils import validate_uuid

LOGGER = logging.getLogger(__name__)


auth_router = Router(name=__name__)


class AgentAccessCallback(CallbackData, prefix='agentaccess'):
    request_id: str
    action: str


async def request_owner_permission(
    bot: Bot,
    owner_telegram_id: int,
    requester_name: str,
    requester_username: str | None,
    requester_telegram_id: int,
    agent_id: str,
    request_id: UUID,
) -> bool:
    """Send access request notification to agent owner with approve/deny buttons.

    Returns True if notification was sent successfully, False otherwise.
    """
    builder = InlineKeyboardBuilder()
    builder.button(
        text='✅ Approve',
        callback_data=AgentAccessCallback(
            request_id=str(request_id), action='approve'
        ).pack(),
    )
    builder.button(
        text='❌ Deny',
        callback_data=AgentAccessCallback(request_id=str(request_id), action='deny').pack(),
    )
    builder.adjust(2)

    # Fetch agent details for richer notification
    agent_info = f'Agent ID: {agent_id}'
    try:
        agent = await client.agents.retrieve(agent_id)
        agent_info = f'Assistant: {agent.name}\nModel: {agent.model}\nID: {agent_id}'
    except APIError as e:
        LOGGER.warning(f'Could not fetch agent {agent_id} details: {e}')

    try:
        await bot.send_message(
            owner_telegram_id,
            Text(
                f'📬 Assistant Access Request\n\n'
                f'User: {requester_name} '
                f'(@{requester_username or "no username"})\n'
                f'Telegram ID: {requester_telegram_id}\n\n'
                f'{agent_info}\n\n'
                'Do you want to grant access to this user?'
            ).as_markdown(),
            reply_markup=builder.as_markup(),
        )
        return True
    except Exception as e:
        LOGGER.error(f'Failed to notify owner {owner_telegram_id}: {e}')
        return False


# NOTE: Callback should fit in 64 chars
class NewAssistantCallback(CallbackData, prefix='new'):
    template_name: str
    version: str = 'latest'


# =============================================================================
# User Access Request Handlers
# =============================================================================


@auth_router.message(Command('access'))
async def access_command(message: Message, bot: Bot, gel_client: AsyncIOExecutor) -> None:
    """Request general bot access (identity only, no assistant capabilities)."""
    if not message.from_user:
        return

    # Check if user already has identity access
    if await get_allowed_identity_query(gel_client, telegram_id=message.from_user.id):
        await message.answer(Text('✅ You already have identity access').as_markdown())
        return

    # Check if user already has a pending identity request
    has_pending = await check_pending_request_query(
        gel_client,
        telegram_id=message.from_user.id,
        resource_type=ResourceType.ACCESS_IDENTITY,
    )
    if has_pending:
        await message.answer(
            Text(
                '⏳ You already have a pending identity access request. '
                'Please wait for admin approval.'
            ).as_markdown()
        )
        return

    # Create identity access request
    await create_auth_request_query(
        gel_client,
        telegram_id=message.from_user.id,
        resource_type=ResourceType.ACCESS_IDENTITY,
        resource_id=f'{message.from_user.first_name}:{message.from_user.id}',
    )

    # Notify user
    await message.answer(
        Text(
            '✅ Your identity access request has been submitted '
            'and is pending admin approval'
        ).as_markdown()
    )

    # Notify admins
    await notify_admins(bot, Text('New identity access request').as_markdown())


@auth_router.message(Command('new'))
async def new_assistant(message: Message) -> None:
    # TODO: if no pending requests

    # List available templates using SDK extension
    paginator = await list_templates(client, CONFIG.letta_project_id)
    page = await paginator
    templates = page.templates

    builder = InlineKeyboardBuilder()
    for t in templates:
        data = NewAssistantCallback(template_name=t.name, version=t.latest_version)
        builder.button(text=f'Create assistant: {t.name}', callback_data=data.pack())
    builder.adjust(1)  # One button per row for vertical layout
    await message.answer(
        Text(
            'Create your assistant\n\nSee /about for detailed template descriptions'
        ).as_markdown(),
        reply_markup=builder.as_markup(),
    )


@auth_router.callback_query(NewAssistantCallback.filter())
async def register_assistant_request(
    callback: CallbackQuery,
    callback_data: NewAssistantCallback,
    bot: Bot,
    gel_client: AsyncIOExecutor,
) -> None:
    # Check if user is registered
    if not await is_registered_query(gel_client, telegram_id=callback.from_user.id):
        LOGGER.error(
            f'User {callback.from_user.id} attempted '
            'to request resource without being registered'
        )
        await callback.answer(
            Text('You must use /start command first to register').as_markdown(),
        )
        return

    # Check if user already has a pending assistant request
    has_pending = await check_pending_request_query(
        gel_client,
        telegram_id=callback.from_user.id,
        resource_type=ResourceType.CREATE_AGENT_FROM_TEMPLATE,
    )
    if has_pending:
        await callback.answer(
            Text(
                '⏳ You already have a pending assistant request. '
                'Please wait for admin approval.'
            ).as_markdown()
        )
        return

    # Check identity status: None = no request, pending = waiting, allowed = has access
    identity_request = await get_identity_request_status_query(
        gel_client, telegram_id=callback.from_user.id
    )
    # Only create identity request if none exists (matches DB constraint behavior)
    # TODO: maybe identity name could be customed
    if not identity_request:
        await create_auth_request_query(
            gel_client,
            telegram_id=callback.from_user.id,
            resource_type=ResourceType.ACCESS_IDENTITY,
            # NOTE: name:id
            resource_id=f'{callback.from_user.first_name}:{callback.from_user.id}',
        )
    await create_auth_request_query(
        gel_client,
        telegram_id=callback.from_user.id,
        resource_type=ResourceType.CREATE_AGENT_FROM_TEMPLATE,
        resource_id=callback_data.pack(),
    )

    # Update original message to show selection and remove keyboard
    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            Text(
                f'✅ Request submitted for: {callback_data.template_name}\n\n'
                'Pending admin approval'
            ).as_markdown(),
        )

    # Acknowledge the callback
    await callback.answer()

    # notify admins
    if CONFIG.admin_ids is None:
        return
    for tg_id in CONFIG.admin_ids:
        await bot.send_message(tg_id, Text('New assistant request').as_markdown())


# =============================================================================
# Admin Authorization Handlers
# =============================================================================


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
                '  Telegram ID: ',
                Code(user.telegram_id),
                '\n',
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

    request_uuid = parts[1].strip()

    # Validate request_uuid format
    if not validate_uuid(request_uuid):
        await message.answer(
            Text('Invalid request_uuid. Must be a valid UUID.').as_markdown()
        )
        return

    request_id = UUID(request_uuid)

    # Fetch request data WITHOUT modifying it
    result = await get_auth_request_by_id_query(gel_client, id=request_id)

    if not result:
        await message.answer(Text(f'Request {request_id} not found').as_markdown())
        return

    # Check if request is still pending
    if result.status != AuthStatus03.PENDING:
        await message.answer(
            Text(
                f'Request {request_id} has already been processed '
                f'(status: {result.status.value})'
            ).as_markdown()
        )
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
                template_id=resource_id,
                identity_id=identity_result[0].identity_id,
                tags=[
                    f'owner-tg-{result.user.telegram_id}',
                    f'creator-tg-{result.user.telegram_id}',
                ],
            )

        case ResourceType.ACCESS_AGENT:
            # Attach agent to requester's identity
            identity_result = await get_identity_query(
                gel_client, telegram_id=result.user.telegram_id
            )
            if not identity_result:
                await message.answer(
                    Text(
                        f'❌ User {result.user.telegram_id} does not have an identity. '
                        'They must request identity access first.'
                    ).as_markdown()
                )
                return

            # Check if agent still exists before attaching
            try:
                agent = await client.agents.retrieve(
                    agent_id=resource_id, include=['agent.tags']
                )
            except APIError as e:
                LOGGER.error(f'Agent {resource_id} not found during approval: {e}')
                await message.answer(
                    Text(
                        f'❌ Agent {resource_id} no longer exists. Cannot grant access.'
                    ).as_markdown()
                )
                return

            # Check if agent has an owner tag
            has_owner_tag = False
            if agent.tags:
                has_owner_tag = any(tag.startswith('owner-tg-') for tag in agent.tags)

            # If no owner tag, assign first requester as owner
            if not has_owner_tag:
                owner_tag = f'owner-tg-{result.user.telegram_id}'
                existing_tags = list(agent.tags) if agent.tags else []
                new_tags = existing_tags + [owner_tag]

                try:
                    await client.agents.update(agent_id=resource_id, tags=new_tags)
                    LOGGER.info(
                        f'Assigned owner tag {owner_tag} to agent {resource_id} '
                        f'for first requester'
                    )
                except APIError as e:
                    LOGGER.error(f'Failed to update agent tags: {e}')
                    await message.answer(
                        Text('❌ Failed to update agent tags').as_markdown()
                    )
                    return

                # Forward existing pending requests to new owner
                pending_requests = await get_pending_requests_by_agent_query(
                    gel_client, agent_id=resource_id
                )
                for pending_req in pending_requests:
                    # Skip the current request being approved
                    if pending_req.id == request_id:
                        continue
                    await request_owner_permission(
                        bot=bot,
                        owner_telegram_id=result.user.telegram_id,
                        requester_name=(
                            pending_req.user.full_name or pending_req.user.first_name
                        ),
                        requester_username=pending_req.user.username,
                        requester_telegram_id=pending_req.user.telegram_id,
                        agent_id=resource_id,
                        request_id=pending_req.id,
                    )
                if pending_requests:
                    LOGGER.info(
                        f'Forwarded {len(pending_requests)} pending requests '
                        f'for agent {resource_id} to new owner {result.user.telegram_id}'
                    )
            else:
                owner_tag = f'owner-tg-{result.user.telegram_id}'
                if agent.tags and owner_tag not in agent.tags:
                    LOGGER.warning(
                        f'User {result.user.telegram_id} attempted to access agent '
                        f'{resource_id} without being the owner'
                    )
                    await message.answer(
                        Text(
                            '⚠️ Cannot approve request: You are not the owner of this '
                            'assistant. Only the owner can grant access to other users.'
                        ).as_markdown()
                    )
                    return

            await attach_identity_to_agent(
                agent_id=resource_id, identity_id=identity_result[0].identity_id
            )

    await update_auth_request_status_query(
        gel_client, id=request_id, auth_status=AuthStatus.ALLOWED
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
            # ACCESS_AGENT or CREATE_AGENT_FROM_TEMPLATE
            agents = await client.identities.agents.list(
                identity_id=identity_result[0].identity_id, limit=2, order='desc'
            )
            has_multiple = len(agents.items) > 1
            hint = '\nUse /switch to select it.' if has_multiple else ''

            if resource_type == ResourceType.ACCESS_AGENT:
                agent = await client.agents.retrieve(agent_id=resource_id)
                user_message = f'✅ Access to "{agent.name}" granted!{hint}'
            else:
                agent = agents.items[0]  # newest
                user_message = f'✅ Your new assistant "{agent.name}" is ready!{hint}'
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

    request_uuid = parts[1].strip()

    # Validate request_uuid format
    if not validate_uuid(request_uuid):
        await message.answer(
            Text('Invalid request_uuid. Must be a valid UUID.').as_markdown()
        )
        return

    reason = parts[2] if len(parts) > 2 else None

    # Update request status to denied
    request_id = UUID(request_uuid)
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
            '\n\nYou can submit a new request using /new or /access if needed.'
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
                'You can submit a new request using /new or '
                '/access if you wish to regain access.'
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

    response_parts = [Text('👥 Active Users:')]

    # Group by telegram_id (DB already returns sorted by telegram_id)
    for _, requests in groupby(all_requests, key=lambda r: r.user.telegram_id):
        # Convert iterator to list to use first item and iterate again
        requests_list = list(requests)
        user = requests_list[0].user
        username_str = f'@{user.username}' if user.username else 'no username'
        response_parts.append(
            Text(
                f'• {user.full_name or user.first_name} ({username_str})\n  Telegram ID: ',
                Code(str(user.telegram_id)),
            )
        )

        # List all accesses for this user
        for req in requests_list:
            response_parts.append(
                Text(f'  └─ {req.resource_type.value}: ', req.resource_id)
            )

    await message.answer(as_list(*response_parts).as_markdown())


@auth_router.message(Command('attach'), flags={'require_identity': True})
async def attach_to_agent(
    message: Message,
    bot: Bot,
    gel_client: AsyncIOExecutor,
    identity: GetIdentityResult,
) -> None:
    """Request to attach to an existing assistant by ID.

    Sends access request to the assistant's owner for approval.
    Once approved, the user's identity is attached to the agent,
    granting them full access to interact with it.
    """
    if not message.from_user or not message.text:
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer(Text('Usage: /attach <agent_id>').as_markdown())
        return

    agent_id = parts[1]

    # Validate agent_id format: agent-{uuid}
    if not agent_id.startswith('agent-') or not validate_uuid(
        agent_id.removeprefix('agent-')
    ):
        await message.answer(
            Text('Invalid agent ID format. Must be agent-{uuid}.').as_markdown()
        )
        return

    # First, check if agent exists and get identity info
    try:
        agent_identity_ids = await get_agent_identity_ids(agent_id)
    except APIError as e:
        LOGGER.error(f'Failed to retrieve agent {agent_id}: {e}')
        await message.answer(
            Text(
                f'❌ Assistant with ID {agent_id} not found.\n\n'
                'Please check the agent ID and try again.'
            ).as_markdown()
        )
        return

    try:
        if identity.identity_id in agent_identity_ids:
            await message.answer(
                Text('✅ You already have access to this assistant.').as_markdown()
            )
            return

        if await check_pending_request_query(
            gel_client,
            telegram_id=message.from_user.id,
            resource_type=ResourceType.ACCESS_AGENT,
            resource_id=agent_id,
            status=AuthStatus.PENDING,
        ):
            await message.answer(
                Text(
                    '⏳ You already have a pending request for this assistant. '
                    'Please wait for approval.'
                ).as_markdown()
            )
            return

        owner_telegram_id = await get_agent_owner_telegram_id(agent_id)

        if len(agent_identity_ids) > 0 and not owner_telegram_id:
            LOGGER.error(
                f'Agent {agent_id} has {len(agent_identity_ids)} identities '
                f'but no owner tag. Invalid state.'
            )
            await message.answer(
                Text(
                    '❌ This assistant is in an invalid state:\n\n'
                    'It has users but no owner. Please contact an administrator '
                    'to fix this issue.'
                ).as_markdown()
            )
            return

        if not owner_telegram_id:
            await create_auth_request_query(
                gel_client,
                telegram_id=message.from_user.id,
                resource_type=ResourceType.ACCESS_AGENT,
                resource_id=agent_id,
            )

            await message.answer(
                Text(
                    '✅ Access request submitted to admins '
                    'for unowned assistant.\n\n'
                    'Pending admin approval.'
                ).as_markdown()
            )

            # Notify admins
            await notify_admins(
                bot,
                Text(
                    f'📬 New assistant access request\n\n'
                    f'User: {message.from_user.full_name} '
                    f'(@{message.from_user.username})\n'
                    f'Telegram ID: {message.from_user.id}\n'
                    f'Agent ID: {agent_id}\n\n'
                    'This assistant has no owner tag. '
                    'Use /pending to review.'
                ).as_markdown(),
            )
            return

        owner_user = await get_user_by_telegram_id_query(
            gel_client, telegram_id=owner_telegram_id
        )

        if not owner_user:
            # Fallback to admins if owner not found in database
            LOGGER.warning(
                f'Owner with telegram_id {owner_telegram_id} not found in database '
                f'for agent {agent_id}. Falling back to admins.'
            )

            await create_auth_request_query(
                gel_client,
                telegram_id=message.from_user.id,
                resource_type=ResourceType.ACCESS_AGENT,
                resource_id=agent_id,
            )

            await message.answer(
                Text(
                    '✅ Access request submitted to admins '
                    '(assistant owner unavailable).\n\n'
                    'Pending admin approval.'
                ).as_markdown()
            )

            # Notify admins
            await notify_admins(
                bot,
                Text(
                    f'📬 New assistant access request\n\n'
                    f'User: {message.from_user.full_name} '
                    f'(@{message.from_user.username})\n'
                    f'Telegram ID: {message.from_user.id}\n'
                    f'Agent ID: {agent_id}\n\n'
                    'Assistant owner not found in database. '
                    'Use /pending to review.'
                ).as_markdown(),
            )
            return

        # Create authorization request in database
        request_result = await create_auth_request_query(
            gel_client,
            telegram_id=message.from_user.id,
            resource_type=ResourceType.ACCESS_AGENT,
            resource_id=agent_id,
        )

        # Notify owner
        success = await request_owner_permission(
            bot=bot,
            owner_telegram_id=owner_telegram_id,
            requester_name=message.from_user.full_name or message.from_user.first_name,
            requester_username=message.from_user.username,
            requester_telegram_id=message.from_user.id,
            agent_id=agent_id,
            request_id=request_result.id,
        )

        if not success:
            await message.answer(
                Text(
                    '❌ Failed to notify assistant owner. Please try again later.'
                ).as_markdown()
            )
            return

        await message.answer(
            Text(
                '✅ Access request sent to assistant owner.\n\n'
                'You will be notified when they respond.'
            ).as_markdown()
        )

    except Exception as e:
        LOGGER.error(f'Error in request_agent_access: {e}')
        await message.answer(
            Text('❌ An error occurred while processing your request.').as_markdown()
        )
        raise


@auth_router.callback_query(AgentAccessCallback.filter(), flags={'require_identity': True})
async def handle_agent_access_callback(
    callback: CallbackQuery,
    callback_data: AgentAccessCallback,
    bot: Bot,
    gel_client: AsyncIOExecutor,
) -> None:
    """Handle owner's approval/denial of agent access request."""
    if not callback.from_user or not callback.message:
        return

    try:
        request_id = UUID(callback_data.request_id)

        request = await get_auth_request_by_id_query(gel_client, id=request_id)

        if not request:
            await callback.answer('❌ Request not found or already processed')
            return

        agent_id = request.resource_id

        owner_telegram_id = await get_agent_owner_telegram_id(agent_id)

        if not owner_telegram_id:
            if CONFIG.admin_ids is None or callback.from_user.id not in CONFIG.admin_ids:
                await callback.answer('❌ Only admins can approve unowned assistants')
                LOGGER.warning(
                    f'User {callback.from_user.id} attempted to approve/deny '
                    f'agent access request {request_id} '
                    f'for unowned agent {agent_id} without being admin'
                )
                return
        else:
            if callback.from_user.id != owner_telegram_id:
                await callback.answer('❌ You are not the owner of this assistant')
                LOGGER.warning(
                    f'User {callback.from_user.id} attempted to approve/deny '
                    f'agent access request {request_id} without being owner. '
                    f'Actual owner: {owner_telegram_id}'
                )
                return

        if callback_data.action == 'approve':
            # Get requester's identity
            requester_identity = await get_identity_query(
                gel_client, telegram_id=request.user.telegram_id
            )

            if not requester_identity:
                await callback.answer('❌ Requester identity not found')
                return

            # Attach agent to requester's identity
            try:
                await attach_identity_to_agent(
                    agent_id=agent_id,
                    identity_id=requester_identity[0].identity_id,
                )
            except Exception as attach_error:
                LOGGER.error(
                    f'Failed to attach agent {agent_id} to identity '
                    f'{requester_identity[0].identity_id} '
                    f'for request {request_id}: {attach_error}'
                )
                await callback.answer('❌ Failed to attach assistant')
                return

            result = await resolve_auth_request_query(
                gel_client, id=request_id, auth_status=AuthStatus.ALLOWED
            )

            if not result:
                LOGGER.warning(
                    f'Agent {agent_id} attached to identity '
                    f'{requester_identity[0].identity_id} '
                    f'but request {request_id} not found or already processed'
                )
                await callback.answer('❌ Request already processed')
                return

            if isinstance(callback.message, Message):
                await callback.message.edit_text(
                    Text(
                        f'✅ Access granted\n\n'
                        f'User: {result.user.full_name or result.user.first_name}\n'
                        f'Agent ID: {agent_id}'
                    ).as_markdown()
                )

            try:
                await bot.send_message(
                    result.user.telegram_id,
                    Text(
                        f'✅ Your assistant access request has been approved!\n\n'
                        f'Agent ID: {agent_id}\n\n'
                        'You can now use /switch to select this assistant.'
                    ).as_markdown(),
                )
            except Exception as e:
                LOGGER.error(f'Failed to notify requester: {e}')

            await callback.answer('✅ Access granted')

        elif callback_data.action == 'deny':
            result = await resolve_auth_request_query(
                gel_client, id=request_id, auth_status=AuthStatus.DENIED
            )

            if not result:
                await callback.answer('❌ Request not found or already processed')
                return

            if isinstance(callback.message, Message):
                await callback.message.edit_text(
                    Text(
                        f'❌ Access denied\n\n'
                        f'User: {result.user.full_name or result.user.first_name}\n'
                        f'Agent ID: {agent_id}'
                    ).as_markdown()
                )

            try:
                await bot.send_message(
                    result.user.telegram_id,
                    Text(
                        f'❌ Your assistant access request was denied.\n\n'
                        f'Agent ID: {agent_id}'
                    ).as_markdown(),
                )
            except Exception as e:
                LOGGER.error(f'Failed to notify requester: {e}')

            await callback.answer('❌ Access denied')

    except Exception as e:
        LOGGER.error(f'Error in handle_agent_access_callback: {e}')
        await callback.answer('❌ Error processing request')
        raise
