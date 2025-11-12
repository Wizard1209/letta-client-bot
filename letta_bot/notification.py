"""Telegram notification and scheduling tool management handlers."""

import logging
from pathlib import Path

from aiogram import Bot, Router
from aiogram.filters.command import Command
from aiogram.types import Message
from aiogram.utils.formatting import Bold, Code, Text, as_list, as_marked_section
from gel import AsyncIOExecutor as GelClient

from letta_bot.auth import require_identity
from letta_bot.client import client, register_notify_tool, register_schedule_message_tool
from letta_bot.config import CONFIG
from letta_bot.queries.get_identity_async_edgeql import GetIdentityResult

LOGGER = logging.getLogger(__name__)

# Memory block label for agent notification tools guidance
NOTIFICATION_TOOL_BLOCK_LABEL = 'proactive_messaging_protocol'


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
    """Create and return notification command router."""
    router = Router(name=f'{__name__}.commands')

    @router.message(Command('notify'))
    @require_identity(gel_client)
    async def notify_command(message: Message, identity: GetIdentityResult) -> None:
        """Handle /notify command for managing agent notifications."""
        if not message.from_user or not message.text:
            return

        # Parse subcommand
        parts = message.text.strip().split()
        subcommand = parts[1].lower() if len(parts) > 1 else 'status'

        if subcommand not in ['enable', 'disable', 'status']:
            await message.answer(
                as_list(
                    Text('❌ ', Bold('Invalid command')),
                    '',
                    Text('Usage:'),
                    as_marked_section(
                        Text(Code('/notify enable'), ' - Enable proactive notifications'),
                        Text(Code('/notify disable'), ' - Disable proactive notifications'),
                        Text(Code('/notify status'), ' - Check current status'),
                        Text(Code('/notify'), ' - Check current status (default)'),
                        marker='• ',
                    ),
                    sep='\n',
                ).as_markdown()
            )
            return

        # Get selected agent
        if not identity.selected_agent:
            await message.answer(
                Text('❌ No agent selected. Use /switch_agent to select one.').as_markdown()
            )
            return

        agent_id = identity.selected_agent

        if subcommand == 'status':
            await handle_notify_status(message, agent_id)
        elif subcommand == 'enable':
            await handle_notify_enable(message, agent_id, str(message.from_user.id))
        elif subcommand == 'disable':
            await handle_notify_disable(message, agent_id)


    LOGGER.info('Notification handlers initialized')
    return router


async def handle_notify_status(message: Message, agent_id: str) -> None:
    """Check scheduling and notification tools status for the agent."""
    try:
        # Check if tools are attached
        tools = await client.agents.tools.list(agent_id=agent_id)
        schedule_tool_attached = any(t.name == 'schedule_message' for t in tools)
        notify_tool_attached = any(t.name == 'notify_via_telegram' for t in tools)

        # Check environment variables
        agent = await client.agents.retrieve(agent_id=agent_id)
        env_vars = agent.tool_exec_environment_variables or []

        # Scheduling env vars
        has_letta_key = any(
            v.key == 'LETTA_API_KEY' for v in env_vars if hasattr(v, 'key')
        )
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

        await message.answer(
            as_list(
                Text(overall_status, ' ', Bold('Agent Communication Status')),
                '',
                Text(Bold('Agent: '), agent.name),
                '',
                Text(Bold('📅 Scheduling (schedule_message):')),
                Text(
                    '  Tool attached: ', '✅ Yes' if schedule_tool_attached else '❌ No'
                ),
                Text(
                    '  Environment configured: ',
                    '✅ Yes' if schedule_configured else '❌ No',
                ),
                '',
                Text(Bold('📢 Notifications (notify_via_telegram):')),
                Text(
                    '  Tool attached: ', '✅ Yes' if notify_tool_attached else '❌ No'
                ),
                Text(
                    '  Environment configured: ',
                    '✅ Yes' if notify_configured else '❌ No',
                ),
                '',
                Text('Use ', Code('/notify enable'), ' to set up both tools.'),
                sep='\n',
            ).as_markdown()
        )

    except Exception as e:
        LOGGER.error(f'Error checking notification status: {e}')
        await message.answer(Text('❌ Error checking status: ', str(e)).as_markdown())

async def handle_notify_enable(message: Message, agent_id: str, chat_id: str) -> None:
    """Enable scheduling and notifications for the agent."""
    try:
        # Check if Scheduler API key is configured
        if not CONFIG.scheduler_api_key:
            await message.answer(
                Text(
                    '❌ Scheduled messages require SCHEDULER_API_KEY to be configured. '
                    'Please contact the administrator.'
                ).as_markdown()
            )
            return

        agent = await client.agents.retrieve(agent_id=agent_id)

        # Send initial status message
        status_message = await message.answer(
            Text(
                '🔧 Setting up communication tools for ', Bold(agent.name), '...'
            ).as_markdown()
        )

        # STEP 1: Enable Scheduling (schedule_message)
        await status_message.edit_text(
            Text('📅 Configuring ', Code('schedule_message'), ' tool...').as_markdown()
        )
        await _enable_schedule_tool(agent_id)

        # STEP 2: Enable Notifications (notify_via_telegram)
        await status_message.edit_text(
            Text('📢 Configuring ', Code('notify_via_telegram'), ' tool...').as_markdown()
        )
        await _enable_notify_tool(agent_id, chat_id)

        # STEP 3: Attach Memory Block (agent_communication_tools_memo)
        await status_message.edit_text(
            Text('📝 Attaching tool guidance memory block...').as_markdown()
        )
        await _attach_tool_memory_block(agent_id)

        # Final success message
        await status_message.edit_text(
            Text(
                '✅ Communication tools enabled for ',
                Bold(agent.name),
                '\n\n• ',
                Code('schedule_message'),
                ' - Agent can schedule delayed messages',
                '\n• ',
                Code('notify_via_telegram'),
                ' - Agent can send you notifications',
                '\n• ',
                'Tool guidance memory block attached',
            ).as_markdown()
        )

    except Exception as e:
        LOGGER.error(f'Error enabling communication tools: {e}')
        await message.answer(Text('❌ Error enabling tools: ', str(e)).as_markdown())

async def _enable_schedule_tool(agent_id: str) -> None:
    """Enable schedule_message tool - completely separate logic."""
    # Check if tool exists and register/attach it
    schedule_tool = await register_schedule_message_tool()

    # Attach tool if not already attached
    attached_tools = await client.agents.tools.list(agent_id=agent_id)
    if schedule_tool.id and not any(t.id == schedule_tool.id for t in attached_tools):
        await client.agents.tools.attach(agent_id=agent_id, tool_id=schedule_tool.id)
        LOGGER.info(
            f'Attached schedule_message tool {schedule_tool.id} to agent {agent_id}'
        )

    # Set up environment variables for scheduling
    agent = await client.agents.retrieve(agent_id=agent_id)
    current_env_vars = agent.tool_exec_environment_variables or []

    env_dict: dict[str, str | None] = {
        var.key: var.value
        for var in current_env_vars
        if hasattr(var, 'key') and hasattr(var, 'value') and var.value is not None
    }

    # Add scheduling env vars
    env_dict['LETTA_API_KEY'] = CONFIG.letta_api_key
    env_dict['SCHEDULER_URL'] = CONFIG.scheduler_url
    env_dict['SCHEDULER_API_KEY'] = CONFIG.scheduler_api_key
    env_dict['AGENT_ID'] = agent_id

    await client.agents.modify(
        agent_id=agent_id, tool_exec_environment_variables=env_dict
    )

async def _enable_notify_tool(agent_id: str, chat_id: str) -> None:
    """Enable notify_via_telegram tool - completely separate logic."""
    # Check if tool exists and register/attach it
    notify_tool = await register_notify_tool()

    # Attach tool if not already attached
    attached_tools = await client.agents.tools.list(agent_id=agent_id)
    if notify_tool.id and not any(t.id == notify_tool.id for t in attached_tools):
        await client.agents.tools.attach(agent_id=agent_id, tool_id=notify_tool.id)
        LOGGER.info(
            f'Attached notify_via_telegram tool {notify_tool.id} to agent {agent_id}'
        )

    # Set up environment variables for notifications
    agent = await client.agents.retrieve(agent_id=agent_id)
    current_env_vars = agent.tool_exec_environment_variables or []

    env_dict: dict[str, str | None] = {
        var.key: var.value
        for var in current_env_vars
        if hasattr(var, 'key') and hasattr(var, 'value') and var.value is not None
    }

    # Add notification env vars
    env_dict['TELEGRAM_BOT_TOKEN'] = CONFIG.bot_token
    env_dict['TELEGRAM_CHAT_ID'] = chat_id

    await client.agents.modify(
        agent_id=agent_id, tool_exec_environment_variables=env_dict
    )

async def handle_notify_disable(message: Message, agent_id: str) -> None:
    """Disable scheduling and notifications for the agent."""
    try:
        agent = await client.agents.retrieve(agent_id=agent_id)

        # Send initial status message
        status_message = await message.answer(
            Text(
                '🔧 Disabling communication tools for ', Bold(agent.name), '...'
            ).as_markdown()
        )

        # STEP 1: Disable Scheduling (schedule_message)
        await status_message.edit_text(
            Text('📅 Removing ', Code('schedule_message'), ' tool...').as_markdown()
        )
        await _disable_schedule_tool(agent_id)

        # STEP 2: Disable Notifications (notify_via_telegram)
        await status_message.edit_text(
            Text('📢 Removing ', Code('notify_via_telegram'), ' tool...').as_markdown()
        )
        await _disable_notify_tool(agent_id)

        # STEP 3: Detach Memory Block (agent_communication_tools_memo)
        await status_message.edit_text(
            Text('📝 Removing tool guidance memory block...').as_markdown()
        )
        await _detach_tool_memory_block(agent_id)

        # Final success message
        await status_message.edit_text(
            Text('✅ Communication tools disabled for ', Bold(agent.name)).as_markdown()
        )

    except Exception as e:
        LOGGER.error(f'Error disabling communication tools: {e}')
        await message.answer(Text('❌ Error disabling tools: ', str(e)).as_markdown())

async def _disable_schedule_tool(agent_id: str) -> None:
    """Disable schedule_message tool - completely separate logic."""
    # Detach the tool
    attached_tools = await client.agents.tools.list(agent_id=agent_id)
    schedule_tool = next(
        (t for t in attached_tools if t.name == 'schedule_message'), None
    )

    if schedule_tool and schedule_tool.id:
        await client.agents.tools.detach(agent_id=agent_id, tool_id=schedule_tool.id)
        LOGGER.info(f'Detached schedule_message tool from agent {agent_id}')

    # Remove environment variables
    agent = await client.agents.retrieve(agent_id=agent_id)
    current_env_vars = agent.tool_exec_environment_variables or []

    filtered_vars: dict[str, str | None] = {
        var.key: var.value
        for var in current_env_vars
        if hasattr(var, 'key')
        and hasattr(var, 'value')
        and var.value is not None
        and var.key not in ('LETTA_API_KEY', 'SCHEDULER_URL', 'SCHEDULER_API_KEY', 'AGENT_ID')
    }
    await client.agents.modify(
        agent_id=agent_id, tool_exec_environment_variables=filtered_vars
    )

async def _disable_notify_tool(agent_id: str) -> None:
    """Disable notify_via_telegram tool - completely separate logic."""
    # Detach the tool
    attached_tools = await client.agents.tools.list(agent_id=agent_id)
    notify_tool = next(
        (t for t in attached_tools if t.name == 'notify_via_telegram'), None
    )

    if notify_tool and notify_tool.id:
        await client.agents.tools.detach(agent_id=agent_id, tool_id=notify_tool.id)
        LOGGER.info(f'Detached notify_via_telegram tool from agent {agent_id}')

    # Remove environment variables
    agent = await client.agents.retrieve(agent_id=agent_id)
    current_env_vars = agent.tool_exec_environment_variables or []

    filtered_vars: dict[str, str | None] = {
        var.key: var.value
        for var in current_env_vars
        if hasattr(var, 'key')
        and hasattr(var, 'value')
        and var.value is not None
        and var.key not in ('TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID')
    }

    await client.agents.modify(
        agent_id=agent_id, tool_exec_environment_variables=filtered_vars
    )

async def _attach_tool_memory_block(agent_id: str) -> None:
    """Attach proactive messaging protocol memory block to agent."""
    try:
        # Check if block with this label already exists on agent
        existing_blocks = await client.agents.blocks.list(agent_id=agent_id)
        block_exists = any(
            b.label == NOTIFICATION_TOOL_BLOCK_LABEL for b in existing_blocks
        )

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
            label=NOTIFICATION_TOOL_BLOCK_LABEL, value=block_content
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
        # List agent's blocks and find the one with our label
        existing_blocks = await client.agents.blocks.list(agent_id=agent_id)
        target_block = next(
            (b for b in existing_blocks if b.label == NOTIFICATION_TOOL_BLOCK_LABEL),
            None,
        )

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
