#!/usr/bin/env python3
"""CLI script to test custom Letta tools with injected context.

Injects same variables as Letta cloud runtime:
- client: Letta SDK client (global)
- LETTA_AGENT_ID: Agent ID (env var)
- LETTA_PROJECT_ID: Project ID (env var, from .env)

Agent ID source (in order):
1. --agent-id CLI argument
2. LETTA_AGENT_ID env var
3. .agent_id file in project root

Usage:
    uv run python -m devscripts.run_tool <tool_name> [args...]
    uv run python -m devscripts.run_tool --agent-id <id> <tool_name> [args...]

Examples:
    uv run python -m devscripts.run_tool notify_via_telegram "Hello world"
    uv run python -m devscripts.run_tool schedule_message "Reminder" 3600
    uv run python -m devscripts.run_tool search_x_posts "TzKT OR PyTezos" 24 20
"""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys

from devscripts.bootstrap import letta

PROJECT_ROOT = Path(__file__).parent.parent
TOOLS_DIR = PROJECT_ROOT / 'letta_bot' / 'custom_tools'
AGENT_ID_FILE = PROJECT_ROOT / '.agent_id'


def get_agent_id(cli_agent_id: str | None) -> str | None:
    """Get agent ID from CLI arg, env var, or .agent_id file."""
    # 1. CLI argument
    if cli_agent_id:
        return cli_agent_id

    # 2. Environment variable
    if env_id := os.environ.get('LETTA_AGENT_ID'):
        return env_id

    # 3. .agent_id file
    if AGENT_ID_FILE.exists():
        return AGENT_ID_FILE.read_text().strip()

    return None


def load_tool_function(tool_name: str):
    """Load tool function with injected client."""
    tool_file = TOOLS_DIR / f'{tool_name}.py'

    if not tool_file.exists():
        raise FileNotFoundError(f'Tool file not found: {tool_file}')

    spec = importlib.util.spec_from_file_location(tool_name, tool_file)
    if spec is None or spec.loader is None:
        raise ImportError(f'Cannot load spec for {tool_file}')

    module = importlib.util.module_from_spec(spec)

    # Inject client into module's global namespace (like Letta runtime does)
    module.__dict__['client'] = letta

    spec.loader.exec_module(module)

    if not hasattr(module, tool_name):
        raise AttributeError(f'Function {tool_name} not found in {tool_file}')

    return getattr(module, tool_name)


def parse_arg(arg: str):
    """Parse CLI argument to appropriate type."""
    for parser in (int, float, json.loads):
        try:
            return parser(arg)
        except (ValueError, json.JSONDecodeError):
            pass
    return arg


def list_tools() -> list[str]:
    """List available tool names."""
    return sorted(f.stem for f in TOOLS_DIR.glob('*.py') if not f.name.startswith('_'))


def main():
    parser = argparse.ArgumentParser(
        description='Test custom Letta tools with injected context',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('tool_name', nargs='?', help='Name of the tool (without .py)')
    parser.add_argument('args', nargs='*', help='Arguments to pass to the tool')
    parser.add_argument('-l', '--list', action='store_true', help='List available tools')
    parser.add_argument(
        '-a',
        '--agent-id',
        help='Agent ID to inject (also reads from LETTA_AGENT_ID env or .agent_id file)',
    )

    args = parser.parse_args()

    if args.list:
        print('Available tools:')
        for tool in list_tools():
            print(f'  - {tool}')
        return 0

    if not args.tool_name:
        parser.print_help()
        return 1

    # Resolve and inject agent ID
    agent_id = get_agent_id(args.agent_id)
    if agent_id:
        os.environ['LETTA_AGENT_ID'] = agent_id
        print(f'Agent ID: {agent_id}')
    else:
        print('Warning: No agent ID found (some tools may fail)')
        print(f'  Set via: --agent-id, LETTA_AGENT_ID env, or {AGENT_ID_FILE}')

    # Load tool with injected client
    try:
        tool_fn = load_tool_function(args.tool_name)
    except (FileNotFoundError, ImportError, AttributeError) as e:
        print(f'Error: {e}')
        print(f'\nAvailable tools: {", ".join(list_tools())}')
        return 1

    parsed_args = [parse_arg(a) for a in args.args]

    print(f'Running {args.tool_name}({", ".join(repr(a) for a in parsed_args)})')
    print('-' * 50)

    try:
        result = tool_fn(*parsed_args)
        print(result)
    except TypeError as e:
        print(f'Error: {e}')
        print(f'\nFunction signature: {tool_fn.__doc__}')
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
