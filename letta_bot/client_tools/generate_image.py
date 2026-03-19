"""Client-side tool for image generation via OpenAI, Google Gemini, and BFL FLUX APIs.

Supports text-to-image generation and image editing with reference images.
Self-registers in the client tool registry at import time.
Provider is selected by model name: gpt-* → OpenAI, gemini-* → Gemini, flux-* → BFL.
"""

import asyncio
import base64
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from functools import partial
import logging
from typing import Literal, NamedTuple, cast, get_args

from aiogram import Bot
from aiogram.types import BufferedInputFile, Message
import httpx
from openai import AsyncOpenAI

from letta_bot.client_tools.registry import (
    FILE_ID_PLACEHOLDER,
    ClientToolError,
    ClientToolResult,
    ClientToolSchema,
    LettaMessage,
    TelegramPhoto,
    registry,
)
from letta_bot.config import CONFIG
from letta_bot.images import (
    ImageProcessingError,
    build_image_content_part,
    download_image_from_url,
    download_telegram_file,
)
from letta_bot.utils import get_mime_type

LOGGER = logging.getLogger(__name__)

# --- Provider model types ---

OpenAIModel = Literal['gpt-image-1-mini', 'gpt-image-1', 'gpt-image-1.5']
GeminiModel = Literal[
    'gemini-2.5-flash-image',
    'gemini-3.1-flash-image-preview',
    'gemini-3-pro-image-preview',
]
FluxModel = Literal['flux-2-pro', 'flux-2-max', 'flux-2-flex', 'flux-2-klein-9b']
ImageModel = OpenAIModel | GeminiModel | FluxModel

OPENAI_MODELS: list[OpenAIModel] = list(get_args(OpenAIModel))
GEMINI_MODELS: list[GeminiModel] = list(get_args(GeminiModel))
FLUX_MODELS: list[FluxModel] = list(get_args(FluxModel))

_BFL_BASE_URL = 'https://api.bfl.ai/v1'
_BFL_MAX_POLL_ITERATIONS = 120  # ~2 min timeout with 1s sleep


# --- Image output ---

class GeneratedImage(NamedTuple):
    """Raw output from a provider."""

    data: bytes
    mime_type: str


# --- Reference image helpers ---

class ImageRef(NamedTuple):
    """Downloaded reference image for provider SDK file upload."""

    source: str  # file_path or URL
    data: bytes
    mime_type: str


@dataclass(frozen=True)
class _FileIdRef:
    """Minimal wrapper to satisfy HasFileId protocol for downloading by file_id."""

    file_id: str


async def _download_reference_images(
    bot: Bot, references: list[str]
) -> list[ImageRef]:
    """Download reference images from Telegram file_ids or HTTP/HTTPS URLs."""
    results: list[ImageRef] = []
    for ref in references:
        if ref.startswith(('http://', 'https://')):
            image_data, mime = await download_image_from_url(ref)
            results.append(ImageRef(ref, image_data, mime))
        else:
            image_data, file_path = await download_telegram_file(bot, _FileIdRef(ref))
            mime = get_mime_type(file_path) or 'image/jpeg'
            results.append(ImageRef(file_path, image_data, mime))
    return results


# --- Provider implementations ---

async def _generate_via_openai(
    prompt: str, refs: list[ImageRef] | None, *, model: OpenAIModel
) -> GeneratedImage:
    """Generate image via OpenAI Images API."""
    client = AsyncOpenAI(api_key=CONFIG.openai_api_key)

    if refs:
        LOGGER.info(
            'OpenAI images.edit model=%s with %d ref(s), prompt=%s',
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
        LOGGER.info('OpenAI images.generate model=%s, prompt=%s', model, prompt[:80])
        response = await client.images.generate(
            prompt=prompt,
            model=model,
            n=1,
        )

    if not response.data or not response.data[0].b64_json:
        msg = 'OpenAI API returned empty image data'
        raise RuntimeError(msg)

    b64_data = response.data[0].b64_json
    return GeneratedImage(base64.b64decode(b64_data), 'image/png')


async def _generate_via_gemini(
    prompt: str, refs: list[ImageRef] | None, *, model: GeminiModel
) -> GeneratedImage:
    """Generate image via Google Gemini API."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=CONFIG.gemini_api_key)

    # Build content parts: prompt + optional reference images
    parts: list[types.Part] = [types.Part.from_text(text=prompt)]
    if refs:
        LOGGER.info(
            'Gemini generate model=%s with %d ref(s), prompt=%s',
            model,
            len(refs),
            prompt[:80],
        )
        for ref in refs:
            parts.append(
                types.Part.from_bytes(data=ref.data, mime_type=ref.mime_type)
            )
    else:
        LOGGER.info('Gemini generate model=%s, prompt=%s', model, prompt[:80])

    response = await client.aio.models.generate_content(
        model=model,
        contents=parts,
        config=types.GenerateContentConfig(
            response_modalities=['IMAGE'],
        ),
    )

    # Extract image from response parts
    if (
        not response.candidates
        or not response.candidates[0].content
        or not response.candidates[0].content.parts
    ):
        msg = 'Gemini API returned empty response'
        raise RuntimeError(msg)

    for part in response.candidates[0].content.parts:
        if part.inline_data is not None and part.inline_data.data is not None:
            mime_type = part.inline_data.mime_type or 'image/png'
            return GeneratedImage(part.inline_data.data, mime_type)

    msg = 'Gemini API returned no image in response'
    raise RuntimeError(msg)


async def _generate_via_flux(
    prompt: str, refs: list[ImageRef] | None, *, model: FluxModel
) -> GeneratedImage:
    """Generate image via BFL FLUX API (async polling)."""
    headers = {'x-key': CONFIG.bfl_api_key or '', 'Content-Type': 'application/json'}

    body: dict[str, object] = {
        'prompt': prompt,
        'output_format': 'png',
    }

    # Attach reference images as input_image, input_image_2, etc.
    if refs:
        LOGGER.info(
            'FLUX generate model=%s with %d ref(s), prompt=%s',
            model,
            len(refs),
            prompt[:80],
        )
        max_refs = 4 if model == 'flux-2-klein-9b' else 8
        for i, ref in enumerate(refs[:max_refs]):
            key = 'input_image' if i == 0 else f'input_image_{i + 1}'
            body[key] = base64.b64encode(ref.data).decode('ascii')
    else:
        LOGGER.info('FLUX generate model=%s, prompt=%s', model, prompt[:80])

    async with httpx.AsyncClient(timeout=30) as client:
        # Submit generation request
        submit_resp = await client.post(
            f'{_BFL_BASE_URL}/{model}', headers=headers, json=body
        )
        submit_resp.raise_for_status()
        task = submit_resp.json()
        polling_url: str = task['polling_url']

        # Poll until ready
        for _ in range(_BFL_MAX_POLL_ITERATIONS):
            await asyncio.sleep(1)
            poll_resp = await client.get(polling_url, headers=headers)
            poll_resp.raise_for_status()
            result = poll_resp.json()
            status = result.get('status')

            if status == 'Ready':
                sample_url: str = result['result']['sample']
                image_resp = await client.get(sample_url)
                image_resp.raise_for_status()
                return GeneratedImage(image_resp.content, 'image/png')

            if status in (
                'Error',
                'Failed',
                'Request Moderated',
                'Content Moderated',
                'Task not found',
            ):
                raise ClientToolError(f'FLUX generation failed: {status}')

            # status == 'Pending' — keep polling

        raise ClientToolError('FLUX generation timed out (polling limit reached)')


# --- Dispatch ---

# Provider callable: (prompt, refs) -> GeneratedImage
ImageGenerator = Callable[
    [str, list[ImageRef] | None],
    Coroutine[object, object, GeneratedImage],
]


def _resolve_model(
    model: str | None,
) -> tuple[ImageModel, ImageGenerator]:
    """Resolve model name, validate API key, return bound generator.

    Returns (resolved_model, generator) where generator is an async callable
    with signature (prompt, refs) -> GeneratedImage.

    Raises ClientToolError on unknown model or missing API key.
    """
    if model is None:
        model = OPENAI_MODELS[0] if CONFIG.openai_api_key else GEMINI_MODELS[0]

    if model in get_args(OpenAIModel):
        if not CONFIG.openai_api_key:
            raise ClientToolError(
                f'Model {model} requires OPENAI_API_KEY, but it is not set'
            )
        openai_model = cast(OpenAIModel, model)
        gen: ImageGenerator = partial(_generate_via_openai, model=openai_model)
        return openai_model, gen

    if model in get_args(GeminiModel):
        if not CONFIG.gemini_api_key:
            raise ClientToolError(
                f'Model {model} requires GEMINI_API_KEY, but it is not set'
            )
        gemini_model = cast(GeminiModel, model)
        gen = partial(_generate_via_gemini, model=gemini_model)
        return gemini_model, gen

    if model in get_args(FluxModel):
        if not CONFIG.bfl_api_key:
            raise ClientToolError(
                f'Model {model} requires BFL_API_KEY, but it is not set'
            )
        flux_model = cast(FluxModel, model)
        gen = partial(_generate_via_flux, model=flux_model)
        return flux_model, gen

    raise ClientToolError(f'Unknown image model: {model}')


# --- Main executor ---

async def generate_image(
    *,
    message: Message,
    prompt: str,
    reference_images: list[str] | None = None,
    model: str | None = None,
) -> ClientToolResult:
    """Generate image via OpenAI or Gemini API based on model name.

    Args:
        message: Telegram message (provides bot for downloading references).
        prompt: Text description of the desired image.
        reference_images: Optional Telegram file_ids or HTTP/HTTPS URLs.
        model: Image model name (gpt-* or gemini-*).

    Returns:
        ClientToolResult with generated image.

    Raises:
        ClientToolError: Unknown model or missing API key for provider.
    """
    resolved, generate = _resolve_model(model)

    # Download reference images (shared across providers)
    refs: list[ImageRef] | None = None
    if reference_images:
        assert message.bot, 'Bot instance required'
        try:
            refs = await _download_reference_images(message.bot, reference_images)
        except ImageProcessingError as e:
            raise ClientToolError(str(e)) from e

    # TODO: test reference image editing with Gemini
    result = await generate(prompt, refs)

    # Build Telegram photo output
    ext = 'png' if 'png' in result.mime_type else 'jpeg'
    telegram_photo = TelegramPhoto(
        file=BufferedInputFile(result.data, filename=f'generated.{ext}')
    )

    # Extra message: base64 image for agent visual feedback
    b64_data = base64.b64encode(result.data).decode('ascii')
    image_content = build_image_content_part(b64_data, result.mime_type)
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
        f'Image generated successfully (model={resolved}). '
        f'Telegram file_id: {FILE_ID_PLACEHOLDER}'
    )

    return ClientToolResult(
        tool_return=tool_return,
        telegram_output=telegram_photo,
        extra_messages=[extra_message],
    )


# --- Schema builder ---

def _build_schema() -> ClientToolSchema:
    """Build tool schema with dynamic model enum based on available API keys."""
    available_models: list[str] = []
    description_parts: list[str] = []

    if CONFIG.openai_api_key:
        available_models.extend(OPENAI_MODELS)
        description_parts.append(
            'gpt-image-1-mini (default) — fastest, cheapest. '
            'gpt-image-1 — higher quality, slower. '
            'gpt-image-1.5 — best quality, 4x faster than 1, '
            'best text rendering and prompt adherence.'
        )

    if CONFIG.gemini_api_key:
        available_models.extend(GEMINI_MODELS)
        description_parts.append(
            'gemini-2.5-flash-image — fast Gemini image generation. '
            'gemini-3.1-flash-image-preview — latest Gemini flash model. '
            'gemini-3-pro-image-preview — highest quality Gemini model.'
        )

    if CONFIG.bfl_api_key:
        available_models.extend(FLUX_MODELS)
        description_parts.append(
            'flux-2-pro — FLUX production model, fast (<10s). '
            'flux-2-max — FLUX highest quality model (<15s). '
            'flux-2-flex — precision model, best for typography and small details. '
            'flux-2-klein-9b — fast and efficient, optimized for rapid iteration.'
        )

    model_description = (
        'Image model to use. ' + ' '.join(description_parts)
    )

    return ClientToolSchema(
        name='generate_image',
        description=(
            'Generate an image based on a text description. '
            'Use this tool when the user asks you to draw, create, '
            'or generate an image. '
            'You can optionally pass Telegram file_ids of user-sent '
            'photos/stickers or HTTP/HTTPS image URLs as reference_images '
            'for style or content guidance.'
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
                        'Optional list of reference image sources. '
                        'Each item can be a Telegram file_id '
                        '(from user-sent photos/stickers) '
                        'or an HTTP/HTTPS URL pointing to an image'
                    ),
                },
                'model': {
                    'type': 'string',
                    'enum': available_models,
                    'description': model_description,
                },
            },
            'required': ['prompt'],
        },
    )


# Self-register at import time (requires at least one image API key)
if CONFIG.openai_api_key or CONFIG.gemini_api_key or CONFIG.bfl_api_key:
    registry.register('generate_image', generate_image, _build_schema())
else:
    LOGGER.info(
        'generate_image tool disabled: '
        'no image API key is set (OPENAI_API_KEY, GEMINI_API_KEY, or BFL_API_KEY)'
    )
