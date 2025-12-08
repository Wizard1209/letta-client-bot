"""Delete agents by ID.

Usage:
    uv run python -m devscripts.delete_agents agent-uuid1 agent-uuid2 agent-uuid3
"""

import argparse
import asyncio
import logging

from letta_client import APIError

from letta_bot.client import client

# Suppress HTTP request logs
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)


async def delete_agent(agent_id: str) -> tuple[str, bool, str | None]:
    """Delete a single agent and return result."""
    try:
        await client.agents.delete(agent_id=agent_id)
        return (agent_id, True, None)
    except (APIError, Exception) as e:
        return (agent_id, False, str(e))


async def main(agent_ids: list[str]) -> None:
    """Delete specified agents in parallel."""
    if not agent_ids:
        print('\nNo agent IDs provided.')
        return

    print(f'\nDeleting {len(agent_ids)} agent(s)...\n')

    results = await asyncio.gather(*[delete_agent(agent_id) for agent_id in agent_ids])

    for agent_id, success, error in results:
        if success:
            print(f'✅ Deleted: {agent_id}')
        else:
            print(f'❌ Failed: {agent_id} - {error}')

    print('\nDone.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Delete Letta agents by ID')
    parser.add_argument(
        'agent_ids',
        nargs='+',
        help='One or more agent IDs to delete (space-separated)',
    )
    args = parser.parse_args()
    asyncio.run(main(args.agent_ids))
