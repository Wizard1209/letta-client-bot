#!/usr/bin/env python3
"""CLI script to test custom Letta tools.

Two execution paths:
- default: runs the LOCAL file in this process, with LETTA_AGENT_ID,
  LETTA_API_KEY and LETTA_PROJECT_ID set as env vars. Fast, but it is an
  imitation of the sandbox and can drift from it.
- --remote: runs the source REGISTERED ON THE PLATFORM inside the Letta
  sandbox as the agent. This is production. Confirm here before trusting
  a green local run.

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
    uv run python -m devscripts.run_tool -r -a <id> notify_via_telegram "Hi"
"""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys

from devscripts.bootstrap import letta, print_config, resolve_agent_id
from letta_bot.config import CONFIG

PROJECT_ROOT = Path(__file__).parent.parent
TOOLS_DIR = PROJECT_ROOT / 'letta_bot' / 'custom_tools'


def load_tool_function(tool_name: str):
    """Load tool function with injected client."""
    tool_file = TOOLS_DIR / f'{tool_name}.py'

    if not tool_file.exists():
        raise FileNotFoundError(f'Tool file not found: {tool_file}')

    spec = importlib.util.spec_from_file_location(tool_name, tool_file)
    if spec is None or spec.loader is None:
        raise ImportError(f'Cannot load spec for {tool_file}')

    module = importlib.util.module_from_spec(spec)

    # No `client` injection here on purpose. The sandbox builds its own from
    # LETTA_API_KEY and leaves it None when the agent has no such secret, so a
    # harness that always supplies one cannot fail on tools that rely on it.
    # Tools build their own client (see --remote for the production path).
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


def run_remote(tool_name: str, agent_id: str, raw_args: list[str]) -> int:
    """Run the tool in the Letta sandbox, as the agent, on the deployed source.

    Mirrors production: the agent's secrets and LETTA_AGENT_ID are loaded, and
    whatever source is registered on the platform runs — not the local file.
    """
    import inspect

    # Positional CLI args -> named args, using the local signature for names.
    tool_fn = load_tool_function(tool_name)
    names = list(inspect.signature(tool_fn).parameters)
    call_args = {n: parse_arg(v) for n, v in zip(names, raw_args)}

    print(f'Running {tool_name}({call_args}) remotely on {agent_id}')
    print('-' * 50)

    result = letta.agents.tools.run(tool_name, agent_id=agent_id, args=call_args)

    print(f'status: {result.status}')
    print(result.func_return)
    if result.stdout:
        print(f'stdout: {result.stdout}')
    if result.stderr:
        print(f'stderr: {result.stderr}')

    # The platform reports status='success' even when the tool returns an error
    # string, so the payload is what decides the exit code.
    payload = str(result.func_return or '')
    failed = result.status != 'success' or 'Error' in payload or 'Traceback' in payload
    return 1 if failed else 0


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
    parser.add_argument(
        '-r',
        '--remote',
        action='store_true',
        help='Run the tool in the Letta sandbox as the agent, not locally. '
        'This is the production execution path — use it to confirm a tool '
        'really works before trusting a green local run.',
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
    agent_id = resolve_agent_id(args.agent_id)
    if agent_id:
        os.environ['LETTA_AGENT_ID'] = agent_id
    else:
        print('Warning: No agent ID found (some tools may fail)')
        print('  Set via: --agent-id, LETTA_AGENT_ID env, or .agent_id file')

    print_config(agent_id=agent_id or '(none)')

    if args.remote:
        if not agent_id:
            print('Error: --remote needs an agent ID (the sandbox runs as the agent)')
            return 1
        return run_remote(args.tool_name, agent_id, args.args)

    # Locally, LETTA_API_KEY stands in for the agent secret the sandbox provides.
    os.environ.setdefault('LETTA_API_KEY', CONFIG.letta_api_key)

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
