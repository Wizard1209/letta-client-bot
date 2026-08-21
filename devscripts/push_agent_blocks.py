"""Push memory blocks from a lab instance onto the live agent it was taken from.

Usage:
    uv run python -m devscripts.push_agent_blocks <instance> [--blocks a,b] [--execute]

The lab keeps a copy of a production agent's memory blocks under
`lab/agents/<instance>/blocks/`, edits them there, and measures the edits. This
puts the measured state back. Dry run by default: it prints a diff per block and
changes nothing until `--execute`.

Only blocks that already exist on the agent are touched, and only by label. A
block in the lab copy that the agent does not have is reported and skipped
rather than created -- the lab is a mirror of production, not a source for it.
"""

import argparse
import difflib
from pathlib import Path

from devscripts.bootstrap import letta, print_config

LAB_AGENTS = Path(__file__).resolve().parent.parent / 'lab' / 'agents'


def _local(instance: str) -> dict[str, str]:
    root = LAB_AGENTS / instance / 'blocks'
    if not root.exists():
        raise SystemExit(f'no lab instance at {root}')
    return {p.stem: p.read_text() for p in sorted(root.glob('*.md'))}


def _agent_id(instance: str) -> str:
    """Which live agent this instance mirrors, as recorded by the lab."""
    import json

    spec = json.loads((LAB_AGENTS / instance / 'spec.json').read_text())
    agent_id = spec.get('tools_from')
    if not agent_id:
        raise SystemExit(f'{instance}/spec.json has no `tools_from` -- no live counterpart')
    return str(agent_id)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('instance')
    parser.add_argument('--blocks', help='comma-separated labels; default: all that differ')
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()

    agent_id = _agent_id(args.instance)
    print_config(instance=args.instance, agent=agent_id, execute=args.execute)

    local = _local(args.instance)
    if args.blocks:
        wanted = {b.strip() for b in args.blocks.split(',')}
        missing = wanted - set(local)
        if missing:
            raise SystemExit(f'not in the lab copy: {sorted(missing)}')
        local = {k: v for k, v in local.items() if k in wanted}

    remote = {b.label: b for b in letta.agents.blocks.list(agent_id=agent_id)}

    changed = []
    for label, text in local.items():
        block = remote.get(label)
        if block is None:
            print(f'SKIP  {label}: agent has no such block')
            continue
        if (block.value or '') == text:
            print(f'same  {label}')
            continue
        changed.append((label, block, text))
        diff = list(
            difflib.unified_diff(
                (block.value or '').splitlines(),
                text.splitlines(),
                fromfile=f'{label} (live)',
                tofile=f'{label} (lab)',
                lineterm='',
                n=1,
            )
        )
        added = sum(1 for line in diff if line.startswith('+') and not line.startswith('+++'))
        removed = sum(1 for line in diff if line.startswith('-') and not line.startswith('---'))
        print(f'DIFF  {label}: +{added} -{removed} lines, '
              f'{len(block.value or "")} -> {len(text)} chars')
        for line in diff[:40]:
            print('   ' + line)
        if len(diff) > 40:
            print(f'   ... {len(diff) - 40} more diff lines')

    if not changed:
        print('\nnothing to push')
        return
    if not args.execute:
        print(f'\ndry run: {len(changed)} block(s) would change. Re-run with --execute')
        return

    for label, block, text in changed:
        letta.blocks.update(block_id=block.id, value=text)
        print(f'pushed {label}')
    print(f'\n{len(changed)} block(s) updated on {agent_id}')


if __name__ == '__main__':
    main()
