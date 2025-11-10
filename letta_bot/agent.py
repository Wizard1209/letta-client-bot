import logging

from aiogram import Bot, Router
from aiogram.filters.callback_data import CallbackData
from aiogram.filters.command import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.chat_action import ChatActionSender
from aiogram.utils.formatting import Text
from aiogram.utils.keyboard import InlineKeyboardBuilder
from gel import AsyncIOExecutor as GelClient
from letta_client.core.api_error import ApiError

from letta_bot.auth import require_identity
from letta_bot.client import client, get_default_agent
from letta_bot.config import CONFIG
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

LOGGER = logging.getLogger(__name__)


# NOTE: Callback should fit in 64 chars
class RequestNewAgentCallback(CallbackData, prefix='from_template'):
    template_name: str
    version: str = 'latest'


class SwitchAgentCallback(CallbackData, prefix='switch_agent'):
    agent_id: str


def get_general_agent_router(bot: Bot, gel_client: GelClient) -> Router:
    """Create and return agent router with message and command handlers."""
    agent_commands_router = Router(name=f'{__name__}.commands')
    agent_messaging_router = get_agent_messaging_router(bot, gel_client)

    @agent_commands_router.message(Command('request_identity'))
    async def request_identity(message: Message) -> None:
        """Request identity access without requesting an agent."""
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

    @agent_commands_router.message(Command('new_agent_from_template'))
    async def new_agent_from_template(message: Message) -> None:
        # TODO: if no pending requests

        templates_response = await client.templates.list(project_slug=CONFIG.letta_project)
        templates = templates_response.templates

        # TODO: Maybe adjust builder for vertical buttons layout
        builder = InlineKeyboardBuilder()
        for t in templates:
            data = RequestNewAgentCallback(template_name=t.name, version=t.latest_version)
            builder.button(text=f'{t.name}', callback_data=data.pack())
        await message.answer(
            Text('Choose template').as_markdown(), reply_markup=builder.as_markup()
        )

    @agent_commands_router.callback_query(RequestNewAgentCallback.filter())
    async def register_agent_request(
        callback: CallbackQuery, callback_data: RequestNewAgentCallback
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

        # Check if user already has a pending identity request
        has_pending = await check_pending_request_query(
            gel_client,
            telegram_id=callback.from_user.id,
            resource_type=ResourceType.CREATE_AGENT_FROM_TEMPLATE,
        )
        if has_pending:
            await callback.answer(
                Text(
                    '⏳ You already have a pending identity access request. '
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

        # Notify user that request was submitted
        await callback.answer(
            Text(
                '✅ Your request has been submitted and is pending admin approval'
            ).as_markdown(),
        )

        # notify admins
        if CONFIG.admin_ids is None:
            return
        for tg_id in CONFIG.admin_ids:
            await bot.send_message(tg_id, Text('New agent request').as_markdown())

    @agent_commands_router.message(Command('switch_agent'))
    @require_identity(gel_client)
    async def switch_agent(message: Message, identity: GetIdentityResult) -> None:
        """List user's agents and allow switching between them."""
        if not message.from_user:
            return

        # List all agents for this identity
        try:
            agents = await client.identities.agents.list(identity_id=identity.identity_id)

            if not agents:
                await message.answer(
                    Text(
                        "You don't have any agents yet. "
                        'Use /agent_from_template to request one.'
                    ).as_markdown()
                )
                return

            # Build inline keyboard with agents
            builder = InlineKeyboardBuilder()
            for agent in agents:
                # Mark currently selected agent
                is_selected = agent.id == identity.selected_agent
                button_text = f'{"✅ " if is_selected else ""}{agent.name}'
                callback_data = SwitchAgentCallback(agent_id=agent.id)
                builder.button(text=button_text, callback_data=callback_data.pack())

            # Adjust layout for vertical buttons
            builder.adjust(1)

            await message.answer(
                Text('Select an agent:').as_markdown(), reply_markup=builder.as_markup()
            )

        except ApiError as e:
            LOGGER.error(f'Error listing agents for identity {identity.identity_id}: {e}')
            await message.answer(Text('Error retrieving your agents').as_markdown())

    @agent_commands_router.callback_query(SwitchAgentCallback.filter())
    @require_identity(gel_client)
    async def handle_switch_agent(
        callback: CallbackQuery,
        callback_data: SwitchAgentCallback,
        identity: GetIdentityResult,
    ) -> None:
        """Handle agent selection callback."""
        if not callback.from_user:
            return

        # Update selected agent in database
        await set_selected_agent_query(
            gel_client, identity_id=identity.identity_id, agent_id=callback_data.agent_id
        )

        await bot.send_message(
            chat_id=callback.from_user.id,
            text=Text('✅ Agent switched successfully').as_markdown(),
        )

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

        if message.audio or message.voice:
            await message.answer(
                Text('Audio and voice are not yet supported, but will be').as_markdown()
            )
        if message.video:
            await message.answer(Text('Video content is not supported').as_markdown())
        if message.photo or message.sticker:
            await message.answer(
                Text('Photos and stickers are not yet supported, but will be').as_markdown()
            )
        if not message.text:
            await message.answer(
                Text(
                    'No supported context provided, I hope to hear more from you'
                ).as_markdown()
            )
            return

        # NOTE: select the most recent agent if user hasn't selected
        if not identity.selected_agent:
            try:
                agent_id = await get_default_agent(identity.identity_id)
            except IndexError:
                await message.answer('There is no agent yet on your identity.')
                return
            await set_selected_agent_query(
                gel_client, identity_id=identity.identity_id, agent_id=agent_id
            )
            # TODO: notify user about default agent select
        else:
            agent_id = identity.selected_agent

        # Should I let agent know that message came through telegram?
        request = [{'type': 'text', 'text': message.text}]

        try:
            response_stream = client.agents.messages.create_stream(
                agent_id=agent_id,
                messages=[{'role': 'user', 'content': request}],  # type: ignore
                include_pings=True,
                request_options={
                    'timeout_in_seconds': 120,
                },
            )

            handler = AgentStreamHandler(message)

            async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
                async for event in response_stream:
                    try:
                        await handler.handle_event(event)
                    except Exception as e:
                        LOGGER.error(f'Error processing stream event: {e}')
                        continue

        except ApiError as e:
            LOGGER.error(
                'Letta API error - status: %s, body: %s, type: %s',
                getattr(e, 'status_code', 'unknown'),
                getattr(e, 'body', 'no body'),
                type(e).__name__,
            )
            await message.answer(Text('Error communicating with agent').as_markdown())
            raise

        except Exception as e:
            LOGGER.exception('Message handler error')
            await message.answer(Text('An error occurred: ', str(e)).as_markdown())
            raise

    return agent_router
