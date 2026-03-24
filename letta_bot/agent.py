import asyncio
from dataclasses import dataclass, field
import json
import logging

from aiogram import Bot, F, Router
from aiogram.filters.callback_data import CallbackData
from aiogram.filters.command import Command
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from aiogram.utils.chat_action import ChatActionSender
from aiogram.utils.formatting import Bold, Code, Text, as_list, as_marked_list
from aiogram.utils.keyboard import InlineKeyboardBuilder
from gel import AsyncIOExecutor
from httpx import ReadError, ReadTimeout, RemoteProtocolError
from letta_client import APIError

from letta_bot.client import (
    DetachResult,
    LettaProcessingError,
    client,
    detach_user_from_agent,
    list_agents_by_user,
    validate_agent_access,
)
from letta_bot.client_tools import LettaMessage, registry, resolve_approval
from letta_bot.documents import (
    DocumentProcessingError,
    FileTooLargeError,
    file_processing_tracker,
    process_telegram_document,
    wait_for_file_processing,
)
from letta_bot.images import (
    ContentPart,
    ImageContentPart,
    ImageProcessingError,
    TextContentPart,
    process_telegram_image,
)
from letta_bot.letta_sdk_extensions import context_window_overview
from letta_bot.queries.get_identity_async_edgeql import GetIdentityResult
from letta_bot.queries.reset_selected_agent_async_edgeql import (
    reset_selected_agent as reset_selected_agent_query,
)
from letta_bot.queries.set_selected_agent_async_edgeql import (
    set_selected_agent as set_selected_agent_query,
)
from letta_bot.response_handler import AgentStreamHandler
from letta_bot.transcription import TranscriptionError, get_transcription_service

LOGGER = logging.getLogger(__name__)

agent_commands_router = Router(name=f'{__name__}.commands')
agent_router = Router(name=f'{__name__}.messaging')


# =============================================================================
# Message Context Building (Helper Functions)
# =============================================================================


@dataclass
class MessageContext:
    """Accumulates message parts for Letta API request."""

    text_parts: list[str] = field(default_factory=list)
    image_parts: list[ImageContentPart] = field(default_factory=list)

    def add_text(self, text: str) -> None:
        """Add text part to context."""
        self.text_parts.append(text)

    def prepend_text(self, text: str) -> None:
        """Insert text part at the beginning of context."""
        self.text_parts.insert(0, text)

    def add_image(self, image: ImageContentPart) -> None:
        """Add image content part to context."""
        self.image_parts.append(image)

    def build_content_parts(self) -> list[ContentPart]:
        """Build final content parts list for Letta API.

        Order: images first, then combined text (per Letta API spec).
        Returns empty list if no content.
        """
        parts: list[ContentPart] = []

        # Images first (per Letta multimodal spec)
        parts.extend(self.image_parts)

        # Combine all text parts
        if self.text_parts:
            combined_text = '\n\n'.join(self.text_parts)
            text_part: TextContentPart = {'type': 'text', 'text': combined_text}
            parts.append(text_part)

        return parts

    def has_content(self) -> bool:
        """Check if context has any content."""
        return bool(self.text_parts) or bool(self.image_parts)


def build_message_metadata(message: Message) -> str:
    """Build metadata tag for message context.

    Args:
        message: Telegram message

    Returns:
        Formatted metadata XML tag, empty string if no user
    """
    user = message.from_user
    if not user:
        return ''

    day_name = message.date.strftime('%A')
    date_str = message.date.strftime('%B %d')
    time_str = message.date.strftime('%H:%M')

    return (
        f'<metadata>Message received via Telegram from {user.first_name}'
        f' on {day_name}, {date_str} at {time_str} UTC.</metadata>'
    )


def build_reply_context(message: Message) -> str | None:
    """Build reply/quote context if present.

    Args:
        message: Telegram message

    Returns:
        Formatted reply context or None if no reply
    """
    # Quote takes priority (user quoted specific text)
    if message.quote:
        return f'<quote>{message.quote.text}</quote>'

    # Full reply without specific quote
    if message.reply_to_message:
        reply_text = (
            message.reply_to_message.text
            or message.reply_to_message.caption
            or message.text  # need for photo and sticker
        )
        if reply_text:
            preview = reply_text[:100] + ('...' if len(reply_text) > 100 else '')
            if message.reply_to_message.photo:
                file_id = message.reply_to_message.photo[-1].file_id
                file_tag = f'<photo>file_id={file_id}</photo>'
            elif message.reply_to_message.sticker:
                file_id = message.reply_to_message.sticker.file_id
                file_tag = f'<sticker>file_id={file_id}</sticker>'
            else:
                file_tag = ''
            return f'<reply>{file_tag}{preview}</reply>'

    return None


def build_caption(message: Message) -> str | None:
    """Build caption tag if present.

    Args:
        message: Telegram message

    Returns:
        Formatted caption or None
    """
    if message.caption:
        return f'<caption>{message.caption}</caption>'
    return None


def init_message_context(message: Message) -> MessageContext:
    """Initialize MessageContext with standard layers.

    Adds:
    - Layer 0: Metadata
    - Layer 1: Reply context (if present)

    Args:
        message: Telegram message

    Returns:
        Initialized MessageContext
    """
    ctx = MessageContext()

    # Layer 0: Metadata (always present)
    metadata = build_message_metadata(message)
    if metadata:
        ctx.add_text(metadata)

    # Layer 1: Reply context (optional)
    reply_ctx = build_reply_context(message)
    if reply_ctx:
        ctx.add_text(reply_ctx)

    return ctx


# =============================================================================
# Agent Communication (Shared Logic)
# =============================================================================


async def send_to_agent(
    message: Message,
    bot: Bot,
    agent_id: str,
    content_parts: list[ContentPart],
) -> None:
    """Send message to agent and stream response.

    Supports an approval loop: if the agent requests client-side tool
    execution, the bot processes the tool, sends the result back, and
    continues streaming until the agent produces a final response or
    the iteration limit is reached.

    Args:
        message: Original Telegram message (for replies)
        bot: Aiogram Bot instance
        agent_id: Letta agent ID
        content_parts: Content parts for Letta API

    Raises:
        Re-raises exceptions after logging and notifying user
    """
    max_approval_iterations = 10

    assert message.from_user, 'from_user required (guaranteed by IdentityMiddleware)'

    schemas = registry.get_schemas()
    client_tools = schemas or None

    messages_to_send: list[LettaMessage] = [
        {'role': 'user', 'content': content_parts},
    ]

    handler: AgentStreamHandler | None = None

    LOGGER.debug(
        'send_to_agent: agent=%s, tg_id=%d, parts=%d',
        agent_id,
        message.from_user.id,
        len(content_parts),
    )

    try:
        async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
            for _iteration in range(max_approval_iterations):
                handler = AgentStreamHandler(message)

                response_stream = await client.agents.messages.stream(
                    agent_id=agent_id,
                    messages=messages_to_send,  # type: ignore[arg-type]
                    include_pings=True,
                    client_tools=client_tools,
                )

                async for event in response_stream:
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

                # No approval request — agent finished
                if handler.approval_request is None:
                    LOGGER.debug(
                        'send_to_agent: done agent=%s, tg_id=%d',
                        agent_id,
                        message.from_user.id,
                    )
                    return

                # Process approval request and continue loop
                messages_to_send = await resolve_approval(handler.approval_request, message)

            # Max iterations exceeded
            LOGGER.warning(
                'Max approval iterations (%d) exceeded, tg_id=%s, agent_id=%s',
                max_approval_iterations,
                message.from_user.id,
                agent_id,
            )

    except (ReadError, ReadTimeout, RemoteProtocolError) as e:
        LOGGER.error(
            'Letta API connection lost: %s, telegram_id=%s, agent_id=%s',
            e,
            message.from_user.id,
            agent_id,
        )

        if handler is not None:
            await handler.cleanup_ping()

        if handler is not None and handler.has_assistant_message:
            await message.answer(
                **Text('⚠️ Connection interrupted — response may be incomplete.').as_kwargs()
            )
        else:
            await message.answer(
                **Text(
                    '❌ The assistant service stopped responding. '
                    'Please try again in a moment.'
                ).as_kwargs()
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
        await message.answer(**Text('Error communicating with assistant').as_kwargs())
        raise

    except Exception:
        LOGGER.exception(
            'Message handler error: telegram_id=%s, agent_id=%s',
            message.from_user.id,
            agent_id,
        )
        await message.answer(**Text('An unexpected error occurred').as_kwargs())
        raise


class SwitchAssistantCallback(CallbackData, prefix='switch'):
    agent_id: str


class ClearMessagesCallback(CallbackData, prefix='clear'):
    confirm: bool


class ExportAgentCallback(CallbackData, prefix='export'):
    # NOTE: Telegram callback_data limit is 64 bytes.
    # prefix 'export:' (7) + agent UUID (~44) fits, but may break if ID format grows.
    agent_id: str


class DetachSelectCallback(CallbackData, prefix='detach_s'):
    agent_id: str


class DetachConfirmCallback(CallbackData, prefix='detach_c'):
    agent_id: str
    confirm: bool


@agent_commands_router.message(Command('switch'), flags={'require_identity': True})
async def switch(message: Message, identity: GetIdentityResult) -> None:
    """List user's assistants and allow switching between them."""
    if not message.from_user:
        return

    # List all agents for this user (via identity tags)
    try:
        # Collect ALL agents across all pages
        all_agents = []
        async for agent in list_agents_by_user(message.from_user.id):
            all_agents.append(agent)

        if not all_agents:
            await message.answer(
                **Text(
                    "You don't have any assistants yet. Use /new to request one."
                ).as_kwargs()
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
            **Text('Select an assistant:').as_kwargs(),
            reply_markup=builder.as_markup(),
        )

    except APIError as e:
        LOGGER.error(f'Error listing agents for user {message.from_user.id}: {e}')
        await message.answer(**Text('Error retrieving your assistants').as_kwargs())


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

    # Fetch all user's agents first (used for validation and keyboard rebuild)
    try:
        all_agents = [agent async for agent in list_agents_by_user(callback.from_user.id)]
    except APIError as e:
        LOGGER.error(f'Error listing agents for user {callback.from_user.id}: {e}')
        await callback.answer('❌ Error retrieving assistants')
        return

    # Validate user has access to the requested agent
    valid_ids = {agent.id for agent in all_agents}
    if callback_data.agent_id not in valid_ids:
        await callback.answer('❌ Assistant not available')
        return

    # Update selected agent in database
    await set_selected_agent_query(
        gel_client, telegram_id=callback.from_user.id, agent_id=callback_data.agent_id
    )

    # Rebuild keyboard with updated selection (using already fetched agents)
    builder = InlineKeyboardBuilder()
    for agent in all_agents:
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

    # Toast notification for success
    await callback.answer('✅ Assistant switched')


@agent_commands_router.message(
    Command('current'), flags={'require_identity': True, 'require_agent': True}
)
async def assistant_info_handler(message: Message, agent_id: str) -> None:
    """Show assistant info with memory blocks."""
    if not message.from_user:
        return

    # Send loading indicator
    status_msg = await message.answer(**Text('⏳ Fetching assistant info...').as_kwargs())

    try:
        # Fetch agent data
        agent = await client.agents.retrieve(
            agent_id, include=['agent.blocks', 'agent.tools']
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

        memory_section = (
            as_marked_list(*memory_blocks, marker='  • ')
            if memory_blocks
            else Text('  No memory blocks')
        )

        content = as_list(
            Text('🤖 ', Bold(agent.name)),
            Text(),  # Empty line
            as_list(
                Text(Bold('ID: '), Code(agent.id)),
                Text(Bold('Model: '), agent.model),
            ),
            Text(),  # Empty line
            Text('📝 ', Bold('Memory Blocks (chars):')),
            memory_section,
            Text(),  # Empty line
            Text('💬 ', Bold('Message History: '), f'{message_count} messages'),
            Text('🔧 ', Bold('Tools: '), str(tools_count)),
            Text(),  # Empty line
            Text('📤 ', 'Share to let others request access:'),
            Text('    ', Code(f'/attach {agent.id}')),
        )

        # Delete loading message and send result
        await status_msg.delete()
        await message.answer(**content.as_kwargs())

    except Exception as e:
        LOGGER.error(f'Error fetching assistant info: {e}')
        await status_msg.edit_text(**Text('❌ Error fetching assistant info').as_kwargs())


@agent_commands_router.message(
    Command('context'), flags={'require_identity': True, 'require_agent': True}
)
async def context_handler(message: Message, agent_id: str) -> None:
    """Show assistant context window breakdown."""
    if not message.from_user:
        return

    # Send loading indicator
    status_msg = await message.answer(**Text('⏳ Fetching context info...').as_kwargs())

    try:
        # Fetch context window overview
        context = await context_window_overview(client, agent_id)

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
        await status_msg.edit_text(**Text('❌ Error fetching context info').as_kwargs())


@agent_commands_router.message(
    Command('clear'), flags={'require_identity': True, 'require_agent': True}
)
async def clear_messages(message: Message, agent_id: str) -> None:
    """Show confirmation prompt for clearing message history."""
    if not message.from_user:
        return

    try:
        agent = await client.agents.retrieve(agent_id)

        builder = InlineKeyboardBuilder()
        builder.button(
            text='❌ Cancel',
            callback_data=ClearMessagesCallback(confirm=False).pack(),
        )
        builder.button(
            text='🗑️ Clear',
            callback_data=ClearMessagesCallback(confirm=True).pack(),
        )
        builder.adjust(2)

        await message.answer(
            **Text(
                '🤖 ',
                Bold(agent.name),
                '\n\n',
                '⚠️ Clear context messages?\n\n',
                "This won't affect memory or message history.",
            ).as_kwargs(),
            reply_markup=builder.as_markup(),
        )

    except APIError as e:
        LOGGER.error(f'Error retrieving agent {agent_id}: {e}')
        await message.answer(**Text('❌ Error retrieving assistant info').as_kwargs())


@agent_commands_router.callback_query(
    ClearMessagesCallback.filter(), flags={'require_identity': True, 'require_agent': True}
)
async def handle_clear_messages(
    callback: CallbackQuery,
    callback_data: ClearMessagesCallback,
    agent_id: str,
) -> None:
    """Handle message history clearing confirmation."""
    if not callback.from_user or not callback.message:
        return

    if not callback_data.confirm:
        if isinstance(callback.message, Message):
            await callback.message.delete()
        await callback.answer()
        return

    try:
        await client.agents.messages.reset(agent_id=agent_id)

        if isinstance(callback.message, Message):
            await callback.message.edit_text(
                **Text('✅ Message history cleared').as_kwargs()
            )

        await callback.answer('✅ Cleared')

    except APIError as e:
        LOGGER.error(f'Error clearing messages for agent {agent_id}: {e}')
        await callback.answer('❌ Error clearing messages')


async def _perform_export(
    message: Message,
    agent_id: str,
    status_msg: Message | None = None,
) -> None:
    """Download and send agent .af file to user."""
    assert message.from_user, 'from_user required'

    if status_msg is None:
        status_msg = await message.answer(**Text('⏳ Exporting assistant...').as_kwargs())

    try:
        agent_file_content = await client.agents.export_file(agent_id=agent_id)
        # .af format assumption: {"agents": [{"name": ...}, ...]}
        # Falls back to agent_id if structure changes.
        agent_data = json.loads(agent_file_content)
        agents = agent_data.get('agents', [])
        agent_name = agents[0].get('name', agent_id) if agents else agent_id

        safe_name = agent_name.replace('/', '_').replace('\\', '_').replace(' ', '_')
        filename = f'{safe_name}.af'

        data = agent_file_content.encode('utf-8')
        document = BufferedInputFile(file=data, filename=filename)

        await status_msg.delete()
        await message.answer_document(
            document=document,
            caption=f'📦 Agent export: {agent_name}',
        )

    except Exception as e:
        LOGGER.error(
            'Error exporting agent %s for user %s: %s',
            agent_id,
            message.from_user.id,
            e,
        )
        await status_msg.edit_text(**Text('❌ Error exporting assistant').as_kwargs())


@agent_commands_router.message(Command('export'))
async def export_agent(message: Message) -> None:
    """Export assistants as portable .af files."""
    assert message.from_user, 'from_user required'

    telegram_id = message.from_user.id
    agents = [agent async for agent in list_agents_by_user(telegram_id)]

    if not agents:
        await message.answer(**Text('You have no assistants to export.').as_kwargs())
        return

    if len(agents) == 1:
        await _perform_export(message, agents[0].id)
        return

    builder = InlineKeyboardBuilder()
    for agent in agents:
        builder.button(
            text=agent.name,
            callback_data=ExportAgentCallback(agent_id=agent.id).pack(),
        )
    builder.adjust(1)

    await message.answer(
        **Text('Select an assistant to export:').as_kwargs(),
        reply_markup=builder.as_markup(),
    )


@agent_commands_router.callback_query(ExportAgentCallback.filter())
async def handle_export_agent(
    callback: CallbackQuery,
    callback_data: ExportAgentCallback,
) -> None:
    """Handle export agent selection callback."""
    assert callback.from_user, 'from_user required'

    telegram_id = callback.from_user.id
    agent_id = callback_data.agent_id
    identity_tag = f'identity-tg-{telegram_id}'
    try:
        agent = await client.agents.retrieve(agent_id=agent_id, include=['agent.tags'])
    except APIError:
        await callback.answer('❌ Assistant not found')
        return

    if not agent.tags or identity_tag not in agent.tags:
        await callback.answer('❌ Assistant not available')
        return

    await callback.answer()

    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            **Text(f'⏳ Exporting {agent.name}...').as_kwargs()
        )
        await _perform_export(callback.message, agent_id, status_msg=callback.message)


@agent_commands_router.message(Command('detach'), flags={'require_identity': True})
async def detach(message: Message) -> None:
    """List user's assistants for detach selection."""
    assert message.from_user, 'from_user required'

    agents = [agent async for agent in list_agents_by_user(message.from_user.id)]

    if not agents:
        await message.answer(**Text("You don't have any assistants.").as_kwargs())
        return

    builder = InlineKeyboardBuilder()
    for agent in agents:
        builder.button(
            text=agent.name,
            callback_data=DetachSelectCallback(agent_id=agent.id).pack(),
        )
    builder.adjust(1)

    await message.answer(
        **Text('Select an assistant to detach from:').as_kwargs(),
        reply_markup=builder.as_markup(),
    )


@agent_commands_router.callback_query(
    DetachSelectCallback.filter(), flags={'require_identity': True}
)
async def handle_detach_select(
    callback: CallbackQuery,
    callback_data: DetachSelectCallback,
) -> None:
    """Validate detach and show confirmation prompt."""
    assert callback.from_user, 'from_user required'

    telegram_id = callback.from_user.id
    agent_id = callback_data.agent_id

    agent = await validate_agent_access(agent_id, telegram_id)
    if agent is None:
        await callback.answer('❌ Assistant not available')
        return

    # Check if last user (using tags already fetched by validate_agent_access)
    identity_count = sum(1 for t in (agent.tags or []) if t.startswith('identity-tg-'))
    if identity_count <= 1:
        await callback.answer(
            '❌ Cannot detach: you are the last user on this assistant', show_alert=True
        )
        return

    # Check ownership for warning
    owner_tag = f'owner-tg-{telegram_id}'
    is_owner = agent.tags is not None and owner_tag in agent.tags

    warning = (
        '\n\n⚠️ You are the owner. Ownership will be transferred to another user.'
        if is_owner
        else ''
    )

    builder = InlineKeyboardBuilder()
    builder.button(
        text='❌ Cancel',
        callback_data=DetachConfirmCallback(agent_id=agent_id, confirm=False).pack(),
    )
    builder.button(
        text='🔓 Detach',
        callback_data=DetachConfirmCallback(agent_id=agent_id, confirm=True).pack(),
    )
    builder.adjust(2)

    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            **Text(
                'Detach from ',
                Bold(agent.name),
                '?',
                warning,
            ).as_kwargs(),
            reply_markup=builder.as_markup(),
        )

    await callback.answer()


@agent_commands_router.callback_query(
    DetachConfirmCallback.filter(), flags={'require_identity': True}
)
async def handle_detach_confirm(
    callback: CallbackQuery,
    callback_data: DetachConfirmCallback,
    identity: GetIdentityResult,
    gel_client: AsyncIOExecutor,
    bot: Bot,
) -> None:
    """Handle detach confirmation."""
    assert callback.from_user, 'from_user required'

    if not callback_data.confirm:
        if isinstance(callback.message, Message):
            await callback.message.edit_text(**Text('Cancelled.').as_kwargs())
        await callback.answer()
        return

    try:
        result: DetachResult = await detach_user_from_agent(
            callback_data.agent_id, callback.from_user.id
        )
    except ValueError as e:
        await callback.answer(f'❌ {e}', show_alert=True)
        return

    # Reset selected_agent if detached agent was selected
    if identity.selected_agent == callback_data.agent_id:
        await reset_selected_agent_query(gel_client, telegram_id=callback.from_user.id)

    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            **Text('✅ Detached from ', Bold(result.agent_name)).as_kwargs()
        )

    await callback.answer('✅ Detached')

    # Notify new owner if ownership was transferred
    if result.was_owner and result.new_owner_telegram_id is not None:
        await bot.send_message(
            result.new_owner_telegram_id,
            **Text(
                '👑 You are now the owner of ',
                Bold(result.agent_name),
                '\n\n',
                'Use /switch to select this assistant.',
            ).as_kwargs(),
        )


# =============================================================================
# Content Type Handlers
# IMPORTANT: Registration order matters - first match wins in aiogram!
# Specific content filters must come before catch-all.
# =============================================================================


@agent_router.message(F.document, flags={'require_identity': True, 'require_agent': True})
async def handle_document(message: Message, bot: Bot, agent_id: str) -> None:
    """Handle document uploads with per-user concurrency control."""
    assert message.from_user, 'from_user required (guaranteed by IdentityMiddleware)'
    assert message.document, 'document required (guaranteed by F.document filter)'

    user_id = message.from_user.id
    ctx = init_message_context(message)

    # Add caption if present (before document processing)
    caption = build_caption(message)
    if caption:
        ctx.add_text(caption)

    async with file_processing_tracker.acquire(user_id) as acquired:
        if not acquired:
            await message.answer(
                **Text('📄 Wait for the previous file to finish processing.').as_kwargs()
            )
            return

        try:
            file_name = message.document.file_name or 'document'
            status_msg = await message.answer(
                **Text(f'📄 Uploading "{file_name}"...').as_kwargs()
            )

            result = await process_telegram_document(
                bot, message.document, agent_id, user_id
            )
            # Wait for Letta to process the file
            await wait_for_file_processing(result['folder_id'], result['file_id'])

            file_name = result['file_name']
            file_id = result['file_id']

            # Update status message to show upload complete
            await status_msg.edit_text(**Text(f'✅ Uploaded "{file_name}"').as_kwargs())

            ctx.add_text(f'<system>File "{file_name}" ready (id: {file_id})</system>')

        except FileTooLargeError as e:
            await message.answer(**Text(f'📄 {e}').as_kwargs())
            return

        except (DocumentProcessingError, LettaProcessingError) as e:
            LOGGER.warning('Document processing failed: %s, telegram_id=%s', e, user_id)
            ctx.add_text(f'<system>File error: {e}</system>')

        except APIError as e:
            status = getattr(e, 'status_code', 'unknown')
            body = getattr(e, 'body', 'no body')
            LOGGER.warning(
                'Document processing failed: status=%s, body=%s, telegram_id=%s',
                status,
                body,
                user_id,
            )
            ctx.add_text(f'<system>File error: status={status}, body={body}</system>')

    # Send to agent if we have content
    content_parts = ctx.build_content_parts()
    if content_parts:
        await send_to_agent(message, bot, agent_id, content_parts)


@agent_router.message(F.photo, flags={'require_identity': True, 'require_agent': True})
async def handle_album(
    message: Message,
    bot: Bot,
    agent_id: str,
    photos: list[Message],
) -> None:
    """Handle photo album (single photo is treated as 1-photo album).

    Args:
        message: First message in the batch
        bot: Aiogram Bot instance
        agent_id: Letta agent ID
        photos: Injected by PhotoBufferMiddleware (always present)
    """
    assert message.from_user, 'from_user required (guaranteed by IdentityMiddleware)'

    ctx = init_message_context(message)

    # Caption: take from first message with caption
    for m in photos:
        caption = build_caption(m)
        if caption:
            ctx.add_text(caption)
            break

    # Process all photos in parallel (photo guaranteed by F.photo filter + buffer)
    tasks = [process_telegram_image(bot, m.photo[-1]) for m in photos if m.photo]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Add successful results, log errors
    successful_count = 0
    for i, result in enumerate(results):
        if isinstance(result, BaseException):
            LOGGER.warning(
                'Photo %d processing failed: %s, telegram_id=%s',
                i + 1,
                result,
                message.from_user.id,
            )
        else:
            ctx.add_image(result)
            successful_count += 1

    # If all images failed, add error context
    if successful_count == 0 and results:
        ctx.prepend_text(
            '<image-processing-error>Failed to process all images</image-processing-error>'
        )

    # Add file_id annotations for agent to reference via client tools
    file_ids = [m.photo[-1].file_id for m in photos if m.photo]
    if file_ids:
        photos_tags = ''.join(f'<photo>file_id={fid}</photo>' for fid in file_ids)
        ctx.add_text(f'<photos>{photos_tags}</photos>')

    # Send to agent
    content_parts = ctx.build_content_parts()
    if content_parts:
        await send_to_agent(message, bot, agent_id, content_parts)


@agent_router.message(
    F.voice | F.audio, flags={'require_identity': True, 'require_agent': True}
)
async def handle_audio(message: Message, bot: Bot, agent_id: str) -> None:
    """Handle voice messages and audio files with transcription."""
    assert message.from_user, 'from_user required (guaranteed by IdentityMiddleware)'
    transcription_service = get_transcription_service()
    if transcription_service is None:
        await message.answer(
            **Text('Audio transcription not available. No API key configured.').as_kwargs()
        )
        return

    ctx = init_message_context(message)

    # Add caption if present (audio files can have captions)
    caption = build_caption(message)
    if caption:
        ctx.add_text(caption)

    # Determine tag based on content type
    tag = 'voice-transcript' if message.voice else 'audio-transcript'

    try:
        transcript = await transcription_service.transcribe_message_content(bot, message)
        ctx.add_text(f'<{tag}>{transcript}</{tag}>')
    except TranscriptionError as e:
        LOGGER.warning(
            '%s failed: %s, telegram_id=%s',
            tag,
            e,
            message.from_user.id,
        )
        ctx.add_text(f'<{tag}-error>{e}</{tag}-error>')

    # Send to agent
    content_parts = ctx.build_content_parts()
    if content_parts:
        await send_to_agent(message, bot, agent_id, content_parts)


@agent_router.message(F.video, flags={'require_identity': True, 'require_agent': True})
async def handle_video(message: Message) -> None:
    """Notify user that video is not supported."""
    await message.answer(**Text('Video content is not supported').as_kwargs())


@agent_router.message(
    F.sticker & ~F.sticker.is_animated & ~F.sticker.is_video,
    flags={'require_identity': True, 'require_agent': True},
)
async def handle_regular_sticker(message: Message, bot: Bot, agent_id: str) -> None:
    """Handle regular (static) stickers as images."""
    assert message.from_user, 'from_user required (guaranteed by IdentityMiddleware)'
    assert message.sticker, 'sticker required (guaranteed by F.sticker filter)'

    ctx = init_message_context(message)

    # Process sticker as image
    try:
        image_part = await process_telegram_image(bot, message.sticker)
        ctx.add_image(image_part)
        ctx.add_text(f'<sticker>file_id={message.sticker.file_id}</sticker>')
    except ImageProcessingError as e:
        LOGGER.warning(
            'Sticker processing failed: %s, telegram_id=%s',
            e,
            message.from_user.id,
        )
        ctx.prepend_text(f'<sticker-processing-error>{e}</sticker-processing-error>')

    # Send to agent
    content_parts = ctx.build_content_parts()
    if content_parts:
        await send_to_agent(message, bot, agent_id, content_parts)


@agent_router.message(
    F.sticker & (F.sticker.is_animated | F.sticker.is_video),
    flags={'require_identity': True, 'require_agent': True},
)
async def handle_animated_sticker(message: Message) -> None:
    """Notify user that animated/video stickers are not supported."""
    await message.answer(
        **Text('Animated and video stickers are not supported').as_kwargs()
    )


@agent_router.message(flags={'require_identity': True, 'require_agent': True})
async def handle_text(message: Message, bot: Bot, agent_id: str) -> None:
    """Handle text messages (catch-all handler).

    This handler must be registered LAST as it has no content type filter.
    """
    assert message.from_user, 'from_user required (guaranteed by middleware)'
    LOGGER.debug(
        'handle_text: tg_id=%d, agent=%s',
        message.from_user.id,
        agent_id,
    )
    ctx = init_message_context(message)

    # Add text content
    if message.text:
        ctx.add_text(message.text)

    # Send to agent
    content_parts = ctx.build_content_parts()
    if content_parts:
        await send_to_agent(message, bot, agent_id, content_parts)
    else:
        await message.answer(
            **Text(
                'No supported content provided, I hope to hear more from you'
            ).as_kwargs()
        )
