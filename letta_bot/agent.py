import json
import logging

from aiogram import Bot, Router
from aiogram.filters.callback_data import CallbackData
from aiogram.filters.command import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.formatting import BlockQuote, Code, Text
from aiogram.utils.keyboard import InlineKeyboardBuilder
from gel import AsyncIOExecutor as GelClient
from letta_client import AsyncLetta as LettaClient
from letta_client.core.api_error import ApiError
from letta_client.types.identity import Identity

from letta_bot.config import CONFIG
from letta_bot.queries.create_auth_request_async_edgeql import (
    ResourceType,
    create_auth_request as create_auth_request_query,
)
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

client = LettaClient(project=CONFIG.letta_project, token=CONFIG.letta_api_key)
LOGGER = logging.getLogger(__name__)


# NOTE: Callback should fit in 64 chars
class RequestNewAgentCallback(CallbackData, prefix='from_template'):
    template_name: str
    version: str = 'latest'


def get_general_agent_router(bot: Bot, gel_client: GelClient) -> Router:
    """Create and return agent router with message and command handlers."""
    agent_router = Router(name=__name__)
    agent_commands_router = Router(name=f'{__name__}.commands')
    agent_messaging_router = get_agent_messaging_router(gel_client)

    @agent_commands_router.message(Command('request_resource'))
    async def request_resource(message: Message) -> None:
        # TODO: if no pending requests

        templates_response = await client.templates.list(project_slug=CONFIG.letta_project)
        templates = templates_response.templates

        builder = InlineKeyboardBuilder()
        for t in templates:
            data = RequestNewAgentCallback(template_name=t.name, version=t.latest_version)
            builder.button(text=f'{t.name}', callback_data=data.pack())
        await message.answer(
            Text('Choose template').as_markdown(), reply_markup=builder.as_markup()
        )

    @agent_commands_router.callback_query(RequestNewAgentCallback.filter())
    async def register_request_resource(
        callback: CallbackQuery, callback_data: RequestNewAgentCallback
    ) -> None:
        if not await get_allowed_identity_query(
            gel_client, telegram_id=callback.from_user.id
        ):
            # TODO: maybe identity name could be customed
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

        # notify admins
        if CONFIG.admin_ids is None:
            return
        for tg_id in CONFIG.admin_ids:
            await bot.send_message(tg_id, Text('New agent request').as_markdown())

    # Include nested routers
    agent_router.include_routers(agent_commands_router, agent_messaging_router)

    LOGGER.info('Agent handlers initialized')
    return agent_router


def get_agent_messaging_router(gel_client: GelClient) -> Router:
    agent_router = Router(name=f'{__name__}.messaging')

    @agent_router.message()
    async def message_handler(message: Message) -> None:
        if not message.from_user:
            return

        if not await get_allowed_identity_query(
            gel_client, telegram_id=message.from_user.id
        ):
            # TODO: mb redirect to concrete command
            await message.answer(Text('No access').as_markdown())
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

        # TODO: return single item from select instead of the list
        identity = (await get_identity_query(gel_client, telegram_id=message.from_user.id))[
            0
        ]
        # NOTE: select the most recent agent if user hasn't selected
        if not identity.selected_agent:
            agent_id = await get_default_agent(identity)
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
                    'timeout_in_seconds': 60,
                },
            )

            async for event in response_stream:
                try:
                    if hasattr(event, 'message_type'):
                        message_type = event.message_type

                        if message_type == 'assistant_message':
                            content = getattr(event, 'content', '')
                            if content and content.strip():
                                prefixed_content = Text(f'**Agent response:**\n\n{content}')
                                await message.answer(prefixed_content.as_markdown())

                        elif message_type == 'reasoning_message':
                            # TODO: add ability to disable reasoning in Identity table
                            reasoning_text = getattr(event, 'reasoning', '')
                            content = Text(
                                'Agent reasoning\n\n', BlockQuote(reasoning_text)
                            )
                            await message.answer(content.as_markdown())

                        elif message_type == 'tool_call_message':
                            tool_call = event.tool_call  # type: ignore
                            tool_name = tool_call.name
                            arguments = tool_call.arguments

                            if arguments and arguments.strip():
                                try:
                                    args_obj = json.loads(arguments)

                                    # Memory operations
                                    if tool_name == 'archival_memory_insert':
                                        content_text = args_obj.get('content', '')
                                        formatted = Text(
                                            '**Agent remembered:**\n\n',
                                            BlockQuote(content_text),
                                        )
                                        await message.answer(formatted.as_markdown())

                                    elif tool_name == 'archival_memory_search':
                                        query = args_obj.get('query', '')
                                        formatted = Text('**Agent searching:** ', query)
                                        await message.answer(formatted.as_markdown())

                                    elif tool_name == 'memory_insert':
                                        new_str = args_obj.get('new_str', '')
                                        formatted = Text(
                                            '**Agent updating memory:**\n\n',
                                            BlockQuote(new_str),
                                        )
                                        await message.answer(formatted.as_markdown())

                                    elif tool_name == 'memory_replace':
                                        old_str = args_obj.get('old_str', '')
                                        new_str = args_obj.get('new_str', '')
                                        formatted = Text(
                                            '**Agent modifying memory:**\n\n',
                                            'New:\n',
                                            BlockQuote(new_str),
                                            '\n\nOld:\n',
                                            BlockQuote(old_str),
                                        )
                                        await message.answer(formatted.as_markdown())

                                    elif tool_name == 'run_code':
                                        code = args_obj.get('code', '')
                                        language = args_obj.get('language', 'python')
                                        formatted = Text(
                                            '**Agent ran code:**\n\n', Code(language, code)
                                        )
                                        await message.answer(formatted.as_markdown())

                                    else:
                                        # Generic tool call display
                                        formatted_args = json.dumps(args_obj, indent=2)
                                        formatted = Text(
                                            f'**Agent using tool:** {tool_name}\n\n',
                                            Code('json', formatted_args),
                                        )
                                        await message.answer(formatted.as_markdown())

                                except json.JSONDecodeError as e:
                                    LOGGER.warning(f'Error parsing tool arguments: {e}')
                                    formatted = Text(
                                        f'**Agent using tool:** {tool_name}\n\n',
                                        Code('', arguments),
                                    )
                                    await message.answer(formatted.as_markdown())

                except Exception as e:
                    LOGGER.warning(f'Error processing stream event: {e}')
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


# Letta API integration functions
async def create_letta_identity(identifier_key: str, name: str) -> Identity:
    """Create identity in Letta API with retry logic.

    Returns identity object with .id attribute.

    States:
    1. Attempt creation
    2. If fails, attempt retrieval by identifier_key
    3. If retrieval also fails, raise error
    """
    try:
        # State 1: Attempt to create new identity
        identity = await client.identities.create(
            identifier_key=identifier_key,
            name=name,
            identity_type='user',
        )
        LOGGER.info(f'Created identity: {identity.id}')
        return identity

    except ApiError as create_error:
        # State 2: Creation failed, attempt to retrieve existing identity
        LOGGER.info(f'Retrieving existing identity: {identifier_key}')

        try:
            # List identities by identifier_key (same pattern as delete_identity.py)
            identities = await client.identities.list(identifier_key=identifier_key)

            if not identities:
                LOGGER.error(f'No existing identity found: {identifier_key}')
                raise create_error

            identity = identities[0]
            LOGGER.info(f'Retrieved existing identity: {identity.id}')
            return identity

        except ApiError as retrieve_error:
            # State 3: Both creation and retrieval failed
            LOGGER.critical(f'Identity creation and retrieval failed: {identifier_key}')
            raise retrieve_error


async def create_agent_from_template(template_id: str, identity_id: str) -> None:
    """Create agent from template in Letta API. Returns agent object."""
    info = RequestNewAgentCallback.unpack(template_id)

    # NOTE: That's weird finding out ID of current project in use
    # But Letta client constructor accepts project slug
    projects_list = (await client.projects.list(name=CONFIG.letta_project)).projects
    if len(projects_list) > 1:
        LOGGER.warning('There is more than one project with given name')
    if len(projects_list) == 0:
        LOGGER.critical('Project in use wasnt found')
        raise RuntimeError('Project in use wasnt found')

    project_id = projects_list[0].id

    # TODO: mb tags for creator, mb custom name
    await client.templates.createagentsfromtemplate(
        project_id, f'{info.template_name}:{info.version}', identity_ids=[identity_id]
    )


async def get_default_agent(identity: GetIdentityResult) -> str:
    result = await client.identities.agents.list(
        identity_id=identity.identity_id, limit=1, order='asc'
    )
    # TODO: what if there are no agents
    agent_id = result[0].id
    return agent_id
