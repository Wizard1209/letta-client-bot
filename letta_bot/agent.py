import logging

from aiogram import Bot, Router
from aiogram.filters.callback_data import CallbackData
from aiogram.filters.command import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.chat_action import ChatActionSender
from aiogram.utils.formatting import Text
from aiogram.utils.keyboard import InlineKeyboardBuilder
from gel import AsyncIOExecutor as GelClient
from httpx import ReadTimeout
from letta_client import APIError

from letta_bot.auth import require_identity
from letta_bot.client import client, get_default_agent
from letta_bot.config import CONFIG
from letta_bot.letta_sdk_extensions import list_templates
from letta_bot.notification import get_notification_router
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
from letta_bot.queries.get_identity_async_edgeql import GetIdentityResult
from letta_bot.queries.is_registered_async_edgeql import (
    is_registered as is_registered_query,
)
from letta_bot.queries.set_selected_agent_async_edgeql import (
    set_selected_agent as set_selected_agent_query,
)
from letta_bot.response_handler import AgentStreamHandler
from letta_bot.transcription import TranscriptionError, get_transcription_service

LOGGER = logging.getLogger(__name__)


# NOTE: Callback should fit in 64 chars
class NewAssistantCallback(CallbackData, prefix='newassistant'):
    template_name: str
    version: str = 'latest'


class SwitchAssistantCallback(CallbackData, prefix='switch'):
    agent_id: str


def get_general_agent_router(bot: Bot, gel_client: GelClient) -> Router:
    """Create and return agent router with message and command handlers."""
    agent_commands_router = Router(name=f'{__name__}.commands')
    agent_messaging_router = get_agent_messaging_router(bot, gel_client)

    @agent_commands_router.message(Command('botaccess'))
    async def botaccess(message: Message) -> None:
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
        if CONFIG.admin_ids is not None:
            for tg_id in CONFIG.admin_ids:
                await bot.send_message(
                    tg_id, Text('New identity access request').as_markdown()
                )

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
        callback: CallbackQuery, callback_data: NewAssistantCallback
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

        if not await get_allowed_identity_query(
            gel_client, telegram_id=callback.from_user.id
        ):
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

    @agent_commands_router.message(Command('switch'))
    @require_identity(gel_client)
    async def switch(message: Message, identity: GetIdentityResult) -> None:
        """List user's assistants and allow switching between them."""
        if not message.from_user:
            return

        # List all agents for this identity
        try:
            # Collect ALL agents across all pages
            all_agents = []
            async for agent in client.identities.agents.list(
                identity_id=identity.identity_id
            ):
                all_agents.append(agent)

            if not all_agents:
                await message.answer(
                    Text(
                        "You don't have any assistants yet. "
                        'Use /newassistant to request one.'
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

    @agent_commands_router.callback_query(SwitchAssistantCallback.filter())
    @require_identity(gel_client)
    async def handle_switch_assistant(
        callback: CallbackQuery,
        callback_data: SwitchAssistantCallback,
        identity: GetIdentityResult,
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
            async for agent in client.identities.agents.list(
                identity_id=identity.identity_id
            ):
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

    # Include nested routers
    agent_commands_router.include_router(get_notification_router(bot, gel_client))
    agent_commands_router.include_router(agent_messaging_router)

    LOGGER.info('Agent handlers initialized')
    return agent_commands_router


def get_agent_messaging_router(bot: Bot, gel_client: GelClient) -> Router:
    agent_router = Router(name=f'{__name__}.messaging')

    @agent_router.message()
    @require_identity(gel_client)
    async def message_handler(message: Message, identity: GetIdentityResult) -> None:
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
                    Text(
                        'Audio not supported. OpenAI API key not configured.'
                    ).as_markdown()
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

        # NOTE: select the most recent agent if user hasn't selected
        if not identity.selected_agent:
            try:
                agent_id = await get_default_agent(identity.identity_id)
            except IndexError:
                await message.answer('You have no assistants yet. Use /newassistant')
                return
            await set_selected_agent_query(
                gel_client, identity_id=identity.identity_id, agent_id=agent_id
            )
            # TODO: notify user about default agent select
        else:
            agent_id = identity.selected_agent

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

    return agent_router
