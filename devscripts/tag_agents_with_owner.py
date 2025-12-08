"""Tag all agents with owner and creator tags based on identity identifier_key.

Usage:
    uv run python -m devscripts.tag_agents_with_owner
"""

import asyncio
import logging

from letta_client import APIError
from letta_client.types.identity import Identity

from letta_bot.client import client
from letta_bot.config import CONFIG

# Suppress HTTP request logs
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)


async def tag_agent(
    agent_id: str, agent_name: str, new_tags: list[str]
) -> tuple[str, bool, str | None]:
    """Tag a single agent."""
    try:
        await client.agents.update(agent_id=agent_id, tags=new_tags)
        return (agent_name, True, None)
    except (APIError, Exception) as e:
        return (agent_name, False, str(e))


async def process_identity(identity: Identity) -> int:
    """Process single identity and tag all its agents."""
    # Extract telegram_id from identifier_key (format: tg-<telegram_id>)
    identifier_key = identity.identifier_key
    if not identifier_key or not identifier_key.startswith('tg-'):
        print(
            f'⚠️  Skipped {identity.name}: identifier_key "{identifier_key}" '
            f'does not match expected format\n'
        )
        return 0

    telegram_id = identifier_key.removeprefix('tg-')
    owner_tag = f'owner-tg-{telegram_id}'
    creator_tag = f'creator-tg-{telegram_id}'

    print(f'Processing identity: {identity.name}')
    print(f'  Identifier: {identifier_key}')
    print(f'  Owner tag: {owner_tag}')
    print(f'  Creator tag: {creator_tag}')

    try:
        # Fetch agents for this identity
        agents_page = await client.identities.agents.list(identity_id=identity.id)
        agents = agents_page.items

        if not agents:
            print('  No agents found\n')
            return 0

        print(f'  Found {len(agents)} agent(s)')

        # Prepare tagging tasks
        tag_tasks = []

        for agent in agents:
            current_tags = agent.tags if agent.tags else []
            has_owner = owner_tag in current_tags
            has_creator = creator_tag in current_tags

            # Skip if already has both tags
            if has_owner and has_creator:
                print(f'    ✓ {agent.name}: already has both tags')
                continue

            # Add missing tags
            new_tags = list(current_tags)
            tags_to_add = []
            if not has_owner:
                new_tags.append(owner_tag)
                tags_to_add.append('owner')
            if not has_creator:
                new_tags.append(creator_tag)
                tags_to_add.append('creator')

            tag_tasks.append((agent.id, agent.name, new_tags, tags_to_add))

        if not tag_tasks:
            print()
            return 0

        # Tag all agents in parallel
        results = await asyncio.gather(
            *[tag_agent(aid, name, tags) for aid, name, tags, _ in tag_tasks]
        )

        # Print results
        tagged_count = 0
        for (_, agent_name, _, tags_added), (_, success, error) in zip(
            tag_tasks, results, strict=True
        ):
            if success:
                print(f'    ✅ {agent_name}: added {", ".join(tags_added)} tag(s)')
                tagged_count += 1
            else:
                print(f'    ❌ {agent_name}: failed to tag - {error}')

        print()
        return tagged_count

    except APIError as e:
        print(f'  ❌ Failed to fetch agents: {e}\n')
        return 0


async def main() -> None:
    """Tag all agents with owner and creator tags."""
    try:
        # Fetch all identities
        page = await client.identities.list(project_id=CONFIG.letta_project_id)
        identities = page.items

        if not identities:
            print('\nNo identities found.')
            return

        print(f'\nProcessing {len(identities)} identities...\n')

        # Process each identity sequentially to preserve readable output
        total_tagged = 0
        for identity in identities:
            tagged = await process_identity(identity)
            total_tagged += tagged

        print('=' * 80)
        print(f'Done. Tagged {total_tagged} agent(s) total.')

    except APIError as e:
        print(f'\n❌ API Error: {e}')
        raise
    except Exception as e:
        print(f'\n❌ Error: {e}')
        raise


if __name__ == '__main__':
    asyncio.run(main())
