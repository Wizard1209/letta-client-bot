"""Detect agents stuck in a compaction/summarization loop.

Signal: a `system_alert` user_message containing the compaction notice
("prior messages with the user are available in external context") injected
before nearly every step, i.e. the context window overflows on each turn.

Usage:
    uv run python -m devscripts._detect_compaction_loop [limit]
"""

import sys
from collections import Counter

from devscripts.bootstrap import letta, print_config

MARKER = 'available in external context'


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    print_config(limit=str(limit))

    rows = []
    for a in letta.agents.list(limit=200):
        try:
            page = letta.agents.messages.list(a.id, limit=limit, order='desc')
            msgs = list(page.data) if hasattr(page, 'data') else list(page)
        except Exception as e:  # noqa: BLE001
            print(f'  !! {a.name}: {type(e).__name__}')
            continue
        if not msgs:
            continue

        alerts = [m for m in msgs if MARKER in str(getattr(m, 'content', ''))]
        steps = sum(
            1 for m in msgs if getattr(m, 'message_type', '') == 'tool_call_message'
        )
        newest = getattr(msgs[0], 'date', None)
        oldest = getattr(msgs[-1], 'date', None)
        span = (newest - oldest).total_seconds() if newest and oldest else 0

        rows.append(
            {
                'name': a.name,
                'id': a.id,
                'alerts': len(alerts),
                'total': len(msgs),
                'steps': steps,
                'newest': newest,
                'span_min': span / 60,
                'ratio': len(alerts) / max(steps, 1),
            }
        )

    rows.sort(key=lambda r: -r['alerts'])
    print()
    print(f'{"alerts":>7}/{"calls":<6} {"ratio":>5} {"span_min":>9}  agent')
    print('-' * 100)
    for r in rows:
        if not r['alerts']:
            continue
        flag = '  <<< COMPACTION LOOP' if r['ratio'] > 0.7 and r['alerts'] >= 5 else ''
        print(
            f'{r["alerts"]:>7}/{r["steps"]:<6} {r["ratio"]:>5.2f} {r["span_min"]:>9.1f}  '
            f'{r["name"]:34s} {r["id"]}{flag}'
        )
        print(f'{"":32s}last activity: {r["newest"]}')


if __name__ == '__main__':
    main()
