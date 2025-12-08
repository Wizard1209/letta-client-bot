#!/usr/bin/env python3
"""CLI script to test custom Letta tools with .env loaded.

Usage:
    uv run python -m devscripts.run_tool <tool_name> [args...]

Examples:
    uv run python -m devscripts.run_tool get_x_user_posts elonmusk 12 10
    uv run python -m devscripts.run_tool notify_via_telegram "Hello world"
    uv run python -m devscripts.run_tool schedule_message "Reminder" 3600
"""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys


def load_env(env_path: Path) -> None:
    """Load environment variables from .env file."""
    if not env_path.exists():
        print(f'Warning: {env_path} not found')
        return

    with open(env_path) as f:
        for line in f:
            line = line.strip()
            # Skip empty lines and comments
            if not line or line.startswith('#'):
                continue
            # Parse KEY=value
            if '=' in line:
                key, _, value = line.partition('=')
                key = key.strip()
                value = value.strip()
                # Don't override existing env vars
                if key and key not in os.environ:
                    os.environ[key] = value


def load_tool_function(tool_name: str, tools_dir: Path):
    """Dynamically load a tool function from custom_tools directory."""
    tool_file = tools_dir / f'{tool_name}.py'

    if not tool_file.exists():
        raise FileNotFoundError(f'Tool file not found: {tool_file}')

    spec = importlib.util.spec_from_file_location(tool_name, tool_file)
    if spec is None or spec.loader is None:
        raise ImportError(f'Cannot load spec for {tool_file}')

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Get the function with same name as module
    if not hasattr(module, tool_name):
        raise AttributeError(f'Function {tool_name} not found in {tool_file}')

    return getattr(module, tool_name)


def parse_arg(arg: str):
    """Parse CLI argument, attempting to convert to appropriate type."""
    # Try int
    try:
        return int(arg)
    except ValueError:
        pass

    # Try float
    try:
        return float(arg)
    except ValueError:
        pass

    # Try JSON (for complex types)
    try:
        return json.loads(arg)
    except json.JSONDecodeError:
        pass

    # Return as string
    return arg


def list_tools(tools_dir: Path) -> list[str]:
    """List available tool names."""
    tools = []
    for f in tools_dir.glob('*.py'):
        if not f.name.startswith('_'):
            tools.append(f.stem)
    return sorted(tools)


def main():
    project_root = Path(__file__).parent.parent
    tools_dir = project_root / 'letta_bot' / 'custom_tools'
    env_path = project_root / '.env'

    parser = argparse.ArgumentParser(
        description='Test custom Letta tools with .env loaded',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        'tool_name',
        nargs='?',
        help='Name of the tool to run (without .py)',
    )
    parser.add_argument(
        'args',
        nargs='*',
        help='Arguments to pass to the tool function',
    )
    parser.add_argument(
        '-l',
        '--list',
        action='store_true',
        help='List available tools',
    )
    parser.add_argument(
        '-e',
        '--env',
        default=str(env_path),
        help=f'Path to .env file (default: {env_path})',
    )

    args = parser.parse_args()

    # List tools mode
    if args.list:
        tools = list_tools(tools_dir)
        print('Available tools:')
        for tool in tools:
            print(f'  - {tool}')
        return 0

    if not args.tool_name:
        parser.print_help()
        return 1

    # Load environment
    load_env(Path(args.env))

    # Load and run tool
    try:
        tool_fn = load_tool_function(args.tool_name, tools_dir)
    except (FileNotFoundError, ImportError, AttributeError) as e:
        print(f'Error: {e}')
        print(f'\nAvailable tools: {", ".join(list_tools(tools_dir))}')
        return 1

    # Parse arguments
    parsed_args = [parse_arg(a) for a in args.args]

    # Run tool
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
