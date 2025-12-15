"""Move agent(s) to another project.

Usage:
    uv run python -m devscripts.move_agent --project-id <target-project-id> agent-uuid1 agent-uuid2
    uv run python -m devscripts.move_agent -p <target-project-id> agent-uuid1
"""

import argparse

from letta_client import APIError

from devscripts.bootstrap import letta


def move_agent(agent_id: str, target_project_id: str) -> tuple[str, bool, str | None]:
    """Move a single agent to target project and return result."""
    try:
        updated = letta.agents.update(agent_id=agent_id, project_id=target_project_id)
        return (agent_id, True, updated.name)
    except APIError as e:
        return (agent_id, False, str(e))


def main(agent_ids: list[str], target_project_id: str) -> None:
    """Move specified agents to target project."""
    if not agent_ids:
        print('\nNo agent IDs provided.')
        return

    print(f'\nMoving {len(agent_ids)} agent(s) to project {target_project_id}...\n')

    for agent_id in agent_ids:
        agent_id, success, info = move_agent(agent_id, target_project_id)
        if success:
            print(f'  ✓ Moved: {agent_id} ({info})')
        else:
            print(f'  ✗ Failed: {agent_id} - {info}')

    print('\nDone.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Move Letta agents to another project')
    parser.add_argument(
        '-p',
        '--project-id',
        required=True,
        help='Target project ID to move agents to',
    )
    parser.add_argument(
        'agent_ids',
        nargs='+',
        help='One or more agent IDs to move (space-separated)',
    )
    args = parser.parse_args()
    main(args.agent_ids, args.project_id)
