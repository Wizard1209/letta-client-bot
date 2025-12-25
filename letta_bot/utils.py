from collections.abc import Awaitable, Callable, Sequence
from functools import wraps
import time
from typing import Any, ParamSpec, TypeVar, overload
from uuid import UUID

from aiogram.types import MessageEntity as AiogramEntity

from md_tg.config import MessageEntity as MdTgEntity

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


@overload
def to_aiogram_entities(entities: MdTgEntity) -> AiogramEntity: ...


@overload
def to_aiogram_entities(entities: Sequence[MdTgEntity]) -> list[AiogramEntity]: ...


def to_aiogram_entities(
    entities: MdTgEntity | Sequence[MdTgEntity],
) -> AiogramEntity | list[AiogramEntity]:
    """Convert md_tg MessageEntity to aiogram MessageEntity format.

    Supports both single entity and list of entities.

    Args:
        entities: Single MessageEntity dict or list of MessageEntity dicts from md_tg

    Returns:
        Single aiogram MessageEntity or list of aiogram MessageEntity instances

    Examples:
        >>> from md_tg import markdown_to_telegram
        >>>
        >>> # Single chunk
        >>> text, entities = markdown_to_telegram('**Bold**')[0]
        >>> await message.answer(text, entities=to_aiogram_entities(entities))
        >>>
        >>> # Multiple chunks
        >>> chunks = markdown_to_telegram(long_markdown)
        >>> for text, entities in chunks:
        ...     await message.answer(text, entities=to_aiogram_entities(entities))
    """
    # Check if single entity (has 'type' key)
    if isinstance(entities, dict) and 'type' in entities:
        return AiogramEntity(
            type=entities['type'],
            offset=entities['offset'],
            length=entities['length'],
            url=entities.get('url'),
            language=entities.get('language'),
        )

    # List of entities
    return [
        AiogramEntity(
            type=e['type'],
            offset=e['offset'],
            length=e['length'],
            url=e.get('url'),
            language=e.get('language'),
        )
        for e in entities
    ]
