"""List all identities from Letta API with detailed information.

Usage:
    uv run python -m devscripts.list_identities
"""

import asyncio
import logging

from letta_client import APIError

from letta_bot.client import client
from letta_bot.config import CONFIG

# Suppress HTTP request logs
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)

LOGGER = logging.getLogger(__name__)


async def main() -> None:
    """List all identities with their agents."""
    try:
        # Fetch all identities
        page = await client.identities.list(project_id=CONFIG.letta_project_id)
        identities = page.items

        if not identities:
            print('\nNo identities found.')
            return

        print('\n' + '=' * 80)
        print(f'Found {len(identities)} identities')
        print('=' * 80 + '\n')

        for idx, identity in enumerate(identities, 1):
            print(f'{idx}. {identity.name}')
            print(f'   ID: {identity.id}')
            print(f'   Identifier Key: {identity.identifier_key}')
            print(f'   Type: {identity.identity_type}')
            print(f'   Project ID: {identity.project_id or "N/A"}')

            # Show properties if available
            if hasattr(identity, 'properties') and identity.properties:
                print('   Properties:')
                for prop in identity.properties:
                    print(f'     • {prop.key}: {prop.value} ({prop.type})')

            # Fetch and show agents
            try:
                agents_page = await client.identities.agents.list(identity_id=identity.id)
                agents = agents_page.items

                if agents:
                    print(f'   Agents ({len(agents)}):')
                    for agent in agents:
                        # Use client.agents.retrieve() to get full agent details
                        try:
                            full_agent = await client.agents.retrieve(
                                agent_id=agent.id,
                                include=['agent.tags', 'agent.blocks', 'agent.tools'],
                            )

                            print(f'     • {full_agent.name}')
                            print(f'       ID: {full_agent.id}')

                            # Description
                            if (
                                hasattr(full_agent, 'description')
                                and full_agent.description
                            ):
                                desc = full_agent.description
                                if len(desc) > 80:
                                    desc = desc[:77] + '...'
                                print(f'       Description: {desc}')

                            # Model configuration
                            if hasattr(full_agent, 'model') and full_agent.model:
                                print(f'       Model: {full_agent.model}')

                            # Tags
                            if hasattr(full_agent, 'tags') and full_agent.tags:
                                print(f'       Tags: {", ".join(full_agent.tags)}')

                            # Memory blocks count
                            if hasattr(full_agent, 'blocks') and full_agent.blocks:
                                print(f'       Memory Blocks: {len(full_agent.blocks)}')

                            # Tools count
                            if hasattr(full_agent, 'tools') and full_agent.tools:
                                print(f'       Tools: {len(full_agent.tools)}')

                            # Last run metrics
                            if (
                                hasattr(full_agent, 'last_run_completion')
                                and full_agent.last_run_completion
                            ):
                                last_run = full_agent.last_run_completion.isoformat()
                                print(f'       Last Run: {last_run}')
                                if (
                                    hasattr(full_agent, 'last_run_duration_ms')
                                    and full_agent.last_run_duration_ms
                                ):
                                    duration_sec = full_agent.last_run_duration_ms / 1000
                                    print(f'       Last Duration: {duration_sec:.2f}s')
                                if (
                                    hasattr(full_agent, 'last_stop_reason')
                                    and full_agent.last_stop_reason
                                ):
                                    stop_reason = full_agent.last_stop_reason
                                    print(f'       Last Stop Reason: {stop_reason}')

                            # Created timestamp
                            if hasattr(full_agent, 'created_at') and full_agent.created_at:
                                created = full_agent.created_at.isoformat()
                                print(f'       Created: {created}')

                            # Updated timestamp
                            if hasattr(full_agent, 'updated_at') and full_agent.updated_at:
                                updated = full_agent.updated_at.isoformat()
                                print(f'       Updated: {updated}')

                        except APIError as agent_err:
                            # Fallback to basic agent info if retrieve fails
                            print(f'     • {agent.name}')
                            print(f'       ID: {agent.id}')
                            print(f'       Error fetching full details: {agent_err}')

                else:
                    print('   Agents: None')
            except APIError as e:
                print(f'   Agents: Error fetching ({e})')

            print()  # Empty line between identities

        print('=' * 80)

    except APIError as e:
        print(f'\n❌ API Error: {e}')
        raise
    except Exception as e:
        print(f'\n❌ Error: {e}')
        raise


if __name__ == '__main__':
    asyncio.run(main())
