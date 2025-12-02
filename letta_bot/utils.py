from collections.abc import Callable
from functools import wraps
import time
from typing import Any, ParamSpec, TypeVar

P = ParamSpec('P')
R = TypeVar('R')


def async_cache(ttl: int = 300) -> Callable[[Callable[P, R]], Callable[P, R]]:
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

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            key = (args, tuple(sorted(kwargs.items())))
            if key in cache:
                result, timestamp = cache[key]
                if time.time() - timestamp < ttl:
                    return result  # type: ignore[return-value]
            result = await func(*args, **kwargs)  # type: ignore[misc]
            cache[key] = (result, time.time())
            return result  # type: ignore[return-value]

        # TODO: Add cache.clear() method for invalidation
        # TODO: Add maxsize limit to prevent unbounded growth

        return wrapper  # type: ignore[return-value]

    return decorator
