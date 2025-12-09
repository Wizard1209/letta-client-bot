"""Tool management: attach, detach, and configure tools for agents."""

from enum import Enum
import hashlib
import logging
from pathlib import Path
from typing import NamedTuple

from aiogram import Router
from aiogram.filters.callback_data import CallbackData
from aiogram.filters.command import Command
from aiogram.types import CallbackQuery, InaccessibleMessage, Message
from aiogram.utils.formatting import Bold, Code, Text, as_list
from aiogram.utils.keyboard import InlineKeyboardBuilder
from letta_client.types.agent_state import AgentState

from letta_bot.client import client, register_notify_tool, register_schedule_message_tool
from letta_bot.config import CONFIG
from letta_bot.queries.get_identity_async_edgeql import GetIdentityResult
from letta_bot.utils import version_needs_update

LOGGER = logging.getLogger(__name__)

# Memory block configuration (must be before functions that use them)
NOTIFICATION_TOOL_BLOCK_LABEL = 'proactive_messaging_protocol'
NOTIFICATION_TOOL_BLOCK_VERSION = '1.1.1'
NOTIFICATION_MEMORY_BLOCK_DESC = (
    'How to use scheduling and notification tools to enable proactive behavior: '
    'scheduling reminders and follow-ups, sending notifications at specific times '
    'across timezones, creating recurring check-ins, understanding conversational '
    'vs silent communication modes, context preservation, and timing verification'
)


# =============================================================================
# Status NamedTuple
# =============================================================================


class ToolUpdateStatus(NamedTuple):
    """Update status for a tool (code and env vars)."""

    code_match: bool
    env_match: bool


# =============================================================================
# Connection Check Functions
# =============================================================================


def _is_schedule_connected(agent: AgentState) -> bool:
    """Check if schedule_message tool is attached."""
    tools = agent.tools or []
    return any(t.name == 'schedule_message' for t in tools)


def _is_notify_connected(agent: AgentState) -> bool:
    """Check if notify_via_telegram tool is attached."""
    tools = agent.tools or []
    return any(t.name == 'notify_via_telegram' for t in tools)


def _is_memory_block_exists(agent: AgentState) -> bool:
    """Check if proactive messaging memory block exists."""
    blocks = agent.blocks or []
    return any(b.label == NOTIFICATION_TOOL_BLOCK_LABEL for b in blocks)


def _get_identity_count(agent: AgentState) -> int:
    """Count telegram identities (tg-* format)."""
    identities = agent.identities or []
    return sum(1 for i in identities if (i.identifier_key or '').startswith('tg-'))


# =============================================================================
# Update Check Functions (only call if connected)
# =============================================================================


def _compute_code_hash(source_code: str) -> str:
    """Compute hash of source code for comparison."""
    return hashlib.sha256(source_code.encode()).hexdigest()


def _check_code_match(agent: AgentState, tool_name: str) -> bool:
    """Check if tool source code matches local file."""
    tools = agent.tools or []
    tool = next((t for t in tools if t.name == tool_name), None)
    if not tool or not tool.source_code:
        return False
    local_code = _load_tool_code(tool_name)
    return _compute_code_hash(tool.source_code) == _compute_code_hash(local_code)


def _check_schedule_current(agent: AgentState) -> ToolUpdateStatus:
    """Check if schedule_message tool code and env vars are current."""
    env_vars = agent.tool_exec_environment_variables or []
    env_dict = {v.key: v.value for v in env_vars}

    code_match = _check_code_match(agent, 'schedule_message')
    env_match = (
        env_dict.get('LETTA_API_KEY') == CONFIG.letta_api_key
        and env_dict.get('SCHEDULER_URL') == CONFIG.scheduler_url
        and env_dict.get('SCHEDULER_API_KEY') == CONFIG.scheduler_api_key
        and env_dict.get('AGENT_ID') == agent.id
    )

    return ToolUpdateStatus(code_match=code_match, env_match=env_match)


def _check_notify_current(agent: AgentState) -> ToolUpdateStatus:
    """Check if notify_via_telegram tool code and env vars are current."""
    env_vars = agent.tool_exec_environment_variables or []
    env_dict = {v.key: v.value for v in env_vars}

    code_match = _check_code_match(agent, 'notify_via_telegram')
    env_match = env_dict.get('TELEGRAM_BOT_TOKEN') == CONFIG.bot_token

    return ToolUpdateStatus(code_match=code_match, env_match=env_match)


def _check_memory_current(agent: AgentState) -> bool:
    """Check if memory block version is current."""
    blocks = agent.blocks or []
    for block in blocks:
        if block.label == NOTIFICATION_TOOL_BLOCK_LABEL:
            raw_version = (block.metadata or {}).get('version')
            current_version = str(raw_version) if raw_version else None
            needs_update = version_needs_update(
                current_version, NOTIFICATION_TOOL_BLOCK_VERSION
            )
            return not needs_update
    return False


# =============================================================================
# Code Loading Helper
# =============================================================================


def _load_tool_code(tool_name: str) -> str:
    """Load tool source code by name."""
    path = Path(__file__).parent / 'custom_tools' / f'{tool_name}.py'
    return path.read_text(encoding='utf-8')


class NotifyAction(str, Enum):
    """Actions for notify callback."""

    ENABLE = 'enable'
    DISABLE = 'disable'
    UPDATE = 'update'


class NotifyCallback(CallbackData, prefix='notify'):
    """Callback data for notification buttons."""

    action: NotifyAction


def _load_memory_block_content() -> str:
    """Load memory block content from markdown file."""
    memo_path = (
        Path(__file__).parent
        / 'custom_tools'
        / 'memory_blocks'
        / 'proactive_messaging_protocol.md'
    )
    return memo_path.read_text(encoding='utf-8')


tools_router = Router(name=f'{__name__}.commands')


@tools_router.message(Command('notify'), flags={'require_identity': True})
async def notify_command(message: Message, identity: GetIdentityResult) -> None:
    """Handle /notify command - manage proactive assistant behavior."""
    if not message.from_user:
        return

    if not identity.selected_agent:
        await message.answer(
            Text('❌ No assistant selected. Use /switch to select one.').as_markdown()
        )
        return

    # Show checking message first, then edit with status
    status_msg = await message.answer(Text('🔍 Checking status...').as_markdown())
    await handle_notify_status(status_msg, identity.selected_agent)


@tools_router.callback_query(NotifyCallback.filter(), flags={'require_identity': True})
async def handle_notify_callback(
    callback: CallbackQuery,
    callback_data: NotifyCallback,
    identity: GetIdentityResult,
) -> None:
    """Handle notify button clicks."""
    if not callback.from_user:
        return

    if isinstance(callback.message, InaccessibleMessage) or not callback.message:
        await callback.answer('Message expired. Use /notify again.')
        return

    if not identity.selected_agent:
        await callback.answer('No assistant selected.')
        return

    await callback.answer()

    match callback_data.action:
        case NotifyAction.ENABLE:
            await handle_notify_enable(callback.message, identity.selected_agent)
        case NotifyAction.DISABLE:
            await handle_notify_disable(callback.message, identity.selected_agent)
        case NotifyAction.UPDATE:
            await handle_notify_update(callback.message, identity.selected_agent)


async def handle_notify_status(message: Message, agent_id: str) -> None:
    """Check proactive behavior status for the agent.

    Flow:
    1. Retrieve agent state (single API call)
    2. Check if connected (any tools attached)
    3. If connected → show "Checking for updates..." → compare code/env/version
    4. Display status with appropriate action buttons
    """
    try:
        # Step 1: Retrieve agent state
        agent = await client.agents.retrieve(agent_id=agent_id)

        # Step 2: Check connection status
        schedule_connected = _is_schedule_connected(agent)
        notify_connected = _is_notify_connected(agent)
        memory_exists = _is_memory_block_exists(agent)
        identity_count = _get_identity_count(agent)

        any_connected = schedule_connected or notify_connected or memory_exists

        # Step 3: If connected, check for updates
        schedule_update: ToolUpdateStatus | None = None
        notify_update: ToolUpdateStatus | None = None
        memory_current: bool | None = None

        if any_connected:
            await message.edit_text(Text('🔄 Checking for updates...').as_markdown())

            if schedule_connected:
                schedule_update = _check_schedule_current(agent)
            if notify_connected:
                notify_update = _check_notify_current(agent)
            if memory_exists:
                memory_current = _check_memory_current(agent)

        # Step 4: Display status with buttons
        await _display_notify_status(
            message,
            agent,
            schedule_connected,
            notify_connected,
            memory_exists,
            identity_count,
            schedule_update,
            notify_update,
            memory_current,
        )

    except Exception as e:
        LOGGER.error(f'Error checking notification status: {e}')
        await message.edit_text(Text('❌ Error checking status: ', str(e)).as_markdown())


def _get_status_icon(
    connected: bool, update_status: ToolUpdateStatus | ToolUpdateStatus | None
) -> str:
    """Get status icon based on connection and update status.

    Returns:
        ❌ = not connected
        🔄 = connected, update available (code or env mismatch)
        ✅ = connected and current
    """
    if not connected:
        return '❌'
    if update_status is None:
        return '❌'  # Shouldn't happen, but safe fallback
    if update_status.code_match and update_status.env_match:
        return '✅'
    return '🔄'


def _get_memory_block_version(agent: AgentState) -> str | None:
    """Get the current version of the memory block on agent, or None if not found."""
    blocks = agent.blocks or []
    for block in blocks:
        if block.label == NOTIFICATION_TOOL_BLOCK_LABEL:
            raw_version = (block.metadata or {}).get('version')
            return str(raw_version) if raw_version else None
    return None


async def _display_notify_status(
    message: Message,
    agent: AgentState,
    schedule_connected: bool,
    notify_connected: bool,
    memory_exists: bool,
    identity_count: int,
    schedule_update: ToolUpdateStatus | None,
    notify_update: ToolUpdateStatus | None,
    memory_current: bool | None,
) -> None:
    """Display proactive mode status with action buttons.

    Icons:
        ❌ = not connected
        🔄 = connected, update available
        ✅ = connected and current

    Buttons:
        Enable = if any ❌
        Disable = if any ✅
        Update = if any 🔄
    """
    # Determine status icons
    schedule_icon = _get_status_icon(schedule_connected, schedule_update)
    notify_icon = _get_status_icon(notify_connected, notify_update)

    # Memory block icon
    if not memory_exists:
        memory_icon = '❌'
    elif memory_current:
        memory_icon = '✅'
    else:
        memory_icon = '🔄'

    # Collect all icons to determine buttons
    all_icons = [schedule_icon, notify_icon, memory_icon]
    has_cross = '❌' in all_icons
    has_check = '✅' in all_icons
    has_update = '🔄' in all_icons

    # Overall status
    if all(icon == '✅' for icon in all_icons):
        overall_icon = '✅'
    elif has_update or has_cross:
        overall_icon = '⚠️'
    else:
        overall_icon = '❌'

    # Build buttons based on icons
    builder = InlineKeyboardBuilder()
    if has_cross:
        builder.button(
            text='✅ Enable', callback_data=NotifyCallback(action=NotifyAction.ENABLE)
        )
    if has_check:
        builder.button(
            text='❌ Disable', callback_data=NotifyCallback(action=NotifyAction.DISABLE)
        )
    if has_update:
        builder.button(
            text='🔄 Update', callback_data=NotifyCallback(action=NotifyAction.UPDATE)
        )
    builder.adjust(3)

    # Render status display
    await message.edit_text(
        _render_status(
            overall_icon=overall_icon,
            agent_name=agent.name,
            schedule_connected=schedule_connected,
            schedule_update=schedule_update,
            notify_connected=notify_connected,
            notify_update=notify_update,
            identity_count=identity_count,
            memory_exists=memory_exists,
            memory_current=memory_current,
            current_memory_version=_get_memory_block_version(agent),
        ),
        reply_markup=builder.as_markup(),
    )


def _render_tool_status(update: ToolUpdateStatus) -> Text:
    """Render code/env status line for a tool."""
    code_icon = '✅' if update.code_match else '🔄'
    env_icon = '✅' if update.env_match else '🔄'
    return Text('   code: ', code_icon, '  env: ', env_icon)


def _render_memory_status(
    exists: bool,
    current: bool | None,
    current_version: str | None,
) -> Text:
    """Render memory block status line."""
    if not exists:
        return Text('   ❌ not attached')

    target = NOTIFICATION_TOOL_BLOCK_VERSION
    if current:
        return Text('   ✅ v', target)

    # Version mismatch
    current_str = f'v{current_version}' if current_version else 'unknown'
    return Text('   🔄 ', current_str, ' → v', target)


def _render_status(
    *,
    overall_icon: str,
    agent_name: str,
    schedule_connected: bool,
    schedule_update: ToolUpdateStatus | None,
    notify_connected: bool,
    notify_update: ToolUpdateStatus | None,
    identity_count: int,
    memory_exists: bool,
    memory_current: bool | None,
    current_memory_version: str | None,
) -> str:
    """Render the full proactive mode status message."""
    # Header
    lines: list[Text | str] = [
        Text(overall_icon, ' ', Bold('Proactive Mode')),
        '',
        Text(Bold('Agent: '), agent_name),
        '',
    ]

    # Scheduler section
    lines.append(Text('📅 ', Bold('Scheduler')))
    if schedule_connected and schedule_update:
        lines.append(_render_tool_status(schedule_update))
    else:
        lines.append(Text('   ❌ not connected'))
    lines.append('')

    # Notifier section
    users_suffix = f' ({identity_count} users)' if identity_count > 0 else ''
    lines.append(Text('📢 ', Bold('Notifier'), users_suffix))
    if notify_connected and notify_update:
        lines.append(_render_tool_status(notify_update))
    else:
        lines.append(Text('   ❌ not connected'))
    lines.append('')

    # Guidelines section
    lines.append(Text('📝 ', Bold('Guidelines')))
    lines.append(
        _render_memory_status(memory_exists, memory_current, current_memory_version)
    )

    return as_list(*lines, sep='\n').as_markdown()


async def handle_notify_enable(message: Message, agent_id: str) -> None:
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
        await _enable_notify_tool(agent_id)

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


async def handle_notify_update(message: Message, agent_id: str) -> None:
    """Update proactive tools by re-enabling (disable + enable)."""
    await message.edit_text(Text('🔄 Updating tools...').as_markdown())
    await handle_notify_disable(message, agent_id)
    await handle_notify_enable(message, agent_id)


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


async def _enable_notify_tool(agent_id: str) -> None:
    """Enable notify_via_telegram tool.

    Note: Tool uses agent_state injection to get telegram IDs from identities,
    so only TELEGRAM_BOT_TOKEN env var is needed.
    """
    notify_tool = await register_notify_tool()

    # Attach tool if not already attached
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

    # Set up environment variable for bot token
    agent = await client.agents.retrieve(agent_id=agent_id)
    current_env_vars = agent.tool_exec_environment_variables or []

    env_dict: dict[str, str] = {
        var.key: var.value
        for var in current_env_vars
        if hasattr(var, 'key') and hasattr(var, 'value') and var.value is not None
    }

    env_dict['TELEGRAM_BOT_TOKEN'] = CONFIG.bot_token

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
    """Disable notify_via_telegram tool."""
    # Detach the tool
    notify_tool = None
    async for tool in client.agents.tools.list(agent_id=agent_id):
        if tool.name == 'notify_via_telegram':
            notify_tool = tool
            break

    if notify_tool and notify_tool.id:
        await client.agents.tools.detach(agent_id=agent_id, tool_id=notify_tool.id)
        LOGGER.info(f'Detached notify_via_telegram tool from agent {agent_id}')

    # Remove environment variable
    agent = await client.agents.retrieve(agent_id=agent_id)
    current_env_vars = agent.tool_exec_environment_variables or []

    filtered_vars: dict[str, str] = {
        var.key: var.value
        for var in current_env_vars
        if hasattr(var, 'key')
        and hasattr(var, 'value')
        and var.value is not None
        and var.key != 'TELEGRAM_BOT_TOKEN'
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

        # Create new memory block with version metadata
        block = await client.blocks.create(
            label=NOTIFICATION_TOOL_BLOCK_LABEL,
            description=NOTIFICATION_MEMORY_BLOCK_DESC,
            value=block_content,
            metadata={'version': NOTIFICATION_TOOL_BLOCK_VERSION},
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
