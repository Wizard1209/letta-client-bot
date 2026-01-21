"""Audio transcription module supporting multiple engines.

Supports OpenAI Whisper and ElevenLabs Scribe for transcribing voice messages
and audio files from Telegram.
"""

import logging
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Protocol

from aiogram import Bot
from aiogram.types import Audio, Message, Voice
from aiogram.utils.chat_action import ChatActionSender

LOGGER = logging.getLogger(__name__)

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


class TranscriptionEngine(Protocol):
    """Protocol for transcription engine implementations."""

    max_file_size: int
    engine_name: str

    async def transcribe_file(self, file_path: Path) -> str:
        """Transcribe audio file to text.

        Args:
            file_path: Path to the audio file.

        Returns:
            Transcribed text.

        Raises:
            TranscriptionError: If transcription fails.
        """
        ...


class OpenAITranscriptionEngine:
    """OpenAI Whisper transcription engine."""

    max_file_size = 25 * 1024 * 1024  # 25MB
    engine_name = 'OpenAI Whisper'

    def __init__(self, api_key: str, model: str = 'gpt-4o-mini-transcribe') -> None:
        """Initialize OpenAI transcription engine.

        Args:
            api_key: OpenAI API key.
            model: Whisper model to use.
        """
        from openai import AsyncOpenAI

        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def transcribe_file(self, file_path: Path) -> str:
        """Transcribe audio file using OpenAI Whisper API."""
        try:
            response = await self.client.audio.transcriptions.create(
                model=self.model,
                file=file_path,
            )
            return response.text
        except Exception as e:
            raise TranscriptionError(f'Whisper API error: {e}') from e


class ElevenLabsTranscriptionEngine:
    """ElevenLabs Scribe transcription engine."""

    max_file_size = 100 * 1024 * 1024  # 100MB
    engine_name = 'ElevenLabs Scribe'

    def __init__(self, api_key: str, model: str = 'scribe_v2') -> None:
        """Initialize ElevenLabs transcription engine.

        Args:
            api_key: ElevenLabs API key.
            model: Scribe model to use (scribe_v1 or scribe_v2).
        """
        from elevenlabs import AsyncElevenLabs

        if not api_key:
            raise TranscriptionError('No api key provided')

        self.client = AsyncElevenLabs(api_key=api_key)
        self.model = model

    async def transcribe_file(self, file_path: Path) -> str:
        """Transcribe audio file using ElevenLabs Scribe API."""
        from elevenlabs import SpeechToTextChunkResponseModel

        try:
            with open(file_path, 'rb') as audio_file:
                response = await self.client.speech_to_text.convert(
                    file=audio_file,
                    model_id=self.model,
                    tag_audio_events=True,
                )
            # Without multichannel/webhook, response is SpeechToTextChunkResponseModel
            if not isinstance(response, SpeechToTextChunkResponseModel):
                raise TranscriptionError('Unexpected response type from ElevenLabs API')
            return response.text
        except TranscriptionError:
            raise
        except Exception as e:
            raise TranscriptionError(f'ElevenLabs Scribe API error: {e}') from e


class TranscriptionService:
    """Service for transcribing voice messages and audio files."""

    def __init__(self, engine: TranscriptionEngine) -> None:
        """Initialize the transcription service.

        Args:
            engine: Transcription engine to use.
        """
        self.engine = engine

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
            label, suffix = 'Voice message', '.ogg'
        else:
            label = 'Audio file'
            suffix = self._get_extension(content.file_name, content.mime_type)

        max_size = self.engine.max_file_size
        if content.file_size and content.file_size > max_size:
            raise TranscriptionError(
                f'{label} too large ({content.file_size / 1024 / 1024:.1f}MB). '
                f'Maximum size is {max_size / 1024 / 1024:.0f}MB.'
            )

        with NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
            tmp_path = Path(tmp.name)

            # Download
            try:
                await bot.download(content.file_id, destination=tmp_path)
            except Exception as e:
                raise TranscriptionError(f'Failed to download file: {e}') from e

            # Transcribe using the configured engine
            return await self.engine.transcribe_file(tmp_path)

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
        return '.ogg'


# Global instance (initialized lazily)
_transcription_service: TranscriptionService | None = None


def get_transcription_service() -> TranscriptionService | None:
    """Get or create the global transcription service.

    Engine selection based on available API keys (ElevenLabs prioritized):
    - If ELEVENLABS_API_KEY set → ElevenLabs Scribe
    - Else if OPENAI_API_KEY set → OpenAI Whisper
    - Else → None

    Returns None if no API key available.
    """
    global _transcription_service

    if _transcription_service is not None:
        return _transcription_service

    from letta_bot.config import CONFIG

    engine: TranscriptionEngine | None = None

    if CONFIG.elevenlabs_api_key:
        engine = ElevenLabsTranscriptionEngine(
            CONFIG.elevenlabs_api_key, CONFIG.elevenlabs_stt_model
        )
    elif CONFIG.openai_api_key:
        engine = OpenAITranscriptionEngine(CONFIG.openai_api_key, CONFIG.whisper_model)

    if engine is None:
        return None

    LOGGER.info('Transcription engine: %s', engine.engine_name)
    _transcription_service = TranscriptionService(engine)
    return _transcription_service
