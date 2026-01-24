"""Shared Letta client instance and Letta API operations.

This module provides:
1. A single Letta client instance used across the application
2. Pure Letta API operations (identity, agent, tool management)

Isolating the client here prevents circular import issues.
"""

from contextlib import suppress
import logging
from typing import Any, BinaryIO

from letta_client import APIError, AsyncLetta as LettaClient, ConflictError
from letta_client.types.agent_state import Identity

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
            f"Identity already exists but couldn't be retrieved {identifier_key}"
        )
        raise
    except APIError:
        LOGGER.critical(f'Identity creation and retrieval failed: {identifier_key}')
        raise


# =============================================================================
# Agent Management
# =============================================================================


async def create_agent_from_template(
    template_id: str, identity_id: str, tags: list[str] | None = None
) -> None:
    """Create agent from template in Letta API."""
    # Local import to avoid circular dependency
    from letta_bot.auth import NewAssistantCallback

    info = NewAssistantCallback.unpack(template_id)

    # Use new templates.agents.create() API
    # Client is already configured with project, so it auto-scopes
    template_version = f'{info.template_name}:{info.version}'

    # Prepare kwargs with optional tags
    kwargs: dict[str, Any] = {
        'template_version': template_version,
        'identity_ids': [identity_id],
    }
    if tags is not None:
        kwargs['tags'] = tags
    await client.templates.agents.create(**kwargs)


async def get_oldest_agent_id(identity_id: str) -> str:
    """Get the oldest agent ID for a given identity.

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


async def attach_identity_to_agent(agent_id: str, identity_id: str) -> None:
    """Attach an identity to an existing agent.

    Args:
        agent_id: The ID of the agent to attach identity to
        identity_id: The ID of the identity to attach

    Raises:
        APIError: If the attach operation fails
    """
    await client.agents.identities.attach(agent_id=agent_id, identity_id=identity_id)


async def get_agent_identity_ids(agent_id: str) -> list[str]:
    """Get all identity IDs associated with an agent.

    Args:
        agent_id: The ID of the agent

    Returns:
        List of identity IDs attached to the agent (empty list if none)

    Raises:
        APIError: If the retrieve operation fails
    """
    agent = await client.agents.retrieve(agent_id=agent_id, include=['agent.identities'])
    if agent.identities is None:
        return []
    return [identity.id for identity in agent.identities]


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
        'creator-tg': str(telegram_id),
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
