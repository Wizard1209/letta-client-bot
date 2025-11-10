"""Telegram notification tool management handlers."""

import logging

from aiogram import Bot, Router
from aiogram.filters.command import Command
from aiogram.types import Message
from aiogram.utils.formatting import Bold, Code, Text, as_list, as_marked_section
from gel import AsyncIOExecutor as GelClient

from letta_bot.auth import require_identity
from letta_bot.client import client, register_notify_tool
from letta_bot.config import CONFIG
from letta_bot.queries.get_identity_async_edgeql import GetIdentityResult

LOGGER = logging.getLogger(__name__)


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

    async def handle_notify_status(message: Message, agent_id: str) -> None:
        """Check notification tool status for the agent."""
        try:
            # Check if tool is attached
            tools = await client.agents.tools.list(agent_id=agent_id)
            notify_tool_attached = any(t.name == 'notify_via_telegram' for t in tools)

            # Check environment variables
            agent = await client.agents.retrieve(agent_id=agent_id)
            env_vars = agent.tool_exec_environment_variables or []

            has_bot_token = any(
                v.key == 'TELEGRAM_BOT_TOKEN' for v in env_vars if hasattr(v, 'key')
            )
            has_chat_id = any(
                v.key == 'TELEGRAM_CHAT_ID' for v in env_vars if hasattr(v, 'key')
            )

            status_emoji = (
                '✅' if (notify_tool_attached and has_bot_token and has_chat_id) else '❌'
            )

            await message.answer(
                as_list(
                    Text(status_emoji, ' ', Bold('Telegram Notifications Status')),
                    '',
                    Text(Bold('Agent: '), agent.name),
                    Text(
                        Bold('Tool attached: '),
                        '✅ Yes' if notify_tool_attached else '❌ No',
                    ),
                    Text(
                        Bold('Environment configured: '),
                        '✅ Yes' if (has_bot_token and has_chat_id) else '❌ No',
                    ),
                    '',
                    Text('Use ', Code('/notify enable'), ' to set up notifications.'),
                    sep='\n',
                ).as_markdown()
            )

        except Exception as e:
            LOGGER.error(f'Error checking notification status: {e}')
            await message.answer(Text('❌ Error checking status: ', str(e)).as_markdown())

    async def handle_notify_enable(
        message: Message, agent_id: str, chat_id: str
    ) -> None:
        """Enable notifications for the agent."""
        try:
            # Step 1: Check if tool exists and register/attach it
            all_tools = await client.tools.list(name='notify_via_telegram')

            if not all_tools:
                # Register new tool from source
                LOGGER.info('Registering notify_via_telegram tool from source')
                await message.answer(
                    Text('🔧 Registering notify_via_telegram tool').as_markdown()
                )
                notify_tool = await register_notify_tool()
                await message.answer(Text('✅ Tool registered successfully!').as_markdown())
            else:
                notify_tool = all_tools[0]
                LOGGER.info(f'Using existing tool: {notify_tool.id}')

            # Check if already attached
            attached_tools = await client.agents.tools.list(agent_id=agent_id)
            if not any(t.id == notify_tool.id for t in attached_tools):
                await client.agents.tools.attach(agent_id=agent_id, tool_id=notify_tool.id)
                LOGGER.info(f'Attached tool {notify_tool.id} to agent {agent_id}')

            # Step 2: Set up environment variables
            agent = await client.agents.retrieve(agent_id=agent_id)
            current_env_vars = agent.tool_exec_environment_variables or []

            # Convert to dict, filtering out None values
            env_dict: dict[str, str | None] = {
                var.key: var.value
                for var in current_env_vars
                if hasattr(var, 'key') and hasattr(var, 'value') and var.value is not None
            }

            # Add Telegram env vars
            env_dict['TELEGRAM_BOT_TOKEN'] = CONFIG.bot_token
            env_dict['TELEGRAM_CHAT_ID'] = chat_id

            # Update agent
            await client.agents.modify(
                agent_id=agent_id, tool_exec_environment_variables=env_dict
            )

            await message.answer(
                Text(
                    '✅ Notifications enabled for ',
                    Bold(agent.name),
                    '\n\nAgent can now send you messages using ',
                    Code('notify_via_telegram'),
                    ' tool',
                ).as_markdown()
            )

        except Exception as e:
            LOGGER.error(f'Error enabling notifications: {e}')
            await message.answer(
                Text('❌ Error enabling notifications: ', str(e)).as_markdown()
            )

    async def handle_notify_disable(message: Message, agent_id: str) -> None:
        """Disable notifications for the agent."""
        try:
            # Step 1: Detach the tool
            attached_tools = await client.agents.tools.list(agent_id=agent_id)
            notify_tool = next(
                (t for t in attached_tools if t.name == 'notify_via_telegram'), None
            )

            if notify_tool:
                tool_id = notify_tool.id
                if not tool_id:
                    LOGGER.warning('notify_via_telegram tool has no ID')
                    return
                await client.agents.tools.detach(agent_id=agent_id, tool_id=tool_id)

            # Step 2: Remove environment variables
            agent = await client.agents.retrieve(agent_id=agent_id)
            current_env_vars = agent.tool_exec_environment_variables or []

            # Filter out Telegram env vars and None values
            filtered_vars: dict[str, str | None] = {
                var.key: var.value
                for var in current_env_vars
                if hasattr(var, 'key')
                and hasattr(var, 'value')
                and var.value is not None
                and var.key not in ('TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID')
            }

            # Update agent
            await client.agents.modify(
                agent_id=agent_id, tool_exec_environment_variables=filtered_vars
            )

            await message.answer(
                Text(
                    '✅ Notifications disabled for ', Bold(agent.name)
                ).as_markdown()
            )

        except Exception as e:
            LOGGER.error(f'Error disabling notifications: {e}')
            await message.answer(
                Text('❌ Error disabling notifications: ', str(e)).as_markdown()
            )

    LOGGER.info('Notification handlers initialized')
    return router
