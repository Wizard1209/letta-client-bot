"""Report context-window headroom per agent — detects compaction-loop risk.

An agent loops on summarization when its *static* footprint (system prompt +
memory blocks + tool schemas) plus the reserved output budget (`max_tokens`)
leaves too little room for tool results: every tool call overflows the window,
Letta compacts, the agent loses the data it just fetched and re-fetches it.

    headroom = context_window - static_current - max_tokens

Usage:
    uv run python -m devscripts._ctx_headroom
"""

from devscripts.bootstrap import letta, print_config


def main() -> None:
    print_config()

    rows = []
    for a in letta.agents.list(limit=200):
        lc = a.llm_config
        ctx = getattr(lc, 'context_window', 0) or 0
        max_tok = getattr(lc, 'max_tokens', 0) or 0
        try:
            c = letta.get(f'/v1/agents/{a.id}/context', cast_to=object)
        except Exception as e:  # noqa: BLE001
            print(f'  !! {a.name}: {type(e).__name__}')
            continue
        current = c.get('context_window_size_current', 0)
        nmsg = c.get('num_messages', 0)
        static = current  # includes whatever messages remain
        headroom = ctx - static - max_tok
        rows.append(
            {
                'name': a.name,
                'id': a.id,
                'model': str(getattr(lc, 'model', '?')),
                'ctx': ctx,
                'max_tok': max_tok,
                'current': current,
                'nmsg': nmsg,
                'headroom': headroom,
            }
        )

    rows.sort(key=lambda r: r['headroom'])
    print()
    hdr = (
        f'{"headroom":>9} {"ctx":>7} {"used":>7} {"out":>6} {"msgs":>5}  '
        f'{"model":22s} agent'
    )
    print(hdr)
    print('-' * 118)
    for r in rows:
        if r['headroom'] < 0:
            flag = '  <<< LOOPS: no room at all'
        elif r['headroom'] < 15000:
            flag = '  <<< AT RISK'
        else:
            flag = ''
        print(
            f'{r["headroom"]:>9} {r["ctx"]:>7} {r["current"]:>7} {r["max_tok"]:>6} '
            f'{r["nmsg"]:>5}  {r["model"][:22]:22s} {r["name"]:32s} {r["id"]}{flag}'
        )


if __name__ == '__main__':
    main()
