"""Bootstrap module for devscripts - sync clients using project CONFIG.

Usage:
    from devscripts.bootstrap import letta, gel, print_config, resolve_agent_id
    from letta_bot.config import CONFIG

    def main() -> None:
        print_config()
        agents = letta.agents.list()

All scripts should:
1. Import clients from this module
2. Use sync operations (no asyncio)
3. Use CONFIG for env vars
4. Always call print_config() at script start
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv; load_dotenv(Path(__file__).parent.parent / '.env')

import gel as _gel_module
from letta_client import Letta

from letta_bot.config import CONFIG

# Suppress noisy HTTP logs
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)

# Sync Letta client (devscripts are sync-only)
letta = Letta(
    api_key=CONFIG.letta_api_key,
    project_id=CONFIG.letta_project_id,
    timeout=120,
)

# Sync Gel client
gel = _gel_module.create_client()

# Agent ID file location
_AGENT_ID_FILE = Path(__file__).parent.parent / '.agent_id'



def _mask(value: str) -> str:
    """Show last 4 chars of a secret."""
    if len(value) <= 4:
        return '****'
    return f'...{value[-4:]}'


def print_config(**extra: str) -> None:
    """Print key config values for verification. Call at script start."""
    print(f'  project:  {_mask(CONFIG.letta_project_id)}')
    print(f'  api_key:  {_mask(CONFIG.letta_api_key)}')
    for name, value in extra.items():
        print(f'  {name}:  {value}')
    print()


def resolve_agent_id(cli_arg: str | None = None) -> str | None:
    """Resolve agent ID from CLI arg > env > .agent_id file."""
    if cli_arg:
        return cli_arg
    if env_id := os.environ.get('LETTA_AGENT_ID'):
        return env_id
    if _AGENT_ID_FILE.exists():
        return _AGENT_ID_FILE.read_text().strip()
    return None
