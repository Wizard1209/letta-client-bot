from collections.abc import Awaitable, Callable, Iterable, Iterator
from functools import wraps
import mimetypes
import time
from typing import Any, ParamSpec, TypeVar
from uuid import UUID

from aiogram.types import MessageEntity
from aiogram.utils.formatting import Text

from md_tg import markdown_to_telegram
from md_tg.utils import utf16_len

CHUNK_MAX_LEN = 2048

P = ParamSpec('P')
R = TypeVar('R')


def async_cache(
    ttl: int = 300,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """
    Async cache decorator with TTL expiration.

    Args:
        ttl: Time-to-live in seconds (default: 300 = 5 minutes)

    Usage:
        @async_cache(ttl=60)
        async def get_user(user_id: int):
            return await db.fetch_user(user_id)
    """
    cache: dict[tuple[Any, ...], tuple[Any, float]] = {}

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            key = (args, tuple(sorted(kwargs.items())))
            if key in cache:
                result, timestamp = cache[key]
                if time.time() - timestamp < ttl:
                    return result  # type: ignore[no-any-return]
            result = await func(*args, **kwargs)
            cache[key] = (result, time.time())
            return result

        # TODO: Add cache.clear() method for invalidation
        # TODO: Add maxsize limit to prevent unbounded growth

        return wrapper

    return decorator


def validate_uuid(uuid_str: str) -> bool:
    """Validate UUID string format.

    Args:
        uuid_str: UUID string

    Returns:
        True if valid, False otherwise
    """
    try:
        UUID(uuid_str)
        return True
    except ValueError:
        return False


def parse_version(version: str) -> tuple[int, ...]:
    """Parse version string to comparable tuple."""
    return tuple(int(x) for x in version.split('.'))


def version_needs_update(current: str | None, required: str) -> bool:
    """Check if current version is missing or lower than required."""
    if not current:
        return True
    try:
        return parse_version(current) < parse_version(required)
    except ValueError:
        return True


def get_mime_type(file_name: str | None) -> str | None:
    """Detect MIME type from file name using standard library.

    Args:
        file_name: File name with extension (e.g., 'document.pdf')

    Returns:
        MIME type string or None if unknown
    """
    if not file_name:
        return None

    mime_type, _ = mimetypes.guess_type(file_name)
    return mime_type


def chunk_texts(
    parts: Iterable[Text],
    max_len: int = CHUNK_MAX_LEN,
    separator: str = '\n',
) -> Iterator[tuple[str, list[MessageEntity]]]:
    """Yield (text, entities) chunks from aiogram Text parts.

    Renders each Text part, accumulates with separator until the next
    part would exceed max_len, then yields the chunk and starts a new one.

    Args:
        parts: Iterable of aiogram Text objects
        max_len: Max UTF-16 length per chunk (default: 2048)
        separator: String between parts within a chunk

    Yields:
        (text, entities) tuples ready for message.answer(text, entities=...)
    """
    chunk_text = ''
    chunk_entities: list[MessageEntity] = []
    chunk_len = 0
    sep_len = utf16_len(separator)

    for part in parts:
        part_text, part_entities = part.render()
        part_len = utf16_len(part_text)

        # Would adding this part exceed the limit?
        needed = part_len + (sep_len if chunk_text else 0)
        if chunk_text and chunk_len + needed > max_len:
            yield chunk_text, chunk_entities
            chunk_text = ''
            chunk_entities = []
            chunk_len = 0

        # Append separator if not first in chunk
        offset = chunk_len
        if chunk_text:
            chunk_text += separator
            offset += sep_len
            chunk_len += sep_len

        # Append part text and shift entity offsets
        chunk_text += part_text
        for entity in part_entities:
            chunk_entities.append(
                MessageEntity(
                    type=entity.type,
                    offset=entity.offset + offset,
                    length=entity.length,
                    url=entity.url,
                    language=entity.language,
                    user=entity.user,
                    custom_emoji_id=entity.custom_emoji_id,
                )
            )
            )
        chunk_len += part_len

    # Yield remaining
    if chunk_text:
        yield chunk_text, chunk_entities


def merge_with_entity(
    header: Text,
    content: str,
    entity_type: str,
    separator: str = '\n',
) -> list[tuple[str, list[MessageEntity]]]:
    """Merge aiogram header with md_tg content and wrap content with entity.

    Use this when you need to wrap content with MessageEntity types not available
    in standard markdown (e.g., expandable_blockquote, spoiler).

    Args:
        header: aiogram Text object (e.g., Italic('Header:'), Bold('Title'))
        content: Markdown content to convert and wrap
        entity_type: MessageEntity type for wrapping content
        separator: String between header and content (default: newline)

    Returns:
        List of (text, entities) tuples for message.answer()

    Example:
        >>> from aiogram.utils.formatting import Italic
        >>> chunks = merge_with_entity(
        ...     header=Italic('Agent reasoning:'),
        ...     content='The user asked about...',
        ...     entity_type='expandable_blockquote',
        ... )
    """
    # Render header via aiogram
    header_text, header_entities = header.render()

    # Handle empty content - return just header
    if not content or not content.strip():
        return [(header_text, list(header_entities))]

    # Convert content via md_tg
    content_chunks = markdown_to_telegram(content)
    if not content_chunks:
        return [(header_text, list(header_entities))]

    header_with_sep_len = utf16_len(header_text + separator)

    result: list[tuple[str, list[MessageEntity]]] = []
    is_first_chunk = True

    for content_text, content_entities in content_chunks:
        content_len = utf16_len(content_text)

        if is_first_chunk:
            is_first_chunk = False

            # Combine: header + separator + content
            combined_text = header_text + separator + content_text

            # Adjust content entities offsets
            adjusted_entities: list[MessageEntity] = []
            for entity in content_entities:
                adjusted_entities.append(
                    MessageEntity(
                        type=entity.type,
                        offset=entity.offset + header_with_sep_len,
                        length=entity.length,
                        url=entity.url,
                        language=entity.language,
                    )
                )

            # Combine: header entities + adjusted content entities
            all_entities = list(header_entities) + adjusted_entities

            # Add wrapping entity for content
            if content_len > 0:
                all_entities.append(
                    MessageEntity(
                        type=entity_type,
                        offset=header_with_sep_len,
                        length=content_len,
                    )
                )

            result.append((combined_text, all_entities))
        else:
            # Subsequent chunks: content only with wrapping entity
            chunk_entities = list(content_entities)
            if content_len > 0:
                chunk_entities.append(
                    MessageEntity(
                        type=entity_type,
                        offset=0,
                        length=content_len,
                    )
                )
            result.append((content_text, chunk_entities))

    return result
