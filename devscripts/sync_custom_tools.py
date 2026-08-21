"""Push custom tool sources to Letta and backfill the LETTA_API_KEY secret.

The sandbox's injected `client` is built from LETTA_API_KEY and is None on any
agent whose `secrets` lack that key, so every tool builds its own client from
the same variable. Agents created before the change do not carry it — hence the
backfill.

Dry-run by default; nothing is written without --execute.

Usage:
    uv run python -m devscripts.sync_custom_tools                  # dry-run
    uv run python -m devscripts.sync_custom_tools --execute
    uv run python -m devscripts.sync_custom_tools --execute --tools-only
    uv run python -m devscripts.sync_custom_tools --execute --secrets-only
"""

import argparse
from pathlib import Path

from devscripts.bootstrap import letta, print_config
from letta_bot.config import CONFIG

TOOLS_DIR = Path(__file__).parent.parent / 'letta_bot' / 'custom_tools'

# Tools that call back into the Letta API and therefore need LETTA_API_KEY.
CLIENT_DEPENDENT = (
    'notify_via_telegram',
    'schedule_message',
    'list_scheduled_messages',
    'delete_scheduled_message',
)


def push_tools(execute: bool) -> None:
    """Write each tool's repo source onto its existing platform object.

    Updates by tool_id rather than upserting: `upsert` derives the tool name
    from the FIRST top-level function in the source, so a file whose helper is
    defined above the tool function registers under the helper's name and
    leaves the real tool — and every agent attached to it — untouched.
    """
    on_platform = {t.name: t for t in letta.tools.list(limit=200)}

    for name in CLIENT_DEPENDENT:
        local = (TOOLS_DIR / f'{name}.py').read_text()
        remote = on_platform.get(name)

        if remote is None:
            print(f'  {name}: NOT on platform — attach it manually first, skipping')
            continue
        if (remote.source_code or '').strip() == local.strip():
            print(f'  {name}: already up to date')
            continue

        print(f'  {name}: differs from repo — updating {remote.id}')
        if execute:
            tool = letta.tools.update(remote.id, source_code=local)
            ok = tool.name == name and tool.id == remote.id
            print(f'    -> {tool.id} name={tool.name}' + ('' if ok else '  *** MISMATCH ***'))


def backfill_secrets(execute: bool) -> None:
    """Ensure every agent using a client-dependent tool holds LETTA_API_KEY."""
    needed = 0

    for listed in letta.agents.list(limit=200):
        agent = letta.agents.retrieve(agent_id=listed.id)
        tools = {t.name for t in (agent.tools or [])}
        if not tools & set(CLIENT_DEPENDENT):
            continue

        # `secrets` supersedes the deprecated tool_exec_environment_variables,
        # but reads still come back on both — check whichever is populated.
        current = agent.secrets or agent.tool_exec_environment_variables or []
        if any(e.key == 'LETTA_API_KEY' for e in current):
            continue

        needed += 1
        kept = sorted(e.key for e in current)
        print(f'  {agent.name} ({agent.id}): missing LETTA_API_KEY, keeping {kept}')
        if execute:
            # `secrets` REPLACES the whole set, so resend the existing keys
            # alongside the new one or they are dropped.
            merged = {e.key: e.value for e in current}
            merged['LETTA_API_KEY'] = CONFIG.letta_api_key
            letta.agents.update(agent_id=agent.id, secrets=merged)

            after = {e.key for e in (letta.agents.retrieve(agent_id=agent.id).secrets or [])}
            missing = set(merged) - after
            print(f'    set, {len(after)} secrets' + (f' — LOST {missing}' if missing else ''))

    print(f'  agents needing the key: {needed}')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='apply changes')
    parser.add_argument('--tools-only', action='store_true')
    parser.add_argument('--secrets-only', action='store_true')
    args = parser.parse_args()

    print_config(mode='EXECUTE' if args.execute else 'dry-run')

    if not args.secrets_only:
        print('Tool sources:')
        push_tools(args.execute)

    if not args.tools_only:
        print('Agent secrets:')
        backfill_secrets(args.execute)

    if not args.execute:
        print('\nDry-run. Re-run with --execute to apply.')


if __name__ == '__main__':
    main()
