from collections.abc import Awaitable, Callable
from functools import wraps
import time
from typing import Any, ParamSpec, TypeVar
from uuid import UUID

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
