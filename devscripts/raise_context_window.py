"""Raise the context window of claude-sonnet-5 agents to the model's real limit.

Agents migrated to sonnet-5 kept the narrow context windows inherited from
haiku / sonnet-4 (50k-95k) while the model supports 1M. Combined with the
`max_tokens` output reservation this leaves too little room for tool results:
every tool call overflows the window, Letta compacts, the agent loses the data
it just fetched and re-fetches it.

Dry-run by default; pass --execute to apply. Every change is verified by
re-reading the agent, and the prior llm_config is written to a backup file.

Usage:
    uv run python -m devscripts.raise_context_window                    # dry-run
    uv run python -m devscripts.raise_context_window --execute
    uv run python -m devscripts.raise_context_window --execute --only agent-...
"""

import argparse
import json
from pathlib import Path

from devscripts.bootstrap import letta, print_config

TARGET_MODEL = 'claude-sonnet-5'
TARGET_WINDOW = 200_000


def headroom(agent_id: str, ctx: int, max_tokens: int) -> int | None:
    """Free tokens for tool results: window - static footprint - output reserve."""
    try:
        c = letta.get(f'/v1/agents/{agent_id}/context', cast_to=object)
    except Exception:  # noqa: BLE001
        return None
    return ctx - c['context_window_size_current'] - max_tokens


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--execute', action='store_true', help='apply changes')
    ap.add_argument('--only', help='limit to a single agent id')
    ap.add_argument(
        '--backup-dir',
        type=Path,
        default=Path('.'),
        help='where to write the llm_config backup',
    )
    args = ap.parse_args()
    print_config(target=f'{TARGET_MODEL} -> {TARGET_WINDOW}', execute=str(args.execute))

    targets = [
        a
        for a in letta.agents.list(limit=200)
        if TARGET_MODEL in str(getattr(a.llm_config, 'model', ''))
        and (getattr(a.llm_config, 'context_window', 0) or 0) < TARGET_WINDOW
    ]
    if args.only:
        targets = [a for a in targets if a.id == args.only]

    if not targets:
        print('Nothing to do — every sonnet-5 agent is already at the target window.')
        return

    print(f'{len(targets)} agent(s) below {TARGET_WINDOW}:\n')

    if args.execute:
        backup = {
            a.id: {
                'name': a.name,
                'context_window': a.llm_config.context_window,
                'max_tokens': a.llm_config.max_tokens,
                'model': str(a.llm_config.model),
            }
            for a in targets
        }
        path = args.backup_dir / 'context_window_backup.json'
        path.write_text(json.dumps(backup, indent=2, default=str))
        print(f'backup -> {path}\n')

    ok = failed = 0
    for a in targets:
        before = a.llm_config.context_window
        max_tok = a.llm_config.max_tokens or 0
        hr_before = headroom(a.id, before, max_tok)

        if not args.execute:
            print(
                f'  [dry-run] {a.name:32s} {before:6d} -> {TARGET_WINDOW} '
                f'(headroom {hr_before})'
            )
            continue

        try:
            letta.agents.update(agent_id=a.id, context_window_limit=TARGET_WINDOW)
        except Exception as e:  # noqa: BLE001
            print(f'  ✗ {a.name:32s} update failed: {type(e).__name__} {e}')
            failed += 1
            continue

        # Verify by re-reading, not by trusting the PATCH response.
        fresh = letta.get(f'/v1/agents/{a.id}', cast_to=object)
        after = fresh['llm_config']['context_window']
        if after != TARGET_WINDOW:
            print(f'  ✗ {a.name:32s} readback says {after}, expected {TARGET_WINDOW}')
            failed += 1
            continue

        hr_after = headroom(a.id, after, fresh['llm_config']['max_tokens'] or 0)
        drift = ''
        if str(fresh['llm_config']['model']) != str(a.llm_config.model):
            drift = f'  !! model drifted -> {fresh["llm_config"]["model"]}'
        print(
            f'  ✓ {a.name:32s} {before:6d} -> {after} | '
            f'headroom {hr_before} -> {hr_after}{drift}'
        )
        ok += 1

    if args.execute:
        print(f'\nDone: {ok} ok, {failed} failed.')


if __name__ == '__main__':
    main()
