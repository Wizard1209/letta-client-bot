"""Shared Letta client instance and Letta API operations.

This module provides:
1. A single Letta client instance used across the application
2. Pure Letta API operations (identity, agent, tool management)

Isolating the client here prevents circular import issues.
"""

import logging
from pathlib import Path

from letta_client import AsyncLetta as LettaClient
from letta_client.core.api_error import ApiError
from letta_client.types.identity import Identity
from letta_client.types.tool import Tool

from letta_bot.config import CONFIG

# Single shared client instance
client = LettaClient(project=CONFIG.letta_project, token=CONFIG.letta_api_key)
LOGGER = logging.getLogger(__name__)


# =============================================================================
# Identity Management
# =============================================================================


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
            # TODO: Now list works properly only with project_id specified
            projects_list = (await client.projects.list(name=CONFIG.letta_project)).projects
            project_id = projects_list[0].id
            identities = await client.identities.list(
                identifier_key=identifier_key, project_id=project_id
            )

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


# =============================================================================
# Agent Management
# =============================================================================


async def create_agent_from_template(template_id: str, identity_id: str) -> None:
    """Create agent from template in Letta API. Returns agent object."""
    # Local import to avoid circular dependency
    from letta_bot.agent import RequestNewAgentCallback

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


async def get_default_agent(identity_id: str) -> str:
    """Get the oldest agent for a given identity.

    Args:
        identity_id: The Letta identity ID

    Returns:
        Agent ID of the oldest agent

    Raises:
        IndexError: If no agents exist for the identity
    """
    result = await client.identities.agents.list(
        identity_id=identity_id, limit=1, order='asc'
    )
    return result[0].id


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

    return await client.tools.create(
        source_code=source_code,
        tags=['telegram', 'notification', 'messaging'],
    )
