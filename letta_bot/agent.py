import logging
from uuid import UUID

from aiogram import Bot, Router
from aiogram.filters.callback_data import CallbackData
from aiogram.filters.command import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.chat_action import ChatActionSender
from aiogram.utils.formatting import Bold, Code, Text, as_list, as_marked_list
from aiogram.utils.keyboard import InlineKeyboardBuilder
from gel import AsyncIOExecutor
from httpx import ReadTimeout
from letta_client import APIError

from letta_bot.client import (
    attach_identity_to_agent,
    client,
    get_agent_creator_telegram_id,
    get_agent_identity_ids,
    get_default_agent,
)
from letta_bot.config import CONFIG
from letta_bot.letta_sdk_extensions import context_window_overview, list_templates
from letta_bot.queries.check_pending_request_async_edgeql import (
    check_pending_request as check_pending_request_query,
)
from letta_bot.queries.create_auth_request_async_edgeql import (
    ResourceType,
    create_auth_request as create_auth_request_query,
)
from letta_bot.queries.get_allowed_identity_async_edgeql import (
    get_allowed_identity as get_allowed_identity_query,
)
from letta_bot.queries.get_auth_request_by_id_async_edgeql import (
    get_auth_request_by_id as get_auth_request_by_id_query,
)
from letta_bot.queries.get_identity_async_edgeql import (
    GetIdentityResult,
    get_identity as get_identity_query,
)
from letta_bot.queries.get_user_by_telegram_id_async_edgeql import (
    get_user_by_telegram_id as get_user_by_telegram_id_query,
)
from letta_bot.queries.is_registered_async_edgeql import (
    is_registered as is_registered_query,
)
from letta_bot.queries.reset_selected_agent_async_edgeql import (
    reset_selected_agent as reset_selected_agent_query,
)
from letta_bot.queries.resolve_auth_request_async_edgeql import (
    AuthStatus,
    resolve_auth_request as resolve_auth_request_query,
)
from letta_bot.queries.set_selected_agent_async_edgeql import (
    set_selected_agent as set_selected_agent_query,
)
from letta_bot.response_handler import AgentStreamHandler
from letta_bot.transcription import TranscriptionError, get_transcription_service
from letta_bot.utils import notify_admins, validate_uuid

LOGGER = logging.getLogger(__name__)


agent_commands_router = Router(name=f'{__name__}.commands')
agent_router = Router(name=f'{__name__}.messaging')


# NOTE: Callback should fit in 64 chars
class NewAssistantCallback(CallbackData, prefix='newassistant'):
    template_name: str
    version: str = 'latest'


class SwitchAssistantCallback(CallbackData, prefix='switch'):
    agent_id: str


class AgentAccessCallback(CallbackData, prefix='agentaccess'):
    request_id: str
    action: str


@agent_commands_router.message(Command('botaccess'))
async def botaccess(message: Message, bot: Bot, gel_client: AsyncIOExecutor) -> None:
    """Request or restore bot access without requesting an agent."""
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


@agent_commands_router.message(Command('newassistant'))
async def newassistant(message: Message) -> None:
    # TODO: if no pending requests

    # List available templates using SDK extension
    paginator = await list_templates(client, CONFIG.letta_project_id)
    page = await paginator
    templates = page.templates

    builder = InlineKeyboardBuilder()
    for t in templates:
        data = NewAssistantCallback(template_name=t.name, version=t.latest_version)
        builder.button(text=f'{t.name}', callback_data=data.pack())
    builder.adjust(1)  # One button per row for vertical layout
    await message.answer(
        Text(
            'Choose a template for your assistant\n\n'
            'See /about for detailed template descriptions'
        ).as_markdown(),
        reply_markup=builder.as_markup(),
    )


@agent_commands_router.callback_query(NewAssistantCallback.filter())
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

    if not await get_allowed_identity_query(gel_client, telegram_id=callback.from_user.id):
        # TODO: maybe identity name could be customed
        # Check if user already has a pending identity request
        has_pending = await check_pending_request_query(
            gel_client,
            telegram_id=callback.from_user.id,
            resource_type=ResourceType.ACCESS_IDENTITY,
        )
        if has_pending:
            await callback.answer(
                Text(
                    '⏳ You already have a pending identity access request. '
                    'Please wait for admin approval.'
                ).as_markdown()
            )
            return

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


@agent_commands_router.message(Command('switch'), flags={'require_identity': True})
async def switch(message: Message, identity: GetIdentityResult) -> None:
    """List user's assistants and allow switching between them."""
    if not message.from_user:
        return

    # List all agents for this identity
    try:
        # Collect ALL agents across all pages
        all_agents = []
        async for agent in client.identities.agents.list(identity_id=identity.identity_id):
            all_agents.append(agent)

        if not all_agents:
            await message.answer(
                Text(
                    "You don't have any assistants yet. Use /newassistant to request one."
                ).as_markdown()
            )
            return

        # Build inline keyboard with assistants
        builder = InlineKeyboardBuilder()
        for agent in all_agents:
            # Mark currently selected assistant
            is_selected = agent.id == identity.selected_agent
            button_text = f'{"✅ " if is_selected else ""}{agent.name}'
            callback_data = SwitchAssistantCallback(agent_id=agent.id)
            builder.button(text=button_text, callback_data=callback_data.pack())

        # Adjust layout for vertical buttons
        builder.adjust(1)

        await message.answer(
            Text('Select an assistant:').as_markdown(),
            reply_markup=builder.as_markup(),
        )

    except APIError as e:
        LOGGER.error(f'Error listing agents for identity {identity.identity_id}: {e}')
        await message.answer(Text('Error retrieving your assistants').as_markdown())


@agent_commands_router.callback_query(
    SwitchAssistantCallback.filter(), flags={'require_identity': True}
)
async def handle_switch_assistant(
    callback: CallbackQuery,
    callback_data: SwitchAssistantCallback,
    identity: GetIdentityResult,
    gel_client: AsyncIOExecutor,
) -> None:
    """Handle assistant selection callback."""
    if not callback.from_user:
        return

    # Check if already selected - avoid unnecessary update and Telegram API error
    if identity.selected_agent == callback_data.agent_id:
        await callback.answer('Already selected')
        return

    # Update selected agent in database
    await set_selected_agent_query(
        gel_client, identity_id=identity.identity_id, agent_id=callback_data.agent_id
    )

    # Rebuild keyboard with updated selection
    try:
        builder = InlineKeyboardBuilder()
        async for agent in client.identities.agents.list(identity_id=identity.identity_id):
            is_selected = agent.id == callback_data.agent_id
            button_text = f'{"✅ " if is_selected else ""}{agent.name}'
            builder.button(
                text=button_text,
                callback_data=SwitchAssistantCallback(agent_id=agent.id).pack(),
            )
        builder.adjust(1)

        # Update keyboard to show new selection
        if isinstance(callback.message, Message):
            await callback.message.edit_reply_markup(
                reply_markup=builder.as_markup(),
            )
    except APIError as e:
        LOGGER.error(f'Error updating keyboard: {e}')

    # Toast notification for success
    await callback.answer('✅ Assistant switched')


@agent_commands_router.message(Command('accessassistant'), flags={'require_identity': True})
async def request_agent_access(
    message: Message,
    bot: Bot,
    gel_client: AsyncIOExecutor,
    identity: GetIdentityResult,
) -> None:
    """Request access to another user's agent or unowned agent."""
    if not message.from_user or not message.text:
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer(Text('Usage: /accessassistant <agent_id>').as_markdown())
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

    # First, check if agent exists and get identities
    try:
        agent_state = await client.agents.retrieve(
            agent_id=agent_id, include=['agent.identities']
        )
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
        user_has_access = agent_state.identities is not None and any(
            ident.id == identity.identity_id for ident in agent_state.identities
        )
        if user_has_access:
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

        creator_telegram_id = await get_agent_creator_telegram_id(agent_id)

        if (
            agent_state.identities is not None and len(agent_state.identities) > 0
        ) and not creator_telegram_id:
            LOGGER.error(
                f'Agent {agent_id} has {len(agent_state.identities)} identities '
                f'but no creator tag. Invalid state.'
            )
            await message.answer(
                Text(
                    '❌ This assistant is in an invalid state:\n\n'
                    'It has users but no owner. Please contact an administrator '
                    'to fix this issue.'
                ).as_markdown()
            )
            return

        if not creator_telegram_id:
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
                    'This assistant has no creator tag. '
                    'Use /pending to review.'
                ).as_markdown(),
            )
            return

        creator_user = await get_user_by_telegram_id_query(
            gel_client, telegram_id=creator_telegram_id
        )

        if not creator_user:
            # Fallback to admins if creator not found in database
            LOGGER.warning(
                f'Creator with telegram_id {creator_telegram_id} not found in database '
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
                    '(assistant creator unavailable).\n\n'
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
                    'Assistant creator not found in database. '
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

        builder = InlineKeyboardBuilder()
        builder.button(
            text='✅ Approve',
            callback_data=AgentAccessCallback(
                request_id=str(request_result.id), action='approve'
            ).pack(),
        )
        builder.button(
            text='❌ Deny',
            callback_data=AgentAccessCallback(
                request_id=str(request_result.id), action='deny'
            ).pack(),
        )
        builder.adjust(2)  # Two buttons per row

        # Notify creator only
        try:
            await bot.send_message(
                creator_telegram_id,
                Text(
                    f'📬 Assistant Access Request\n\n'
                    f'User: {message.from_user.full_name} '
                    f'(@{message.from_user.username or "no username"})\n'
                    f'Telegram ID: {message.from_user.id}\n'
                    f'Agent ID: {agent_id}\n\n'
                    'Do you want to grant access to this user?'
                ).as_markdown(),
                reply_markup=builder.as_markup(),
            )
        except Exception as e:
            LOGGER.error(f'Failed to notify creator {creator_telegram_id}: {e}')
            await message.answer(
                Text(
                    '❌ Failed to notify assistant creator. Please try again later.'
                ).as_markdown()
            )
            return

        await message.answer(
            Text(
                '✅ Access request sent to assistant creator.\n\n'
                'You will be notified when they respond.'
            ).as_markdown()
        )

    except Exception as e:
        LOGGER.error(f'Error in request_agent_access: {e}')
        await message.answer(
            Text('❌ An error occurred while processing your request.').as_markdown()
        )
        raise


@agent_commands_router.callback_query(
    AgentAccessCallback.filter(), flags={'require_identity': True}
)
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

        creator_telegram_id = await get_agent_creator_telegram_id(agent_id)

        if not creator_telegram_id:
            if CONFIG.admin_ids is None or callback.from_user.id not in CONFIG.admin_ids:
                await callback.answer('❌ Only admins can approve unowned agents')
                LOGGER.warning(
                    f'User {callback.from_user.id} attempted to approve/deny '
                    f'agent access request {request_id} '
                    f'for unowned agent {agent_id} without being admin'
                )
                return
        else:
            if callback.from_user.id != creator_telegram_id:
                await callback.answer('❌ You are not the creator of this assistant')
                LOGGER.warning(
                    f'User {callback.from_user.id} attempted to approve/deny '
                    f'agent access request {request_id} without being creator. '
                    f'Actual creator: {creator_telegram_id}'
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


@agent_commands_router.message(Command('current'), flags={'require_identity': True})
async def assistant_info_handler(
    message: Message, gel_client: AsyncIOExecutor, identity: GetIdentityResult
) -> None:
    """Show assistant info with memory blocks."""
    if not message.from_user:
        return

    if not identity.selected_agent:
        await message.answer(
            Text(
                '❌ No assistant selected. Use /switch to select one.',
            ).as_markdown()
        )
        return

    # Send loading indicator
    status_msg = await message.answer(Text('⏳ Fetching assistant info...').as_markdown())

    try:
        # Fetch agent data
        agent = await client.agents.retrieve(
            identity.selected_agent, include=['agent.blocks', 'agent.tools']
        )

        # Build memory blocks list
        memory_blocks = []
        for block in agent.blocks:
            block_size = len(block.value or '')
            utilization = (
                (block_size / block.limit * 100)
                if block.limit is not None and block.limit > 0
                else 0
            )
            warning = ' ⚠️' if utilization > 100 else ''
            memory_blocks.append(
                Text(
                    f'{block.label}: {block_size}/{block.limit} '
                    f'({utilization:.1f}%){warning}'
                )
            )

        # Build complete message
        message_count = len(agent.message_ids) if agent.message_ids else 0
        tools_count = len(agent.tools) if agent.tools else 0

        content = as_list(
            Text('🤖 ', Bold(agent.name)),
            Text(),  # Empty line
            as_list(
                Text(Bold('ID: '), Code(agent.id)),
                Text(Bold('Model: '), agent.model),
            ),
            Text(),  # Empty line
            Text('📝 ', Bold('Memory Blocks (chars):')),
            as_marked_list(*memory_blocks, marker='  • '),
            Text(),  # Empty line
            Text('💬 ', Bold('Message History: '), f'{message_count} messages'),
            Text('🔧 ', Bold('Tools: '), str(tools_count)),
        )

        # Delete loading message and send result
        await status_msg.delete()
        await message.answer(**content.as_kwargs())

    except Exception as e:
        LOGGER.error(f'Error fetching assistant info: {e}')
        await status_msg.edit_text(Text('❌ Error fetching assistant info').as_markdown())


@agent_commands_router.message(Command('context'), flags={'require_identity': True})
async def context_handler(
    message: Message, gel_client: AsyncIOExecutor, identity: GetIdentityResult
) -> None:
    """Show assistant context window breakdown."""
    if not message.from_user:
        return

    if not identity.selected_agent:
        await message.answer(
            Text('❌ No assistant selected. Use /switch to select one.').as_markdown()
        )
        return

    # Send loading indicator
    status_msg = await message.answer(Text('⏳ Fetching context info...').as_markdown())

    try:
        # Fetch context window overview
        context = await context_window_overview(client, identity.selected_agent)

        # Calculate context window usage
        current = context.context_window_size_current
        max_size = context.context_window_size_max
        ctx_percentage = (current / max_size * 100) if max_size > 0 else 0
        warning = ' ⚠️' if ctx_percentage > 100 else ''

        # Build component breakdown list
        components = [
            ('System instruction', context.num_tokens_system),
            ('Tool description', context.num_tokens_functions_definitions),
            ('External summary', context.num_tokens_external_memory_summary),
            ('Core memory', context.num_tokens_core_memory),
            ('Recursive Memory', context.num_tokens_summary_memory),
            ('Messages', context.num_tokens_messages),
        ]

        component_items = []
        for name, tokens in components:
            percentage = (tokens / max_size * 100) if max_size > 0 else 0
            component_items.append(Text(f'{name}: {tokens} ({percentage:.1f}%)'))

        # Build complete message
        content = as_list(
            Text(
                '🪟 ',
                Bold('Context Window: '),
                f'{current}/{max_size} tokens ({ctx_percentage:.1f}%){warning}',
            ),
            Text(),  # Empty line
            Text(Bold('Context Breakdown (tokens):')),
            as_marked_list(*component_items, marker='  • '),
        )

        # Delete loading message and send result
        await status_msg.delete()
        await message.answer(**content.as_kwargs())

    except Exception as e:
        LOGGER.error(f'Error fetching context info: {e}')
        await status_msg.edit_text(Text('❌ Error fetching context info').as_markdown())


@agent_router.message(flags={'require_identity': True})
async def message_handler(
    message: Message, bot: Bot, gel_client: AsyncIOExecutor, identity: GetIdentityResult
) -> None:
    if not message.from_user:
        return

    # Build message content layer by layer
    parts: list[str] = []

    # Layer 1: Reply context (quote takes priority over full reply)
    if message.quote:
        # User quoted a specific part of the message
        parts.append(f'<quote>{message.quote.text}</quote>')
    elif message.reply_to_message:
        # Full reply without specific quote
        reply = message.reply_to_message
        if reply.text:
            preview = reply.text[:100] + ('...' if len(reply.text) > 100 else '')
            parts.append(f'<reply_to>{preview}</reply_to>')

    # Layer 2: Text content
    if message.text:
        parts.append(message.text)

    # Layer 3: Caption (for media messages)
    if message.caption:
        parts.append(f'<caption>{message.caption}</caption>')

    # Layer 4: Audio transcription
    if message.voice or message.audio:
        transcription_service = get_transcription_service()
        if transcription_service is None:
            await message.answer(
                Text('Audio not supported. OpenAI API key not configured.').as_markdown()
            )
            return

        tag = 'voice_transcript' if message.voice else 'audio_transcript'
        try:
            transcript = await transcription_service.transcribe_message_content(
                bot, message
            )
            parts.append(f'<{tag}>{transcript}</{tag}>')
        except TranscriptionError as e:
            LOGGER.warning(
                '%s failed: %s, telegram_id=%s',
                tag,
                e,
                message.from_user.id,
            )
            parts.append(f'<{tag}_error>{e}</{tag}_error>')

    # Unsupported content types
    if message.video:
        await message.answer(Text('Video content is not supported').as_markdown())
    if message.photo or message.sticker:
        await message.answer(
            Text('Photos and stickers are not yet supported, but will be').as_markdown()
        )

    # Combine all parts
    message_text = '\n\n'.join(parts) if parts else None

    if not message_text:
        await message.answer(
            Text(
                'No supported content provided, I hope to hear more from you'
            ).as_markdown()
        )
        return

    # Get or auto-select agent
    if not identity.selected_agent:
        try:
            agent_id = await get_default_agent(identity.identity_id)
            await set_selected_agent_query(
                gel_client, identity_id=identity.identity_id, agent_id=agent_id
            )
        except IndexError:
            await message.answer(
                Text('You have no assistants yet. Use /newassistant').as_markdown()
            )
            return
    else:
        agent_id = identity.selected_agent

        # Validate that the selected agent still belongs to the identity
        agent_identity_ids = await get_agent_identity_ids(agent_id)
        if identity.identity_id not in agent_identity_ids:
            LOGGER.warning(
                f'Selected agent {agent_id} no longer belongs to identity '
                f'{identity.identity_id}. Auto-selecting new agent.'
            )
            # Reset and try to get the default agent
            try:
                agent_id = await get_default_agent(identity.identity_id)
                await set_selected_agent_query(
                    gel_client, identity_id=identity.identity_id, agent_id=agent_id
                )
            except IndexError:
                # No agents left - reset selected_agent to NULL
                await reset_selected_agent_query(
                    gel_client, identity_id=identity.identity_id
                )
                await message.answer(
                    Text('You have no assistants yet. Use /newassistant').as_markdown()
                )
                return

    # Should I let agent know that message came through telegram?
    request = [{'type': 'text', 'text': message_text}]

    try:
        async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
            response_stream = await client.agents.messages.create(
                agent_id=agent_id,
                messages=[{'role': 'user', 'content': request}],  # type: ignore
                include_pings=True,
                streaming=True,
            )

            handler = AgentStreamHandler(message)

            async for event in response_stream:  # type: ignore[union-attr]
                try:
                    await handler.handle_event(event)
                except Exception as e:
                    LOGGER.error(
                        'Stream event error: %s, tg_id=%s, agent=%s',
                        e,
                        message.from_user.id,
                        agent_id,
                    )
                    continue

    except ReadTimeout:
        # If we timeout, it means Letta stopped sending data (no pings, no response)
        # This indicates a server-side failure, not a slow agent
        LOGGER.error(
            'Letta API stopped responding for user %s (agent_id: %s) - '
            'no data received for 120s (expected pings every ~30s)',
            message.from_user.id if message.from_user else 'unknown',
            agent_id,
        )
        await message.answer(
            Text(
                '❌ The agent service stopped responding. '
                'This may be a temporary issue with Letta API. '
                'Please try again in a moment.'
            ).as_markdown()
        )

    except APIError as e:
        LOGGER.error(
            'Letta API error: status=%s, body=%s, type=%s, telegram_id=%s, agent_id=%s',
            getattr(e, 'status_code', 'unknown'),
            getattr(e, 'body', 'no body'),
            type(e).__name__,
            message.from_user.id,
            agent_id,
        )
        await message.answer(Text('Error communicating with assistant').as_markdown())
        raise

    except Exception:
        LOGGER.exception(
            'Message handler error: telegram_id=%s, agent_id=%s',
            message.from_user.id,
            agent_id,
        )
        await message.answer(Text('An unexpected error occurred').as_markdown())
        raise
