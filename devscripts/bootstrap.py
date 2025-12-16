"""Bootstrap module for devscripts - sync clients with plain env loading.

Usage:
    from devscripts.bootstrap import letta, gel, env

    # Access env vars directly
    print(env('SOME_VAR'))
    print(env('OPTIONAL_VAR', 'default'))

    # Use sync Letta client
    agents = letta.agents.list()

    # Use sync Gel client
    result = gel.query('select User { telegram_id }')

All scripts should:
1. Import from this module (not letta_bot.client or letta_bot.config)
2. Use sync operations (no asyncio)
3. Access env vars via env() helper
"""

from functools import lru_cache
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root (once at import time)
_PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(_PROJECT_ROOT / '.env')

# Suppress noisy HTTP logs by default
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)


def env(key: str, default: str | None = None) -> str:
    """Get environment variable with optional default.

    Args:
        key: Environment variable name
        default: Default value if not set (None means required)

    Returns:
        Environment variable value

    Raises:
        KeyError: If variable not set and no default provided
    """
    value = os.environ.get(key)
    if value is None:
        if default is None:
            raise KeyError(f'{key} not set in environment')
        return default
    return value


@lru_cache
def get_letta():
    """Get sync Letta client (cached).

    Returns:
        Letta: Sync Letta client instance
    """
    from letta_client import Letta

    return Letta(
        api_key=env('LETTA_API_KEY'),
        project_id=env('LETTA_PROJECT_ID'),
        timeout=120,
    )


@lru_cache
def get_gel():
    """Get sync Gel client (cached).

    Returns:
        gel.Client: Sync Gel client instance
    """
    import gel as gel_module

    return gel_module.create_client()


# Lazy client proxies - import once, use everywhere
class _LazyClient:
    """Lazy proxy that creates client on first access."""

    def __init__(self, factory):
        self._factory = factory
        self._client = None

    def __getattr__(self, name):
        if self._client is None:
            self._client = self._factory()
        return getattr(self._client, name)


# Pre-configured clients (lazy-loaded)
letta = _LazyClient(get_letta)
gel = _LazyClient(get_gel)
