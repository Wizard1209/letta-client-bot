"""Proactive assistant behavior: notifications and scheduling tool management."""

import logging
from pathlib import Path

from aiogram import Bot, Router
from aiogram.filters.callback_data import CallbackData
from aiogram.filters.command import Command
from aiogram.types import CallbackQuery, InaccessibleMessage, Message
from aiogram.utils.formatting import Bold, Code, Text, as_list
from aiogram.utils.keyboard import InlineKeyboardBuilder
from gel import AsyncIOExecutor as GelClient

from letta_bot.auth import require_identity
from letta_bot.client import client, register_notify_tool, register_schedule_message_tool
from letta_bot.config import CONFIG
from letta_bot.queries.get_identity_async_edgeql import GetIdentityResult

LOGGER = logging.getLogger(__name__)


class NotifyCallback(CallbackData, prefix='notify'):
    """Callback data for notification enable/disable buttons."""

    enable: bool


# Memory block label for agent notification tools guidance
NOTIFICATION_TOOL_BLOCK_LABEL = 'proactive_messaging_protocol'

NOTIFICATION_MEMORY_BLOCK_DESC = (
    'How to use scheduling and notification tools to enable proactive behavior: '
    'scheduling reminders and follow-ups, sending notifications at specific times '
    'across timezones, creating recurring check-ins, understanding conversational '
    'vs silent communication modes, context preservation, and timing verification'
)


def _load_memory_block_content() -> str:
    """Load memory block content from markdown file."""
    memo_path = (
        Path(__file__).parent
        / 'custom_tools'
        / 'memory_blocks'
        / 'proactive_messaging_protocol.md'
    )
    return memo_path.read_text(encoding='utf-8')


def get_notification_router(bot: Bot, gel_client: GelClient) -> Router:
    """Create and return proactive mode command router."""
    router = Router(name=f'{__name__}.commands')

    @router.message(Command('notify'))
    @require_identity(gel_client)
    async def notify_command(message: Message, identity: GetIdentityResult) -> None:
        """Handle /notify command - manage proactive assistant behavior."""
        if not message.from_user:
            return

        if not identity.selected_agent:
            await message.answer(
                Text('❌ No assistant selected. Use /switch to select one.').as_markdown()
            )
            return

        await handle_notify_status(message, identity.selected_agent)

    @router.callback_query(NotifyCallback.filter())
    @require_identity(gel_client)
    async def handle_notify_callback(
        callback: CallbackQuery,
        callback_data: NotifyCallback,
        identity: GetIdentityResult,
    ) -> None:
        """Handle enable/disable button clicks."""
        if not callback.from_user:
            return

        if isinstance(callback.message, InaccessibleMessage) or not callback.message:
            await callback.answer('Message expired. Use /notify again.')
            return

        if not identity.selected_agent:
            await callback.answer('No assistant selected.')
            return

        await callback.answer()

        if callback_data.enable:
            await handle_notify_enable(
                callback.message, identity.selected_agent, str(callback.from_user.id)
            )
        else:
            await handle_notify_disable(callback.message, identity.selected_agent)

    LOGGER.info('Notification handlers initialized')
    return router


async def handle_notify_status(message: Message, agent_id: str) -> None:
    """Check proactive behavior status for the agent."""
    try:
        # Check if tools are attached (check ALL tools across all pages)
        schedule_tool_attached = False
        notify_tool_attached = False
        async for tool in client.agents.tools.list(agent_id=agent_id):
            if tool.name == 'schedule_message':
                schedule_tool_attached = True
            if tool.name == 'notify_via_telegram':
                notify_tool_attached = True
            if schedule_tool_attached and notify_tool_attached:
                break  # Found both, can stop early

        # Check environment variables
        agent = await client.agents.retrieve(agent_id=agent_id)
        env_vars = agent.tool_exec_environment_variables or []

        # Scheduling env vars
        has_letta_key = any(v.key == 'LETTA_API_KEY' for v in env_vars if hasattr(v, 'key'))
        has_scheduler_token = any(
            v.key == 'SCHEDULER_API_KEY' for v in env_vars if hasattr(v, 'key')
        )
        has_agent_id = any(v.key == 'AGENT_ID' for v in env_vars if hasattr(v, 'key'))

        # Notification env vars
        has_bot_token = any(
            v.key == 'TELEGRAM_BOT_TOKEN' for v in env_vars if hasattr(v, 'key')
        )
        has_chat_id = any(
            v.key == 'TELEGRAM_CHAT_ID' for v in env_vars if hasattr(v, 'key')
        )

        schedule_configured = (
            schedule_tool_attached
            and has_letta_key
            and has_scheduler_token
            and has_agent_id
        )
        notify_configured = notify_tool_attached and has_bot_token and has_chat_id

        overall_status = '✅' if (schedule_configured and notify_configured) else '⚠️'

        # Build inline keyboard with Enable/Disable buttons
        builder = InlineKeyboardBuilder()
        builder.button(text='✅ Enable', callback_data=NotifyCallback(enable=True))
        builder.button(text='❌ Disable', callback_data=NotifyCallback(enable=False))
        builder.adjust(2)

        await message.answer(
            as_list(
                Text(overall_status, ' ', Bold('Proactive Mode')),
                '',
                Text(Bold('Agent: '), agent.name),
                '',
                Text(Bold('📅 Reminders & Follow-ups:')),
                Text('  Tool attached: ', '✅ Yes' if schedule_tool_attached else '❌ No'),
                Text(
                    '  Environment configured: ',
                    '✅ Yes' if schedule_configured else '❌ No',
                ),
                '',
                Text(Bold('📢 Proactive Messaging:')),
                Text('  Tool attached: ', '✅ Yes' if notify_tool_attached else '❌ No'),
                Text(
                    '  Environment configured: ',
                    '✅ Yes' if notify_configured else '❌ No',
                ),
                sep='\n',
            ).as_markdown(),
            reply_markup=builder.as_markup(),
        )

    except Exception as e:
        LOGGER.error(f'Error checking notification status: {e}')
        await message.answer(Text('❌ Error checking status: ', str(e)).as_markdown())


async def handle_notify_enable(message: Message, agent_id: str, chat_id: str) -> None:
    """Enable proactive behavior for the agent (reminders, follow-ups, notifications)."""
    try:
        # Check if Scheduler API key is configured
        if not CONFIG.scheduler_api_key:
            await message.edit_text(
                Text(
                    '❌ Scheduled messages require SCHEDULER_API_KEY to be configured. '
                    'Please contact the administrator.'
                ).as_markdown()
            )
            return

        agent = await client.agents.retrieve(agent_id=agent_id)

        # STEP 1: Enable Scheduling (schedule_message)
        await message.edit_text(
            Text('📅 Configuring ', Code('schedule_message'), ' tool...').as_markdown()
        )
        await _enable_schedule_tool(agent_id)

        # STEP 2: Enable Notifications (notify_via_telegram)
        await message.edit_text(
            Text('📢 Configuring ', Code('notify_via_telegram'), ' tool...').as_markdown()
        )
        await _enable_notify_tool(agent_id, chat_id)

        # STEP 3: Attach Memory Block (agent_communication_tools_memo)
        await message.edit_text(
            Text('📝 Attaching tool guidance memory block...').as_markdown()
        )
        await _attach_tool_memory_block(agent_id)

        # Final success message
        await message.edit_text(
            Text(
                '✅ Proactive mode enabled for ',
                Bold(agent.name),
                '\n\nYour assistant can now:',
                '\n• Schedule future check-ins and reminders',
                '\n• Queue tasks for later execution',
                '\n• Notify you at the right time',
            ).as_markdown()
        )

    except Exception as e:
        LOGGER.error(f'Error enabling communication tools: {e}')
        await message.edit_text(Text('❌ Error enabling tools: ', str(e)).as_markdown())


async def _enable_schedule_tool(agent_id: str) -> None:
    """Enable schedule_message tool - completely separate logic."""
    # Validate required config
    if not CONFIG.scheduler_url or not CONFIG.scheduler_api_key:
        raise ValueError('SCHEDULER_URL and SCHEDULER_API_KEY must be configured')

    # Check if tool exists and register/attach it
    schedule_tool = await register_schedule_message_tool()

    # Attach tool if not already attached (check ALL tools)
    if schedule_tool.id:
        tool_already_attached = False
        async for tool in client.agents.tools.list(agent_id=agent_id):
            if tool.id == schedule_tool.id:
                tool_already_attached = True
                break

        if not tool_already_attached:
            await client.agents.tools.attach(agent_id=agent_id, tool_id=schedule_tool.id)
            LOGGER.info(
                f'Attached schedule_message tool {schedule_tool.id} to agent {agent_id}'
            )

    # Set up environment variables for scheduling
    agent = await client.agents.retrieve(agent_id=agent_id)
    current_env_vars = agent.tool_exec_environment_variables or []

    env_dict: dict[str, str] = {
        var.key: var.value
        for var in current_env_vars
        if hasattr(var, 'key') and hasattr(var, 'value') and var.value is not None
    }

    # Add scheduling env vars
    env_dict['LETTA_API_KEY'] = CONFIG.letta_api_key
    env_dict['SCHEDULER_URL'] = CONFIG.scheduler_url
    env_dict['SCHEDULER_API_KEY'] = CONFIG.scheduler_api_key
    env_dict['AGENT_ID'] = agent_id

    await client.agents.update(agent_id=agent_id, tool_exec_environment_variables=env_dict)


async def _enable_notify_tool(agent_id: str, chat_id: str) -> None:
    """Enable notify_via_telegram tool - completely separate logic."""
    # Check if tool exists and register/attach it
    notify_tool = await register_notify_tool()

    # Attach tool if not already attached (check ALL tools)
    if notify_tool.id:
        tool_already_attached = False
        async for tool in client.agents.tools.list(agent_id=agent_id):
            if tool.id == notify_tool.id:
                tool_already_attached = True
                break

        if not tool_already_attached:
            await client.agents.tools.attach(agent_id=agent_id, tool_id=notify_tool.id)
            LOGGER.info(
                f'Attached notify_via_telegram tool {notify_tool.id} to agent {agent_id}'
            )

    # Set up environment variables for notifications
    agent = await client.agents.retrieve(agent_id=agent_id)
    current_env_vars = agent.tool_exec_environment_variables or []

    env_dict: dict[str, str] = {
        var.key: var.value
        for var in current_env_vars
        if hasattr(var, 'key') and hasattr(var, 'value') and var.value is not None
    }

    # Add notification env vars
    env_dict['TELEGRAM_BOT_TOKEN'] = CONFIG.bot_token
    env_dict['TELEGRAM_CHAT_ID'] = chat_id

    await client.agents.update(agent_id=agent_id, tool_exec_environment_variables=env_dict)


async def handle_notify_disable(message: Message, agent_id: str) -> None:
    """Disable proactive behavior for the agent."""
    try:
        agent = await client.agents.retrieve(agent_id=agent_id)

        # STEP 1: Disable Scheduling (schedule_message)
        await message.edit_text(
            Text('📅 Removing ', Code('schedule_message'), ' tool...').as_markdown()
        )
        await _disable_schedule_tool(agent_id)

        # STEP 2: Disable Notifications (notify_via_telegram)
        await message.edit_text(
            Text('📢 Removing ', Code('notify_via_telegram'), ' tool...').as_markdown()
        )
        await _disable_notify_tool(agent_id)

        # STEP 3: Detach Memory Block (agent_communication_tools_memo)
        await message.edit_text(
            Text('📝 Removing tool guidance memory block...').as_markdown()
        )
        await _detach_tool_memory_block(agent_id)

        # Final success message
        await message.edit_text(
            Text('✅ Proactive mode disabled for ', Bold(agent.name)).as_markdown()
        )

    except Exception as e:
        LOGGER.error(f'Error disabling communication tools: {e}')
        await message.edit_text(Text('❌ Error disabling tools: ', str(e)).as_markdown())


async def _disable_schedule_tool(agent_id: str) -> None:
    """Disable schedule_message tool - completely separate logic."""
    # Detach the tool (search ALL tools)
    schedule_tool = None
    async for tool in client.agents.tools.list(agent_id=agent_id):
        if tool.name == 'schedule_message':
            schedule_tool = tool
            break

    if schedule_tool and schedule_tool.id:
        await client.agents.tools.detach(agent_id=agent_id, tool_id=schedule_tool.id)
        LOGGER.info(f'Detached schedule_message tool from agent {agent_id}')

    # Remove environment variables
    agent = await client.agents.retrieve(agent_id=agent_id)
    current_env_vars = agent.tool_exec_environment_variables or []

    filtered_vars: dict[str, str] = {
        var.key: var.value
        for var in current_env_vars
        if hasattr(var, 'key')
        and hasattr(var, 'value')
        and var.value is not None
        and var.key
        not in ('LETTA_API_KEY', 'SCHEDULER_URL', 'SCHEDULER_API_KEY', 'AGENT_ID')
    }
    await client.agents.update(
        agent_id=agent_id, tool_exec_environment_variables=filtered_vars
    )


async def _disable_notify_tool(agent_id: str) -> None:
    """Disable notify_via_telegram tool - completely separate logic."""
    # Detach the tool (search ALL tools)
    notify_tool = None
    async for tool in client.agents.tools.list(agent_id=agent_id):
        if tool.name == 'notify_via_telegram':
            notify_tool = tool
            break

    if notify_tool and notify_tool.id:
        await client.agents.tools.detach(agent_id=agent_id, tool_id=notify_tool.id)
        LOGGER.info(f'Detached notify_via_telegram tool from agent {agent_id}')

    # Remove environment variables
    agent = await client.agents.retrieve(agent_id=agent_id)
    current_env_vars = agent.tool_exec_environment_variables or []

    filtered_vars: dict[str, str] = {
        var.key: var.value
        for var in current_env_vars
        if hasattr(var, 'key')
        and hasattr(var, 'value')
        and var.value is not None
        and var.key not in ('TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID')
    }

    await client.agents.update(
        agent_id=agent_id, tool_exec_environment_variables=filtered_vars
    )


async def _attach_tool_memory_block(agent_id: str) -> None:
    """Attach proactive messaging protocol memory block to agent."""
    try:
        # Check if block with this label already exists on agent (check ALL blocks)
        block_exists = False
        async for block in client.agents.blocks.list(agent_id=agent_id):
            if block.label == NOTIFICATION_TOOL_BLOCK_LABEL:
                block_exists = True
                break

        if block_exists:
            LOGGER.info(
                f'Memory block {NOTIFICATION_TOOL_BLOCK_LABEL} already attached '
                f'to agent {agent_id}'
            )
            return

        # Load memory block content from markdown file
        block_content = _load_memory_block_content()

        # Create new memory block
        block = await client.blocks.create(
            label=NOTIFICATION_TOOL_BLOCK_LABEL,
            description=NOTIFICATION_MEMORY_BLOCK_DESC,
            value=block_content,
        )

        LOGGER.info(
            f'Created memory block {NOTIFICATION_TOOL_BLOCK_LABEL} with ID {block.id}'
        )

        # Attach block to agent
        if block.id:
            await client.agents.blocks.attach(agent_id=agent_id, block_id=block.id)
            LOGGER.info(f'Attached memory block {block.id} to agent {agent_id}')

    except Exception as e:
        LOGGER.error(f'Error attaching memory block to agent {agent_id}: {e}')
        raise


async def _detach_tool_memory_block(agent_id: str) -> None:
    """Detach and delete proactive messaging protocol memory block from agent."""
    try:
        # List agent's blocks and find the one with our label (search ALL blocks)
        target_block = None
        async for block in client.agents.blocks.list(agent_id=agent_id):
            if block.label == NOTIFICATION_TOOL_BLOCK_LABEL:
                target_block = block
                break

        if not target_block:
            LOGGER.info(
                f'Memory block {NOTIFICATION_TOOL_BLOCK_LABEL} not found '
                f'on agent {agent_id}'
            )
            return

        if not target_block.id:
            LOGGER.warning(
                f'Memory block {NOTIFICATION_TOOL_BLOCK_LABEL} has no ID, cannot detach'
            )
            return

        # Detach block from agent
        await client.agents.blocks.detach(agent_id=agent_id, block_id=target_block.id)
        LOGGER.info(f'Detached memory block {target_block.id} from agent {agent_id}')

        # Delete the block
        await client.blocks.delete(block_id=target_block.id)
        LOGGER.info(f'Deleted memory block {target_block.id}')

    except Exception as e:
        LOGGER.error(f'Error detaching memory block from agent {agent_id}: {e}')
        raise
