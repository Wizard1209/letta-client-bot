"""Audio transcription module using OpenAI Whisper API.

Handles voice messages and audio files from Telegram, converting them
to text for Letta agent processing.
"""

import logging
from pathlib import Path
from tempfile import NamedTemporaryFile

from aiogram import Bot
from aiogram.types import Audio, Message, Voice
from aiogram.utils.chat_action import ChatActionSender

LOGGER = logging.getLogger(__name__)

# Max file size for Whisper API (25MB)
MAX_FILE_SIZE = 25 * 1024 * 1024

# MIME type to file extension mapping (initialized once as module constant)
# Telegram voice messages are always audio/ogg with Opus codec
# Audio files can be various formats depending on what user uploads
MIME_TO_EXT = {
    'audio/ogg': '.ogg',  # Telegram voice messages (OGG container with Opus codec)
    'audio/opus': '.opus',  # Alternative Opus format
    'audio/mpeg': '.mp3',
    'audio/mp3': '.mp3',
    'audio/mp4': '.m4a',
    'audio/m4a': '.m4a',
    'audio/x-m4a': '.m4a',
    'audio/aac': '.aac',
    'audio/wav': '.wav',
    'audio/wave': '.wav',
    'audio/x-wav': '.wav',
    'audio/webm': '.webm',
    'audio/flac': '.flac',
    'audio/x-flac': '.flac',
}


class TranscriptionError(Exception):
    """Raised when transcription fails."""

    pass


class TranscriptionService:
    """Service for transcribing voice messages and audio files."""

    def __init__(self, openai_api_key: str, model: str = 'gpt-4o-mini-transcribe') -> None:
        """Initialize the transcription service.

        Args:
            openai_api_key: OpenAI API key for Whisper access.
            model: Whisper model to use. Options: whisper-1, gpt-4o-transcribe,
                   gpt-4o-mini-transcribe
        """
        # Import here to avoid loading openai if not configured
        from openai import AsyncOpenAI

        self.client = AsyncOpenAI(api_key=openai_api_key)
        self.model = model

    async def transcribe_message_content(
        self,
        bot: Bot,
        message: Message,
    ) -> str:
        """Transcribe voice/audio content with status indicator.

        Shows 'uploading voice' chat action while transcribing.
        Returns raw transcript text without formatting.

        Args:
            bot: Aiogram bot instance.
            message: Telegram message containing voice or audio content.

        Returns:
            Raw transcribed text.

        Raises:
            ValueError: If message contains neither voice nor audio.
            TranscriptionError: If transcription fails.
        """
        if not message.voice and not message.audio:
            raise ValueError('Message contains neither voice nor audio')

        async with ChatActionSender.upload_voice(bot=bot, chat_id=message.chat.id):
            if message.voice:
                return await self._transcribe_content(bot, message.voice)
            if message.audio:
                return await self._transcribe_content(bot, message.audio)
            LOGGER.warning('Audio content was expected')
            return ''

    async def _transcribe_content(self, bot: Bot, content: Voice | Audio) -> str:
        """Transcribe voice or audio content, returning raw text.

        Downloads to a NamedTemporaryFile and transcribes in one operation.
        File is auto-deleted when context exits.
        """
        if isinstance(content, Voice):
            if content.file_size and content.file_size > MAX_FILE_SIZE:
                raise TranscriptionError(
                    f'Voice message too large ({content.file_size / 1024 / 1024:.1f}MB). '
                    f'Maximum size is 25MB.'
                )
            suffix = '.ogg'
        else:
            if content.file_size and content.file_size > MAX_FILE_SIZE:
                raise TranscriptionError(
                    f'Audio file too large ({content.file_size / 1024 / 1024:.1f}MB). '
                    f'Maximum size is 25MB.'
                )
            suffix = self._get_extension(content.file_name, content.mime_type)

        with NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
            tmp_path = Path(tmp.name)

            # Download
            try:
                await bot.download(content.file_id, destination=tmp_path)
            except Exception as e:
                raise TranscriptionError(f'Failed to download file: {e}') from e

            # Transcribe
            try:
                response = await self.client.audio.transcriptions.create(
                    model=self.model,
                    file=tmp_path,
                )
                return response.text
            except Exception as e:
                raise TranscriptionError(f'Whisper API error: {e}') from e

    def _get_extension(self, file_name: str | None, mime_type: str | None) -> str:
        """Determine file extension from filename or MIME type.

        Priority order:
        1. Extract extension from filename if present
        2. Map MIME type to extension using MIME_TO_EXT
        3. Fall back to .ogg (default for unknown audio)

        Args:
            file_name: Original filename (may be None).
            mime_type: MIME type of the file (may be None).

        Returns:
            File extension including the dot (e.g., '.ogg').
        """
        # Try filename first
        if file_name:
            ext = Path(file_name).suffix
            if ext:
                return ext

        # Fall back to MIME type mapping
        if mime_type:
            mapped_ext = MIME_TO_EXT.get(mime_type)
            if mapped_ext:
                return mapped_ext
            # Log unknown MIME type for debugging
            LOGGER.warning(f'Unknown MIME type for audio file: {mime_type}')

        # Default to .ogg (most common for Telegram voice/unknown audio)
        # Whisper API supports OGG, so this is a safe fallback
        return '.ogg'


# Global instance (initialized lazily)
_transcription_service: TranscriptionService | None = None


def get_transcription_service() -> TranscriptionService | None:
    """Get or create the global transcription service.

    Reads configuration from CONFIG. Returns None if OpenAI API key not configured.
    """
    global _transcription_service

    if _transcription_service is not None:
        return _transcription_service

    from letta_bot.config import CONFIG

    if CONFIG.openai_api_key is None:
        return None

    _transcription_service = TranscriptionService(
        CONFIG.openai_api_key, CONFIG.whisper_model
    )
    return _transcription_service
