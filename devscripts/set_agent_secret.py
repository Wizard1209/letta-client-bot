"""Add or replace one secret on an agent, keeping every other key it holds.

`PATCH /v1/agents/{id}` with `secrets` replaces the whole set, and the agent
object no longer carries the current set (`secrets` is null on every retrieve),
so a naive update wipes the keys the owner set by hand. This reads the live set
from `GET /v1/agents/{id}/secrets`, merges one key into it, and writes it back.

The value comes from `--value`, or is copied from another agent that still has
it with `--from-agent`, so a key never has to pass through a shell history.

Usage:
    uv run python -m devscripts.set_agent_secret KEY --from-agent <agent-id> [-a AGENT]
    uv run python -m devscripts.set_agent_secret KEY --value '...' -a AGENT --execute
"""

import argparse

from devscripts.bootstrap import letta, print_config, resolve_agent_id


def agent_secrets(agent_id: str) -> dict[str, str]:
    """Read an agent's secrets from their own endpoint (the SDK has no method)."""
    entries = letta.get(f'/v1/agents/{agent_id}/secrets', cast_to=list[dict[str, str]])
    return {e['key']: e['value'] for e in entries}


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser()
    parser.add_argument('key')
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--value')
    source.add_argument('--from-agent', metavar='AGENT_ID')
    parser.add_argument('--agent-id', '-a')
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()

    agent_id = resolve_agent_id(args.agent_id)
    print_config(agent_id=agent_id, key=args.key, execute=args.execute)

    if args.from_agent:
        donor = agent_secrets(args.from_agent)
        if args.key not in donor:
            raise SystemExit(f'{args.from_agent} has no {args.key}')
        value = donor[args.key]
    else:
        value = args.value

    current = agent_secrets(agent_id)
    print(f'current keys: {sorted(current)}')
    if current.get(args.key) == value:
        print(f'{args.key} already set to this value; nothing to do')
        return
    verb = 'replacing' if args.key in current else 'adding'
    print(f'{verb} {args.key} ({len(value)} chars)')

    if not args.execute:
        print('dry-run; pass --execute to apply')
        return

    letta.agents.update(agent_id=agent_id, secrets={**current, args.key: value})
    after = agent_secrets(agent_id)
    lost = set(current) - set(after)
    ok = after.get(args.key) == value and not lost
    print(f'applied: {ok}  keys now: {sorted(after)}' + (f'  LOST {lost}' if lost else ''))


if __name__ == '__main__':
    main()
