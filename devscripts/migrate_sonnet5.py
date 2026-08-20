"""Migrate all sonnet-4-x agents to claude-sonnet-5 and notify them.

Phases:
    backup       - export stale agents (.af) + snapshot llm_config of all targets
    delete-stale - delete the 3 stale agents (after backup)
    migrate      - dry-run by default; --execute to apply; --only for canary

Usage:
    uv run python -m devscripts.migrate_sonnet5 backup --backup-dir <dir>
    uv run python -m devscripts.migrate_sonnet5 delete-stale --backup-dir <dir> --execute
    uv run python -m devscripts.migrate_sonnet5 migrate                    # dry-run
    uv run python -m devscripts.migrate_sonnet5 migrate --execute --only agent-...
    uv run python -m devscripts.migrate_sonnet5 migrate --execute
"""

import argparse
import json
from pathlib import Path

from letta_client import APIError

from devscripts.bootstrap import letta, print_config

TARGET_MODEL = 'anthropic/claude-sonnet-5'
OLD_MODEL_PREFIXES = (
    'anthropic/claude-sonnet-4-5',
    'anthropic/claude-sonnet-4-6',
)

STALE_AGENTS = {
    'agent-797684db-b076-4e6e-afe7-68c058b7f930': 'warm-blue-termite',
    'agent-03da99f4-98ce-4565-bbdf-ac70176ca593': 'whispering-green-armadillo',
    'agent-79f6cf7b-4dc3-4435-b102-b7374af0742b': 'kb-fernando-sonnet',
}

NOTICE = (
    '<system>System upgrade notice: your model has been switched to Claude Sonnet 5 '
    '(anthropic/claude-sonnet-5), the latest Sonnet generation. You are now running '
    'live on the newest model. No action is required.</system>'
)

LLM_FIELDS = (
    'model',
    'model_endpoint_type',
    'context_window',
    'max_tokens',
    'enable_reasoner',
    'max_reasoning_tokens',
    'temperature',
    'reasoning_effort',
    'verbosity',
)


def llm_snapshot(agent) -> dict:
    """Extract comparable llm_config fields."""
    lc = agent.llm_config
    return {f: getattr(lc, f, None) for f in LLM_FIELDS}


def list_targets() -> list:
    """All agents on old sonnet models, stale ones excluded."""
    agents = list(letta.agents.list(limit=200, include=['agent.tags']))
    return [
        a
        for a in agents
        if str(a.model).startswith(OLD_MODEL_PREFIXES) and a.id not in STALE_AGENTS
    ]


def cmd_backup(backup_dir: Path) -> None:
    """Export stale agents and snapshot llm_config of migration targets."""
    stale_dir = backup_dir / 'deleted_agents'
    stale_dir.mkdir(parents=True, exist_ok=True)

    for agent_id, name in STALE_AGENTS.items():
        out = stale_dir / f'{name}.af'
        print(f'  exporting {name} ({agent_id})...')
        out.write_text(letta.agents.export_file(agent_id))
        print(f'  ✓ {out} ({out.stat().st_size} bytes)')

    targets = list_targets()
    snapshot = {
        a.id: {'name': a.name, 'llm_config': llm_snapshot(a), 'tags': a.tags}
        for a in targets
    }
    snap_file = backup_dir / 'sonnet5_migration_backup.json'
    snap_file.write_text(json.dumps(snapshot, indent=2, default=str))
    print(f'  ✓ llm_config snapshot for {len(snapshot)} agents -> {snap_file}')


def cmd_delete_stale(backup_dir: Path, execute: bool) -> None:
    """Delete stale agents; requires backups to exist."""
    for agent_id, name in STALE_AGENTS.items():
        backup = backup_dir / 'deleted_agents' / f'{name}.af'
        if not backup.exists() or backup.stat().st_size == 0:
            print(f'  ✗ no backup for {name}, refusing to delete')
            continue
        if not execute:
            print(f'  [dry-run] would delete {name} ({agent_id})')
            continue
        letta.agents.delete(agent_id)
        try:
            letta.agents.retrieve(agent_id=agent_id)
            print(f'  ✗ {name} still retrievable after delete!')
        except APIError as e:
            status = getattr(e, 'status_code', '?')
            print(f'  ✓ deleted {name} ({agent_id}), retrieve -> {status}')


# Drift that is expected and must NOT be reverted on sonnet-5:
# - temperature -> 1.0 (Anthropic: `temperature` is deprecated for this model;
#   setting it back breaks every LLM call with a 400)
# - max_reasoning_tokens 0 -> 1024 (sonnet-5 default, matches working reference agent)
EXPECTED_DRIFT_FIELDS = {'temperature', 'max_reasoning_tokens'}


def migrate_one(agent, execute: bool, notify: bool) -> tuple[bool, str]:
    """Update model, recompile, verify llm_config survived, restore, notify."""
    before = llm_snapshot(agent)
    label = f'{agent.name} ({agent.id})'
    if not execute:
        custom = {k: v for k, v in before.items() if k != 'model'}
        return True, f'[dry-run] {label}: {before["model"]} -> {TARGET_MODEL} | {custom}'

    # The PATCH may 400 with a stale CONTEXT_WINDOW_EXCEEDED estimate while still
    # applying the model change; recompile below refreshes the estimate.
    update_err = ''
    try:
        letta.agents.update(agent_id=agent.id, model=TARGET_MODEL)
    except APIError as e:
        if 'CONTEXT_WINDOW_EXCEEDED' not in str(e):
            raise
        update_err = ' | update 400 CONTEXT_WINDOW_EXCEEDED (stale estimate)'

    letta.post(f'/v1/agents/{agent.id}/recompile', cast_to=object, body={})

    after_agent = letta.agents.retrieve(agent_id=agent.id)
    after = llm_snapshot(after_agent)

    if TARGET_MODEL.split('/')[-1] not in str(after['model']):
        return False, f'{label}: model after update is {after["model"]}{update_err}'

    drift = {
        f: (before[f], after[f])
        for f in LLM_FIELDS
        if f != 'model' and before[f] != after[f] and f not in EXPECTED_DRIFT_FIELDS
    }
    restored = ''
    if drift:
        restore_kwargs = {}
        if 'context_window' in drift:
            restore_kwargs['context_window_limit'] = before['context_window']
        if 'max_tokens' in drift:
            restore_kwargs['max_tokens'] = before['max_tokens']
        if restore_kwargs:
            letta.agents.update(agent_id=agent.id, **restore_kwargs)
            final = llm_snapshot(letta.agents.retrieve(agent_id=agent.id))
            still = {
                f: (before[f], final[f])
                for f in restore_kwargs_fields(restore_kwargs)
                if before[f] != final[f]
            }
            restored = f' | drift={drift} restored={not still}'
            if still:
                return False, f'{label}: drift not restored: {still}'
        else:
            restored = f' | drift={drift} (not restorable via update, left as is)'

    note = ''
    if notify:
        response = letta.agents.messages.create(
            agent_id=agent.id,
            messages=[{'role': 'user', 'content': NOTICE}],
        )
        stop = getattr(response, 'stop_reason', None)
        stop_val = getattr(stop, 'stop_reason', stop)
        note = f' | notified: stop={stop_val}'
        if str(stop_val) != 'end_turn':
            return False, f'{label}: notified but stop_reason={stop_val}{update_err}'

    return True, f'{label}: -> {after["model"]}{update_err}{restored}{note}'


def restore_kwargs_fields(restore_kwargs: dict) -> list[str]:
    """Map update() kwargs back to llm_config field names."""
    mapping = {'context_window_limit': 'context_window', 'max_tokens': 'max_tokens'}
    return [mapping[k] for k in restore_kwargs]


def cmd_migrate(execute: bool, only: str | None, notify: bool) -> None:
    """Migrate all target agents (or one, with --only)."""
    targets = list_targets()
    if only:
        targets = [a for a in targets if a.id == only]
        if not targets:
            print(f'  ✗ {only} is not among migration targets')
            return

    print(f'\n{len(targets)} agent(s) to migrate -> {TARGET_MODEL}\n')
    ok = failed = 0
    for agent in targets:
        try:
            success, info = migrate_one(agent, execute, notify)
        except APIError as e:
            success, info = False, f'{agent.name} ({agent.id}): APIError {e}'
        print(f'  {"✓" if success else "✗"} {info}')
        ok, failed = ok + success, failed + (not success)

    print(f'\nDone: {ok} ok, {failed} failed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Migrate sonnet agents to sonnet-5')
    parser.add_argument('phase', choices=['backup', 'delete-stale', 'migrate'])
    parser.add_argument('--backup-dir', type=Path, default=Path('.'))
    parser.add_argument('--execute', action='store_true', help='apply changes')
    parser.add_argument('--only', help='limit migrate to a single agent id (canary)')
    parser.add_argument('--no-notify', action='store_true', help='skip <system> notice')
    args = parser.parse_args()

    print_config(phase=args.phase, execute=str(args.execute))
    if args.phase == 'backup':
        cmd_backup(args.backup_dir)
    elif args.phase == 'delete-stale':
        cmd_delete_stale(args.backup_dir, args.execute)
    else:
        cmd_migrate(args.execute, args.only, notify=not args.no_notify)
