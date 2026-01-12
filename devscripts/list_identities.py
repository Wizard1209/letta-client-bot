"""List all identities from Letta API with detailed information.

Usage:
    uv run python -m devscripts.list_identities
"""

from devscripts.bootstrap import letta


def main() -> None:
    """List all identities with their agents."""
    identities = list(letta.identities.list())

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
                print(f'     - {prop.key}: {prop.value} ({prop.type})')

        # Fetch and show agents
        agents_page = letta.identities.agents.list(identity_id=identity.id)
        agents = agents_page.items

        if agents:
            print(f'   Agents ({len(agents)}):')
            for agent in agents:
                full_agent = letta.agents.retrieve(
                    agent_id=agent.id,
                    include=['agent.tags', 'agent.blocks', 'agent.tools'],
                )

                print(f'     - {full_agent.name}')
                print(f'       ID: {full_agent.id}')

                if hasattr(full_agent, 'description') and full_agent.description:
                    desc = full_agent.description
                    if len(desc) > 80:
                        desc = desc[:77] + '...'
                    print(f'       Description: {desc}')

                if hasattr(full_agent, 'model') and full_agent.model:
                    print(f'       Model: {full_agent.model}')

                if hasattr(full_agent, 'tags') and full_agent.tags:
                    print(f'       Tags: {", ".join(full_agent.tags)}')

                if hasattr(full_agent, 'blocks') and full_agent.blocks:
                    print(f'       Memory Blocks: {len(full_agent.blocks)}')

                if hasattr(full_agent, 'tools') and full_agent.tools:
                    print(f'       Tools: {len(full_agent.tools)}')
        else:
            print('   Agents: None')

        print()

    print('=' * 80)


if __name__ == '__main__':
    main()
