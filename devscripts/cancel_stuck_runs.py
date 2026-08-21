"""Cancel runs left active on agents, which block all new messages.

A run that never reaches a terminal state keeps holding its conversation, and
every later message is refused with 409 "Another request is currently being
processed for this conversation". The run stays listed as `running` or
`created` indefinitely, so the agent looks healthy while silently rejecting
everything.

Only runs older than --min-age-hours are touched, so a genuinely in-flight
request is never cancelled. Dry-run by default.

Usage:
    uv run python -m devscripts.cancel_stuck_runs                  # dry-run
    uv run python -m devscripts.cancel_stuck_runs --execute
    uv run python -m devscripts.cancel_stuck_runs --min-age-hours 24 --execute
"""

import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from devscripts.bootstrap import letta, print_config


def active_runs() -> dict:
    """Collect distinct active runs (the listing repeats once it wraps)."""
    seen = {}
    for run in letta.runs.list(active=True, limit=100):
        if run.id in seen:
            break
        seen[run.id] = run
    return seen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='actually cancel')
    parser.add_argument(
        '--min-age-hours',
        type=float,
        default=1.0,
        help='leave runs younger than this alone (default: 1)',
    )
    args = parser.parse_args()

    print_config(
        mode='EXECUTE' if args.execute else 'dry-run',
        min_age_hours=str(args.min_age_hours),
    )

    names = {a.id: a.name for a in letta.agents.list(limit=200)}
    cutoff = datetime.now(timezone.utc) - timedelta(hours=args.min_age_hours)

    stuck = defaultdict(list)
    for run in active_runs().values():
        created = run.created_at
        if not isinstance(created, datetime):
            created = datetime.fromisoformat(str(created))
        if created >= cutoff:
            print(f'  skip (recent, may be live): {run.id} on {names.get(run.agent_id)}')
            continue
        stuck[run.agent_id].append((run.id, created, run.status))

    if not stuck:
        print('  no stuck runs')
        return

    for agent_id, runs in stuck.items():
        name = names.get(agent_id, agent_id)
        print(f'  {name}: {len(runs)} stuck')
        for run_id, created, status in runs:
            print(f'      {status:9} since {str(created)[:19]}  {run_id}')
        if args.execute:
            letta.agents.messages.cancel(agent_id, run_ids=[r[0] for r in runs])

    if args.execute:
        left = {r.agent_id for r in active_runs().values() if r.agent_id in stuck}
        remaining = [names.get(a, a) for a in left]
        print(f'\n  cancelled; still active: {remaining or "none"}')
    else:
        print('\nDry-run. Re-run with --execute to cancel.')


if __name__ == '__main__':
    main()
