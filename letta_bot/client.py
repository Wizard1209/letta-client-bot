"""Shared Letta client instance and Letta API operations.

This module provides:
1. A single Letta client instance used across the application
2. Pure Letta API operations (identity, agent, tool management)

Isolating the client here prevents circular import issues.
"""

import logging
from pathlib import Path

from letta_client import APIError, AsyncLetta as LettaClient, ConflictError
from letta_client.types.identity import Identity
from letta_client.types.tool import Tool

from letta_bot.config import CONFIG

LETTA_CLIENT_TIMEOUT = 120

# Single shared client instance
client = LettaClient(
    project_id=CONFIG.letta_project_id,
    api_key=CONFIG.letta_api_key,
    timeout=LETTA_CLIENT_TIMEOUT,
)
LOGGER = logging.getLogger(__name__)


# =============================================================================
# Identity Management
# =============================================================================


async def get_or_create_letta_identity(identifier_key: str, name: str) -> Identity:
    """Create identity in Letta API with retry logic.

    Returns identity object with .id attribute.

    States:
    1. Attempt retrieval by identifier_key
    2. If fails, attempt creation
    3. If creation also fails, raise error
    """
    try:
        # List identities by identifier_key
        # Note: Client is already configured with project, so it auto-scopes
        # New pagination API: await to get page, then access .items
        page = await client.identities.list(
            project_id=CONFIG.letta_project_id, identifier_key=identifier_key
        )
        identities = page.items

        if identities:
            identity = identities[0]
            LOGGER.info(f'Retrieved existing identity: {identity.id}')
            return identity

        LOGGER.info(f'No identity found for {identifier_key}')
        # Create identity if not existed
        identity = await client.identities.create(
            identifier_key=identifier_key,
            name=name,
            identity_type='user',
        )
        LOGGER.info(f'Created identity: {identity.id}')
        return identity
    except ConflictError:
        LOGGER.critical(
            f'Identity already exists but couldnt be retrieved {identifier_key}'
        )
        raise
    except APIError:
        LOGGER.critical(f'Identity creation and retrieval failed: {identifier_key}')
        raise


# =============================================================================
# Agent Management
# =============================================================================


async def create_agent_from_template(template_id: str, identity_id: str) -> None:
    """Create agent from template in Letta API."""
    # Local import to avoid circular dependency
    from letta_bot.agent import RequestNewAgentCallback

    info = RequestNewAgentCallback.unpack(template_id)

    # Use new templates.agents.create() API
    # Client is already configured with project, so it auto-scopes
    template_version = f'{info.template_name}:{info.version}'

    # TODO: mb tags for creator, mb custom name
    await client.templates.agents.create(
        template_version=template_version, identity_ids=[identity_id]
    )


async def get_default_agent(identity_id: str) -> str:
    """Get the oldest agent for a given identity.

    Args:
        identity_id: The Letta identity ID

    Returns:
        Agent ID of the oldest agent

    Raises:
        IndexError: If no agents exist for the identity
    """
    # New pagination API: await to get page, then access .items
    page = await client.identities.agents.list(
        identity_id=identity_id, limit=1, order='asc'
    )
    return page.items[0].id


# =============================================================================
# Tool Management
# =============================================================================


async def register_notify_tool() -> Tool:
    """Register the notify_via_telegram tool with Letta from source file.

    Returns:
        The registered tool object

    Raises:
        Exception: If tool registration fails
    """
    tool_file = Path(__file__).parent / 'custom_tools' / 'notify_via_telegram.py'
    source_code = tool_file.read_text()

    return await client.tools.upsert(
        source_code=source_code,
        tags=['telegram', 'notification', 'messaging'],
        default_requires_approval=False,
    )


async def register_schedule_message_tool() -> Tool:
    """Register the schedule_message tool with Letta from source file.

    Returns:
        The registered tool object

    Raises:
        Exception: If tool registration fails
    """
    tool_file = Path(__file__).parent / 'custom_tools' / 'schedule_message.py'
    source_code = tool_file.read_text()

    return await client.tools.upsert(
        source_code=source_code,
        tags=['telegram', 'scheduling', 'delayed-message'],
        default_requires_approval=False,
    )
