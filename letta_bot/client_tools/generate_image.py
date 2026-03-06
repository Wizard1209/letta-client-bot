"""Client-side tool for image generation via OpenAI Images API.

Supports text-to-image generation and image editing with reference images.
Self-registers in the client tool registry at import time.
"""

import base64
from dataclasses import dataclass
import logging

from aiogram import Bot
from aiogram.types import BufferedInputFile, Message
from openai import AsyncOpenAI

from letta_bot.client_tools.registry import (
    FILE_ID_PLACEHOLDER,
    ClientToolResult,
    ClientToolSchema,
    LettaMessage,
    TelegramPhoto,
    registry,
)
from letta_bot.config import CONFIG
from letta_bot.images import (
    build_image_content_part,
    download_telegram_file,
)
from letta_bot.utils import get_mime_type

LOGGER = logging.getLogger(__name__)

_DEFAULT_MODEL = 'gpt-image-1-mini'


@dataclass(frozen=True)
class _FileIdRef:
    """Minimal wrapper to satisfy HasFileId protocol for downloading by file_id."""

    file_id: str


async def _download_reference_images(
    bot: Bot, file_ids: list[str]
) -> list[tuple[str, bytes, str]]:
    """Download reference images from Telegram.

    Returns list of (file_path, image_bytes, mime_type) tuples
    compatible with OpenAI SDK file upload format.
    """
    results: list[tuple[str, bytes, str]] = []
    for fid in file_ids:
        image_data, file_path = await download_telegram_file(bot, _FileIdRef(fid))
        mime = get_mime_type(file_path) or 'image/jpeg'
        results.append((file_path, image_data, mime))
    return results


async def generate_image(
    *,
    message: Message,
    prompt: str,
    reference_images: list[str] | None = None,
    model: str | None = None,
) -> ClientToolResult:
    """Generate image via OpenAI API.

    Args:
        message: Telegram message (provides bot for downloading references).
        prompt: Text description of the desired image.
        reference_images: Optional Telegram file_ids of reference images.
        model: OpenAI image model name.

    Returns:
        ClientToolResult with generated image.
    """
    model = model or _DEFAULT_MODEL
    client = AsyncOpenAI(api_key=CONFIG.openai_api_key)

    if reference_images:
        assert message.bot, 'Bot instance required'
        refs = await _download_reference_images(message.bot, reference_images)

        LOGGER.info(
            'Calling images.edit model=%s with %d reference(s), prompt=%s',
            model,
            len(refs),
            prompt[:80],
        )

        image_input = refs[0] if len(refs) == 1 else refs
        response = await client.images.edit(
            image=image_input,
            prompt=prompt,
            model=model,
            n=1,
        )
    else:
        LOGGER.info('Calling images.generate model=%s, prompt=%s', model, prompt[:80])

        response = await client.images.generate(
            prompt=prompt,
            model=model,
            n=1,
        )

    # Extract b64 data from response
    if not response.data or not response.data[0].b64_json:
        msg = 'OpenAI API returned empty image data'
        raise RuntimeError(msg)

    b64_data = response.data[0].b64_json

    # Build Telegram photo output
    image_bytes = base64.b64decode(b64_data)
    telegram_photo = TelegramPhoto(
        file=BufferedInputFile(image_bytes, filename='generated.png')
    )

    # Extra message: base64 image for agent visual feedback
    image_content = build_image_content_part(b64_data, 'image/png')
    extra_message: LettaMessage = {
        'role': 'user',
        'content': [
            image_content,
            {
                'type': 'text',
                'text': (
                    '<additional-tool-result tool="generate_image">'
                    f'<generated_image file_id="{FILE_ID_PLACEHOLDER}">'
                    'Image generation result attached'
                    '</generated_image>'
                    '</additional-tool-result>'
                ),
            },
        ],
    }

    tool_return = (
        f'Image generated successfully (model={model}). '
        f'Telegram file_id: {FILE_ID_PLACEHOLDER}'
    )

    return ClientToolResult(
        tool_return=tool_return,
        telegram_output=telegram_photo,
        extra_messages=[extra_message],
    )


# Tool schema for Letta API
SCHEMA = ClientToolSchema(
    name='generate_image',
    description=(
        'Generate an image based on a text description. '
        'Use this tool when the user asks you to draw, create, or generate an image. '
        'You can optionally pass Telegram file_ids of user-sent photos or stickers as '
        'reference_images for style or content guidance.'
    ),
    parameters={
        'type': 'object',
        'properties': {
            'prompt': {
                'type': 'string',
                'description': 'Detailed image generation prompt in English',
            },
            'reference_images': {
                'type': 'array',
                'items': {'type': 'string'},
                'description': (
                    'Optional Telegram file_id strings of user-sent photos or stickers '
                    'to use as style/content references'
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
)

# Self-register at import time (requires OpenAI API key)
if CONFIG.openai_api_key:
    registry.register('generate_image', generate_image, SCHEMA)
else:
    LOGGER.info('generate_image tool disabled: OPENAI_API_KEY not set')
