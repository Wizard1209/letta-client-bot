"""Strip the retired file feature off live agents.

Uploads went into folders, and every route behind `client.folders` now answers
400 "This API route is deprecated and no longer supported on the Letta API".
The agents that used it are still carrying the leftovers: the file tools that
came with a folder attachment, and the `file_handling` memory block telling
them how to answer uploads. Both are now instructions for something the agent
cannot do, and the block costs context on every single turn.

Detaches, never deletes: the tools stay in the tool library and the block keeps
its own id, so any of this can be put back by attaching it again.

Usage:
    uv run python -m devscripts.detach_file_feature            # dry-run
    uv run python -m devscripts.detach_file_feature --execute
"""

import argparse

from devscripts.bootstrap import letta, print_config

FILE_TOOLS = frozenset({'open_files', 'grep_files', 'semantic_search_files'})
FILE_BLOCK_LABEL = 'file_handling'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='actually detach')
    args = parser.parse_args()

    print_config(mode='EXECUTE' if args.execute else 'dry-run')

    tools_detached = blocks_detached = failures = 0

    for agent in letta.agents.list(limit=200):
        full = letta.agents.retrieve(agent.id, include=['agent.tools'])
        tools = [t for t in (full.tools or []) if t.name in FILE_TOOLS]
        blocks = [
            b
            for b in letta.agents.blocks.list(agent_id=agent.id)
            if b.label == FILE_BLOCK_LABEL
        ]
        if not tools and not blocks:
            continue

        print(f'{agent.name} ({agent.id})')

        for tool in tools:
            print(f'  tool  {tool.name}')
            if not args.execute:
                continue
            try:
                letta.agents.tools.detach(tool.id, agent_id=agent.id)
                tools_detached += 1
            except Exception as e:  # noqa: BLE001 - report and keep going
                print(f'    FAILED: {e}')
                failures += 1

        for block in blocks:
            print(f'  block {block.label}')
            if not args.execute:
                continue
            try:
                letta.agents.blocks.detach(block.id, agent_id=agent.id)
                blocks_detached += 1
            except Exception as e:  # noqa: BLE001 - report and keep going
                print(f'    FAILED: {e}')
                failures += 1

    print()
    if args.execute:
        print(f'detached {tools_detached} tools, {blocks_detached} blocks, {failures} failed')
    else:
        print('dry-run: nothing changed, pass --execute to apply')


if __name__ == '__main__':
    main()
