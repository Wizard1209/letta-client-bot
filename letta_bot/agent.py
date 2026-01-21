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

from letta_bot.client import LettaProcessingError, client
from letta_bot.documents import (
    DocumentProcessingError,
    FileTooLargeError,
    file_processing_tracker,
    process_telegram_document,
    wait_for_file_processing,
)
from letta_bot.images import (
    ContentPart,
    ImageProcessingError,
    TextContentPart,
    process_telegram_photo,
)
from letta_bot.letta_sdk_extensions import context_window_overview
from letta_bot.queries.get_identity_async_edgeql import GetIdentityResult
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
        LOGGER.error(f'Error listing agents for identity {identity.identity_id}: {e}')
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


@agent_router.message(flags={'require_identity': True, 'require_agent': True})
async def message_handler(message: Message, bot: Bot, agent_id: str) -> None:
    if not message.from_user:
        return

    # Build text content layer by layer
    text_parts: list[str] = []

    # Layer 1: Reply context (quote takes priority over full reply)
    if message.quote:
        # User quoted a specific part of the message
        text_parts.append(f'<quote>{message.quote.text}</quote>')
    elif message.reply_to_message:
        # Full reply without specific quote
        reply = message.reply_to_message
        if reply.text:
            preview = reply.text[:100] + ('...' if len(reply.text) > 100 else '')
            text_parts.append(f'<reply_to>{preview}</reply_to>')

    # Layer 2: Text content
    if message.text:
        text_parts.append(message.text)

    # Layer 3: Caption (for media messages)
    if message.caption:
        text_parts.append(f'<caption>{message.caption}</caption>')

    # Layer 4: Audio transcription
    if message.voice or message.audio:
        transcription_service = get_transcription_service()
        if transcription_service is None:
            await message.answer(
                **Text('Audio not supported. OpenAI API key not configured.').as_kwargs()
            )
            return

        tag = 'voice_transcript' if message.voice else 'audio_transcript'
        try:
            transcript = await transcription_service.transcribe_message_content(
                bot, message
            )
            text_parts.append(f'<{tag}>{transcript}</{tag}>')
        except TranscriptionError as e:
            LOGGER.warning(
                '%s failed: %s, telegram_id=%s',
                tag,
                e,
                message.from_user.id,
            )
            text_parts.append(f'<{tag}_error>{e}</{tag}_error>')

    # Layer 5: File processing (media groups handled by RateLimitMiddleware)
    if message.document:
        user_id = message.from_user.id

        async with file_processing_tracker.acquire(user_id) as acquired:
            if not acquired:
                await message.answer(
                    **Text(
                        '📄 Wait for the previous file to finish processing.'
                    ).as_kwargs()
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

                msg = f'File "{file_name}" ready (id: {file_id})'
                if message.caption:
                    msg += f'\nUser caption: {message.caption}'
                text_parts.append(f'<system_message>{msg}</system_message>')
            except FileTooLargeError as e:
                await message.answer(**Text(f'📄 {e}').as_kwargs())
                return
            except (DocumentProcessingError, LettaProcessingError) as e:
                LOGGER.warning('Document processing failed: %s, telegram_id=%s', e, user_id)
                text_parts.append(f'<system_message>File error: {e}</system_message>')
            except APIError as e:
                status = getattr(e, 'status_code', 'unknown')
                body = getattr(e, 'body', 'no body')
                LOGGER.warning(
                    'Document processing failed: status=%s, body=%s, telegram_id=%s',
                    status,
                    body,
                    user_id,
                )
                error_msg = f'File error: status={status}, body={body}'
                text_parts.append(f'<system_message>{error_msg}</system_message>')

    # Unsupported content types
    if message.video:
        await message.answer(**Text('Video content is not supported').as_kwargs())
    if message.sticker:
        await message.answer(**Text('Stickers are not yet supported').as_kwargs())

    # Build content parts for Letta API (image first, then text per spec)
    content_parts: list[ContentPart] = []

    # Layer 5: Image content (processed first, added to content first)
    if message.photo:
        try:
            # Use highest resolution (last element in photo array)
            image_part = await process_telegram_photo(bot, message.photo[-1])
            content_parts.append(image_part)
        except ImageProcessingError as e:
            LOGGER.warning(
                'Image processing failed: %s, telegram_id=%s',
                e,
                message.from_user.id,
            )
            # Graceful degradation: prepend error to text parts
            text_parts.insert(0, f'<image_processing_error>{e}</image_processing_error>')

    # Combine text parts
    message_text = '\n\n'.join(text_parts) if text_parts else None

    # Add text content part if we have text
    if message_text:
        text_part: TextContentPart = {'type': 'text', 'text': message_text}
        content_parts.append(text_part)

    # Check if we have any content to send
    if not content_parts:
        await message.answer(
            **Text(
                'No supported content provided, I hope to hear more from you'
            ).as_kwargs()
        )
        return

    # Content ready for Letta API
    request = content_parts

    try:
        async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
            response_stream = await client.agents.messages.stream(
                agent_id=agent_id,
                messages=[{'role': 'user', 'content': request}],  # type: ignore[typeddict-item]
                include_pings=True,
            )

            handler = AgentStreamHandler(message)

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
            **Text(
                '❌ The assistant service stopped responding. '
                'This may be a temporary issue with Letta API. '
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
