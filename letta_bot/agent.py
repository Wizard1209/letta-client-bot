import logging

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

from letta_bot.client import client, get_agent_identity_ids, get_default_agent
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


class SwitchAssistantCallback(CallbackData, prefix='switch'):
    agent_id: str


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
                    "You don't have any assistants yet. Use /new to request one."
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
            await message.answer(Text('You have no assistants yet. Use /new').as_markdown())
            return
    else:
        agent_id = identity.selected_agent

        # Validate that the selected agent still belongs to the identity
        if identity.identity_id not in await get_agent_identity_ids(agent_id):
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
                    Text('You have no assistants yet. Use /new').as_markdown()
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
