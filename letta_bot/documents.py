"""Document processing utilities for Telegram documents.

This module handles downloading documents from Telegram and uploading them
to Letta folders for agent access. It also provides file processing tracking
to prevent concurrent uploads.
"""

import asyncio
import logging
from pathlib import Path
from typing import BinaryIO, TypedDict

from aiogram import Bot
from aiogram.types import Document

from letta_bot.client import (
    client,
    get_file_status,
    get_or_create_agent_folder,
    upload_file_to_folder,
)

LOGGER = logging.getLogger(__name__)

# File handling memory block configuration
FILE_HANDLING_BLOCK_LABEL = 'file_handling'
FILE_HANDLING_BLOCK_VERSION = '1.0.0'
FILE_HANDLING_BLOCK_DESC = (
    'How to handle user file uploads: understanding system messages, '
    'using file tools, and responding appropriately to file events.'
)


def _load_file_handling_block_content() -> str:
    """Load file handling memory block content from markdown file."""
    block_path = (
        Path(__file__).parent / 'custom_tools' / 'memory_blocks' / 'file_handling.md'
    )
    return block_path.read_text(encoding='utf-8')


async def _attach_file_handling_block(agent_id: str) -> None:
    """Attach file handling memory block to agent if not exists."""
    # Check if block already exists on agent
    async for block in client.agents.blocks.list(agent_id=agent_id):
        if block.label == FILE_HANDLING_BLOCK_LABEL:
            LOGGER.debug('File handling block already attached to agent %s', agent_id)
            return

    # Load content and create block
    block_content = _load_file_handling_block_content()
    block = await client.blocks.create(
        label=FILE_HANDLING_BLOCK_LABEL,
        description=FILE_HANDLING_BLOCK_DESC,
        value=block_content,
        metadata={'version': FILE_HANDLING_BLOCK_VERSION},
    )

    # Attach to agent
    if block.id:
        await client.agents.blocks.attach(agent_id=agent_id, block_id=block.id)
        LOGGER.info('Attached file handling block to agent %s', agent_id)


# Letta API file size limit (bytes)
# API returns 502 at ~10,485,600 bytes, using 10MB with safety margin
MAX_FILE_SIZE_BYTES: int = 10_000_000  # ~9.5 MB
MAX_FILE_SIZE_MB: float = MAX_FILE_SIZE_BYTES / (1024 * 1024)


class DocumentProcessingError(Exception):
    """Raised when document processing fails (infrastructure errors)."""

    pass


class FileTooLargeError(DocumentProcessingError):
    """Raised when file exceeds size limit."""

    pass


class FileProcessingTracker:
    """Tracks file processing per user to prevent concurrent uploads.

    Usage:
        tracker = FileProcessingTracker()

        async with tracker.acquire(user_id) as acquired:
            if not acquired:
                await message.answer("Please wait...")
                return
            # ... download and upload file ...
    """

    def __init__(self) -> None:
        self._processing: set[int] = set()

    def acquire(self, user_id: int) -> 'FileProcessingContext':
        """Acquire processing slot for user.

        Returns a context manager that tracks processing state.
        """
        return FileProcessingContext(self, user_id)

    def _try_start(self, user_id: int) -> bool:
        """Try to start processing for user. Returns True if acquired."""
        if user_id in self._processing:
            return False
        self._processing.add(user_id)
        return True

    def _stop(self, user_id: int) -> None:
        """Release processing slot for user."""
        self._processing.discard(user_id)


class FileProcessingContext:
    """Context manager for file processing tracking."""

    def __init__(self, tracker: FileProcessingTracker, user_id: int) -> None:
        self._tracker = tracker
        self._user_id = user_id
        self._acquired = False

    async def __aenter__(self) -> bool:
        """Try to acquire processing slot. Returns True if acquired."""
        self._acquired = self._tracker._try_start(self._user_id)
        return self._acquired

    async def __aexit__(self, *args: object) -> None:
        """Release processing slot if acquired."""
        if self._acquired:
            self._tracker._stop(self._user_id)


# Global instance for file processing tracking
file_processing_tracker = FileProcessingTracker()


class DocumentResult(TypedDict):
    """Result of document processing."""

    folder_id: str
    file_id: str
    file_name: str


async def download_telegram_document(bot: Bot, document: Document) -> tuple[BinaryIO, str]:
    """Download document from Telegram and return file-like object with name.

    Args:
        bot: Aiogram Bot instance
        document: Document object from message.document

    Returns:
        Tuple of (file_like_object, file_name). The file object has .name attribute set.

    Raises:
        DocumentProcessingError: If download fails
    """
    try:
        file = await bot.get_file(document.file_id)

        if not file.file_path:
            raise DocumentProcessingError('Telegram returned empty file_path')

        result: BinaryIO | None = await bot.download_file(file.file_path)

        if result is None:
            raise DocumentProcessingError('Download returned None')

        file_name = document.file_name or f'document_{document.file_id}'
        result.name = file_name  # type: ignore[misc]

        return result, file_name

    except DocumentProcessingError:
        raise
    except Exception as e:
        raise DocumentProcessingError(f'Failed to download document: {e}') from e


async def process_telegram_document(
    bot: Bot,
    document: Document,
    agent_id: str,
    user_id: int,
) -> DocumentResult:
    """Process a Telegram document: download and upload to Letta folder.

    This is the main entry point for document processing. It:
    1. Validates file size
    2. Downloads from Telegram
    3. Gets or creates agent folder (attaches file handling memory block)
    4. Uploads to Letta

    Note: Caller should use wait_for_file_processing() to wait for Letta
    to finish processing the file before sending messages to the agent.

    Args:
        bot: Aiogram Bot instance
        document: Telegram Document object
        agent_id: Letta agent ID for folder association
        user_id: Telegram user ID for folder metadata

    Returns:
        DocumentResult with folder_id, file_id and file_name

    Raises:
        FileTooLargeError: If document exceeds size limit
        DocumentProcessingError: If download/upload fails
    """
    # Validate file size
    if document.file_size and document.file_size > MAX_FILE_SIZE_BYTES:
        raise FileTooLargeError(f'File too large (max {MAX_FILE_SIZE_MB:.1f} MB)')

    # Download from Telegram
    file_obj, file_name = await download_telegram_document(bot, document)

    # Get or create folder and attach file handling memory block
    folder_id = await get_or_create_agent_folder(agent_id, user_id)
    await _attach_file_handling_block(agent_id)
    file_id = await upload_file_to_folder(folder_id, file_obj)

    LOGGER.info(
        'Uploaded document: name=%s, file_id=%s, agent=%s',
        file_name,
        file_id,
        agent_id,
    )

    return DocumentResult(folder_id=folder_id, file_id=file_id, file_name=file_name)


async def wait_for_file_processing(
    folder_id: str,
    file_id: str,
    initial_interval: float = 1.0,
    max_interval: float = 5.0,
    backoff_factor: float = 1.5,
    timeout: float = 180.0,
) -> None:
    """Wait for file processing to complete with exponential backoff.

    Args:
        folder_id: Letta folder ID
        file_id: Letta file ID
        initial_interval: Initial seconds between status checks
        max_interval: Maximum seconds between checks
        backoff_factor: Multiplier for interval on each iteration
        timeout: Maximum wait time in seconds

    Raises:
        DocumentProcessingError: If timeout reached
        LettaProcessingError: If Letta failed to process the file
    """
    interval = initial_interval
    try:
        async with asyncio.timeout(timeout):
            while True:
                status = await get_file_status(folder_id, file_id)
                if status == 'completed':
                    return
                await asyncio.sleep(interval)
                interval = min(interval * backoff_factor, max_interval)
    except TimeoutError:
        raise DocumentProcessingError(f'Processing timed out after {timeout}s') from None
