"""Image processing utilities for Telegram photos and stickers.

This module handles downloading images from Telegram and converting them
to base64-encoded content parts for Letta's multimodal API.
"""

import base64
import logging
from typing import BinaryIO, Literal, Protocol, TypedDict, runtime_checkable

from aiogram import Bot

from letta_bot.utils import get_mime_type


@runtime_checkable
class HasFileId(Protocol):
    """Protocol for objects with file_id attribute (PhotoSize, Sticker, etc.)."""

    @property
    def file_id(self) -> str: ...


LOGGER = logging.getLogger(__name__)


class ImageSource(TypedDict):
    """Letta image source structure."""

    type: Literal['base64']
    media_type: str  # MIME type like 'image/jpeg'
    data: str  # Base64-encoded image data


class ImageContentPart(TypedDict):
    """Letta image content part structure."""

    type: Literal['image']
    source: ImageSource


class TextContentPart(TypedDict):
    """Letta text content part structure."""

    type: Literal['text']
    text: str


# Union type for all content parts
ContentPart = ImageContentPart | TextContentPart


class ImageProcessingError(Exception):
    """Raised when image processing fails."""

    pass


DEFAULT_MEDIA_TYPE = 'image/jpeg'


async def download_telegram_file(bot: Bot, file_obj: HasFileId) -> tuple[bytes, str]:
    """Download file from Telegram and return raw bytes with file path.

    Args:
        bot: Aiogram Bot instance
        file_obj: Any object with file_id (PhotoSize, Sticker, etc.)

    Returns:
        Tuple of (file_bytes, file_path)

    Raises:
        ImageProcessingError: If download fails
    """
    try:
        # Get file info (needed for file_path to detect MIME type)
        file = await bot.get_file(file_obj.file_id)

        if not file.file_path:
            raise ImageProcessingError('Telegram returned empty file_path')

        # Download to memory
        result: BinaryIO | None = await bot.download_file(file.file_path)

        if result is None:
            raise ImageProcessingError('Download returned None')

        return result.read(), file.file_path

    except ImageProcessingError:
        raise
    except Exception as e:
        raise ImageProcessingError(f'Failed to download image: {e}') from e


def encode_image_to_base64(image_data: bytes) -> str:
    """Encode raw image bytes to base64 string.

    Args:
        image_data: Raw image bytes

    Returns:
        Base64-encoded string (UTF-8)
    """
    return base64.standard_b64encode(image_data).decode('utf-8')


def build_image_content_part(base64_data: str, media_type: str) -> ImageContentPart:
    """Build Letta image content part structure.

    Args:
        base64_data: Base64-encoded image string
        media_type: MIME type (e.g., 'image/jpeg')

    Returns:
        Dict with Letta image content structure
    """
    return {
        'type': 'image',
        'source': {
            'type': 'base64',
            'media_type': media_type,
            'data': base64_data,
        },
    }


async def process_telegram_image(bot: Bot, file_obj: HasFileId) -> ImageContentPart:
    """Process a Telegram image (photo or sticker) into a Letta image content part.

    Downloads the file from Telegram, encodes to base64, detects MIME type,
    and builds the Letta content structure.

    Args:
        bot: Aiogram Bot instance
        file_obj: Any object with file_id (PhotoSize, Sticker, etc.)

    Returns:
        Letta image content part ready for API request

    Raises:
        ImageProcessingError: If any step fails
    """
    image_data, file_path = await download_telegram_file(bot, file_obj)

    base64_data = encode_image_to_base64(image_data)
    media_type = get_mime_type(file_path) or DEFAULT_MEDIA_TYPE

    LOGGER.info(
        'Processed image: size=%d bytes, type=%s',
        len(image_data),
        media_type,
    )

    return build_image_content_part(base64_data, media_type)
