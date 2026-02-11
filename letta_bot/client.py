"""Shared Letta client instance and Letta API operations.

This module provides:
1. A single Letta client instance used across the application
2. Pure Letta API operations (agent, tool management)
3. Tag-based user-agent association (replaces Letta Identity API)

Isolating the client here prevents circular import issues.
"""

from collections.abc import AsyncIterator
from contextlib import suppress
import logging
from typing import BinaryIO

from letta_client import AsyncLetta as LettaClient, ConflictError, NotFoundError
from letta_client.types.agent_state import AgentState

from letta_bot.config import CONFIG


class LettaProcessingError(Exception):
    """Raised when Letta fails to process a file (parsing/embedding errors)."""

    pass


LETTA_CLIENT_TIMEOUT = 120

# Single shared client instance
client = LettaClient(
    project_id=CONFIG.letta_project_id,
    api_key=CONFIG.letta_api_key,
    timeout=LETTA_CLIENT_TIMEOUT,
)
LOGGER = logging.getLogger(__name__)


# =============================================================================
# Agent Management (Tag-Based)
# =============================================================================


async def create_agent_from_template(
    template_id: str, telegram_id: int, extra_tags: list[str] | None = None
) -> None:
    """Create agent from template in Letta API.

    Automatically adds identity, owner, and creator tags for the telegram user.
    """
    # Local import to avoid circular dependency
    from letta_bot.auth import NewAssistantCallback

    info = NewAssistantCallback.unpack(template_id)

    # Use new templates.agents.create() API
    template_version = f'{info.template_name}:{info.version}'

    # Build tags: identity (access), owner, and creator
    tags = [
        f'identity-tg-{telegram_id}',
        f'owner-tg-{telegram_id}',
        f'creator-tg-{telegram_id}',
    ]
    if extra_tags:
        tags.extend(extra_tags)

    await client.templates.agents.create(template_version=template_version, tags=tags)


async def list_agents_by_user(
    telegram_id: int,
    limit: int | None = None,
    order: str | None = None,
) -> AsyncIterator[AgentState]:
    """List all agents accessible to a telegram user.

    Args:
        telegram_id: Telegram user ID
        limit: Maximum number of agents to return
        order: Sort order ('asc' for oldest first, 'desc' for newest first)

    Yields:
        AgentState objects for each agent with identity-tg-{telegram_id} tag
    """
    identity_tag = f'identity-tg-{telegram_id}'
    async for agent in client.agents.list(tags=[identity_tag], limit=limit, order=order):
        yield agent


async def get_oldest_agent_by_user(telegram_id: int) -> str:
    """Get the oldest agent ID for a telegram user.

    Args:
        telegram_id: Telegram user ID

    Returns:
        Agent ID of the oldest agent

    Raises:
        IndexError: If no agents exist for the user
    """
    identity_tag = f'identity-tg-{telegram_id}'
    # Get first page with oldest agent (asc order)
    page = await client.agents.list(tags=[identity_tag], limit=1, order='asc')
    return page.items[0].id


async def add_user_to_agent(agent_id: str, telegram_id: int) -> None:
    """Grant a telegram user access to an agent by adding identity tag.

    Args:
        agent_id: The ID of the agent
        telegram_id: Telegram user ID to grant access

    Raises:
        APIError: If the update operation fails
    """
    agent = await client.agents.retrieve(agent_id=agent_id, include=['agent.tags'])
    existing_tags = list(agent.tags) if agent.tags else []

    identity_tag = f'identity-tg-{telegram_id}'
    if identity_tag not in existing_tags:
        await client.agents.update(agent_id=agent_id, tags=existing_tags + [identity_tag])


async def validate_agent_access(agent_id: str, telegram_id: int) -> AgentState | None:
    """Check if telegram user has access to agent.

    Args:
        agent_id: The ID of the agent
        telegram_id: Telegram user ID

    Returns:
        AgentState if user has access, None if not found or no access
    """
    try:
        agent = await client.agents.retrieve(agent_id=agent_id, include=['agent.tags'])
    except NotFoundError:
        return None

    identity_tag = f'identity-tg-{telegram_id}'
    if agent.tags and identity_tag in agent.tags:
        return agent

    return None


async def check_user_has_agent_access(agent_id: str, telegram_id: int) -> bool:
    """Check if telegram user has access to agent (lightweight version).

    Args:
        agent_id: The ID of the agent
        telegram_id: Telegram user ID

    Returns:
        True if user has access, False otherwise
    """
    return await validate_agent_access(agent_id, telegram_id) is not None


async def get_agent_owner_telegram_id(agent_id: str) -> int | None:
    """Extract owner's telegram_id from agent tags.

    Args:
        agent_id: The ID of the agent

    Returns:
        Owner's telegram_id if found, None otherwise

    Raises:
        APIError: If the retrieve operation fails
    """
    agent = await client.agents.retrieve(agent_id=agent_id, include=['agent.tags'])
    if agent.tags is not None:
        # Search for tag with format: owner-tg-{telegram_id}
        for tag in agent.tags:
            if tag.startswith('owner-tg-'):
                try:
                    telegram_id_str = tag.removeprefix('owner-tg-')
                    return int(telegram_id_str)
                except ValueError:
                    LOGGER.warning(f'Invalid owner tag format: {tag}')
                    continue

    return None


# =============================================================================
# Folder Management
# =============================================================================


async def get_or_create_agent_folder(agent_id: str, telegram_id: int) -> str:
    """Get existing folder or create new one for an agent.

    Args:
        agent_id: The ID of the agent
        telegram_id: Telegram user ID for metadata

    Returns:
        Folder ID
    """
    folder_name = f'uploads-{agent_id}'

    # Check if agent already has the uploads folder attached
    async for folder in client.agents.folders.list(agent_id=agent_id):
        if folder.name == folder_name:
            return folder.id

    # Create and attach new folder with metadata
    metadata: dict[str, object] = {
        'owner-tg': str(telegram_id),
    }
    try:
        new_folder = await client.folders.create(name=folder_name, metadata=metadata)
        await client.agents.folders.attach(folder_id=new_folder.id, agent_id=agent_id)
        return new_folder.id
    except ConflictError:
        # Race condition: folder was created by parallel request
        # Find by name and attach (suppress ConflictError if already attached)
        async for existing in client.folders.list(name=folder_name):
            with suppress(ConflictError):
                await client.agents.folders.attach(folder_id=existing.id, agent_id=agent_id)
            return existing.id
        raise


async def upload_file_to_folder(
    folder_id: str,
    file: BinaryIO,
) -> str:
    """Upload file to Letta folder.

    Args:
        folder_id: Letta folder ID
        file: File-like object with .name attribute set

    Returns:
        File ID from Letta

    Raises:
        LettaProcessingError: If Letta rejects the file
    """
    file_obj = await client.folders.files.upload(
        folder_id=folder_id,
        file=file,
        duplicate_handling='replace',
    )
    # Check if upload was rejected immediately
    if file_obj.processing_status == 'error':
        raise LettaProcessingError(file_obj.error_message or 'Upload rejected')
    return file_obj.id


async def get_file_status(folder_id: str, file_id: str) -> str:
    """Get current processing status of a file.

    Args:
        folder_id: Letta folder ID
        file_id: Letta file ID

    Returns:
        Processing status string (pending, parsing, embedding, completed)

    Raises:
        NotFoundError: If file not found
        ValueError: If file has no processing status
        LettaProcessingError: If Letta failed to process the file
    """
    file_obj = await client.folders.files.retrieve(file_id, folder_id=folder_id)
    if file_obj.processing_status is None:
        raise ValueError(f'File {file_id} has no processing status')
    if file_obj.processing_status == 'error':
        raise LettaProcessingError(file_obj.error_message or 'Unknown processing error')
    return file_obj.processing_status
