"""Client-side generate_image tool: schema + executor.

Uses OpenAI gpt-image-1 for generation and editing.
- No references: images.generate()
- With references: images.edit() (downloads from Telegram first)

gpt-image-1 always returns b64 — do NOT pass response_format.
"""

import io
import logging
from typing import Any

from aiogram import Bot
from openai import AsyncOpenAI

from letta_bot.config import CONFIG

from letta_client.types.agents.message_stream_params import ClientTool

LOGGER = logging.getLogger(__name__)

# Tool schema (matches SDK ClientTool TypedDict)
GENERATE_IMAGE_TOOL: ClientTool = {
    'name': 'generate_image',
    'description': (
        'Generate an image based on a text description. '
        'Use this tool when the user asks you to draw, create, or generate an image. '
        'You can optionally pass Telegram file_ids of user-sent photos as '
        'reference_images for style or content guidance.'
    ),
    'parameters': {
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
                    'Optional Telegram file_id strings of user-sent photos '
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
}


async def _download_telegram_file(bot: Bot, file_id: str) -> bytes:
    """Download a file from Telegram by file_id."""
    tg_file = await bot.get_file(file_id)
    assert tg_file.file_path, f'No file_path for file_id={file_id}'
    buf = io.BytesIO()
    await bot.download_file(tg_file.file_path, buf)
    return buf.getvalue()


_DEFAULT_MODEL = 'gpt-image-1-mini'


async def execute_generate_image(
    bot: Bot,
    prompt: str,
    reference_images: list[str] | None = None,
    model: str | None = None,
) -> tuple[str, str, str]:
    """Execute image generation via OpenAI.

    Args:
        bot: Aiogram Bot instance (for downloading reference images).
        prompt: Text description for generation.
        reference_images: Optional Telegram file_id strings.
        model: OpenAI image model (default: gpt-image-1-mini).

    Returns:
        (b64_data, media_type, text_summary)
    """
    openai_client = AsyncOpenAI(api_key=CONFIG.openai_api_key)
    model = model or _DEFAULT_MODEL

    ref_note = ''
    if reference_images:
        ref_note = f' (with {len(reference_images)} reference image(s))'

        # Download reference images from Telegram as (filename, bytes, mime) tuples
        ref_files: list[tuple[str, bytes, str]] = []
        for i, fid in enumerate(reference_images):
            data = await _download_telegram_file(bot, fid)
            ref_files.append((f'ref_{i}.png', data, 'image/png'))

        LOGGER.info(
            'Calling images.edit model=%s with %d reference(s), prompt=%s',
            model,
            len(ref_files),
            prompt[:80],
        )

        # gpt-image-1 family always returns b64 — do NOT pass response_format
        response = await openai_client.images.edit(
            image=ref_files,
            prompt=prompt,
            model=model,
        )
    else:
        LOGGER.info('Calling images.generate model=%s, prompt=%s', model, prompt[:80])

        response = await openai_client.images.generate(
            prompt=prompt,
            model=model,
        )

    assert response.data, 'OpenAI returned empty data'
    b64_data = response.data[0].b64_json
    assert b64_data, 'OpenAI returned no b64_json'

    media_type = 'image/png'
    text_summary = f'Image generated for prompt: "{prompt}"{ref_note}'

    return b64_data, media_type, text_summary
