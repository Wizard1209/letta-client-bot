"""Image generation client-side tool via OpenAI Images API.

Registers itself into the client-side tool registry at import time.
"""

import base64
import logging

from aiogram import Bot
from aiogram.types import Message
from letta_client.types.agents.message_create_params import ClientTool
import openai
from openai import AsyncOpenAI

from letta_bot.client_tools.registry import (
    PENDING_PLACEHOLDER,
    ClientToolResult,
    LettaImage,
    TelegramPhoto,
    register_tool,
)
from letta_bot.config import CONFIG
from letta_bot.images import ImageProcessingError, download_telegram_file
from letta_bot.utils import get_mime_type

LOGGER = logging.getLogger(__name__)

DEFAULT_MODEL = 'gpt-image-1-mini'

_openai_client: AsyncOpenAI | None = None


def _get_openai_client() -> AsyncOpenAI:
    """Get or create the global async OpenAI client."""
    global _openai_client  # noqa: PLW0603
    if _openai_client is None:
        _openai_client = AsyncOpenAI(api_key=CONFIG.openai_api_key)
    return _openai_client


class _TelegramFileRef:
    """Minimal adapter satisfying HasFileId protocol for raw file_id strings."""

    def __init__(self, file_id: str) -> None:
        self._file_id = file_id

    @property
    def file_id(self) -> str:
        return self._file_id


async def execute_generate_image(
    *,
    bot: Bot,
    message: Message,
    prompt: str,
    reference_images: list[str] | None = None,
    model: str = DEFAULT_MODEL,
) -> ClientToolResult:
    """Execute the generate_image client-side tool."""
    try:
        client = _get_openai_client()

        if reference_images:
            # Download reference images from Telegram
            # Pass as (filename, bytes, content_type) tuples
            # so OpenAI detects MIME type correctly
            refs: list[tuple[str, bytes, str]] = []
            for fid in reference_images:
                data, file_path = await download_telegram_file(bot, _TelegramFileRef(fid))
                mime = get_mime_type(file_path) or 'image/jpeg'
                refs.append((file_path, data, mime))

            image_input = refs[0] if len(refs) == 1 else refs
            response = await client.images.edit(
                image=image_input,
                prompt=prompt,
                model=model,
                n=1,
            )
        else:
            # GPT image models always return b64_json
            response = await client.images.generate(
                prompt=prompt,
                model=model,
                n=1,
            )

        if not response.data:
            return ClientToolResult(
                tool_return='Error: OpenAI returned empty response',
                status='error',
            )

        b64 = response.data[0].b64_json
        if not b64:
            return ClientToolResult(
                tool_return='Error: OpenAI returned empty image data',
                status='error',
            )

        return ClientToolResult(
            tool_return=(
                f'Image generated and sent to user. telegram_file_id: {PENDING_PLACEHOLDER}'
            ),
            status='success',
            telegram_result=TelegramPhoto(data=base64.b64decode(b64)),
            letta_image=LettaImage(b64_data=b64, media_type='image/png'),
        )

    except ImageProcessingError as e:
        LOGGER.warning('Reference image download failed: %s', e)
        return ClientToolResult(
            tool_return=f'Error downloading reference image: {e}',
            status='error',
        )
    except openai.APIError as e:
        LOGGER.warning('Image generation failed: %s', e)
        return ClientToolResult(
            tool_return=f'Error generating image: {e}',
            status='error',
        )


# =============================================================================
# Tool Schema & Registration
# =============================================================================

_SCHEMA: ClientTool = {
    'name': 'generate_image',
    'description': (
        'Generate an image based on a text description. '
        'Use this tool when the user asks you to draw, create, '
        'or generate an image. '
        'You can optionally pass Telegram file_ids of user-sent '
        'photos or stickers as reference_images for style or content guidance.'
    ),
    'parameters': {
        'type': 'object',
        'properties': {
            'prompt': {
                'type': 'string',
                'description': ('Detailed image generation prompt in English'),
            },
            'reference_images': {
                'type': 'array',
                'items': {'type': 'string'},
                'description': (
                    'Optional Telegram file_id strings of user-sent '
                    'photos or stickers to use as style/content references'
                ),
            },
            'model': {
                'type': 'string',
                'enum': [
                    'gpt-image-1-mini',
                    'gpt-image-1',
                    'gpt-image-1.5',
                ],
                'description': (
                    'Image model to use. '
                    'gpt-image-1-mini (default) — fastest, cheapest. '
                    'gpt-image-1 — higher quality, slower. '
                    'gpt-image-1.5 — best quality, 4x faster than 1, '
                    'best text rendering and prompt adherence. '
                    'Use gpt-image-1.5 when user wants top quality '
                    'or accurate text in images.'
                ),
            },
        },
        'required': ['prompt'],
    },
}

register_tool('generate_image', execute_generate_image, _SCHEMA)
