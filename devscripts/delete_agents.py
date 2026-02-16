"""Delete agents by ID.

Usage:
    uv run python -m devscripts.delete_agents agent-uuid1 agent-uuid2 agent-uuid3
"""

import argparse

from letta_client import APIError

from devscripts.bootstrap import letta, print_config


def delete_agent(agent_id: str) -> tuple[str, bool, str | None]:
    """Delete a single agent and return result."""
    try:
        letta.agents.delete(agent_id=agent_id)
        return (agent_id, True, None)
    except APIError as e:
        return (agent_id, False, str(e))


def main(agent_ids: list[str]) -> None:
    """Delete specified agents."""
    print_config()
    if not agent_ids:
        print('\nNo agent IDs provided.')
        return

    print(f'\nDeleting {len(agent_ids)} agent(s)...\n')

    for agent_id in agent_ids:
        agent_id, success, error = delete_agent(agent_id)
        if success:
            print(f'  Deleted: {agent_id}')
        else:
            print(f'  Failed: {agent_id} - {error}')

    print('\nDone.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Delete Letta agents by ID')
    parser.add_argument(
        'agent_ids',
        nargs='+',
        help='One or more agent IDs to delete (space-separated)',
    )
    args = parser.parse_args()
    main(args.agent_ids)
