"""List users and their agents via identity tags.

Usage:
    uv run python -m devscripts.list_users
"""

from collections import defaultdict

from devscripts.bootstrap import letta, print_config


def main() -> None:
    """List users by identity-tg-* tags and their agents."""
    print_config()

    # Group agents by telegram_id from identity-tg-* tags
    users: dict[int, list] = defaultdict(list)

    print('Scanning agents...')

    for agent in letta.agents.list():
        # Fetch full agent with tags
        full_agent = letta.agents.retrieve(agent.id, include=['agent.tags'])
        if not full_agent.tags:
            continue
        for tag in full_agent.tags:
            if tag.startswith('identity-tg-'):
                try:
                    tg_id = int(tag[12:])
                    users[tg_id].append(full_agent)
                except ValueError:
                    continue

    if not users:
        print('No users found.')
        return

    print(f'Found {len(users)} users\n')
    print('=' * 60)

    for tg_id, agents in sorted(users.items()):
        # Separate owned vs shared access
        owned = [a for a in agents if a.tags and f'owner-tg-{tg_id}' in a.tags]
        shared = [a for a in agents if a not in owned]

        print(f'\nUser: tg-{tg_id}')
        print(f'  Total agents: {len(agents)}')

        if owned:
            print(f'  Owned ({len(owned)}):')
            for agent in owned:
                print(f'    • {agent.name}')
                print(f'      ID: {agent.id}')

        if shared:
            print(f'  Shared access ({len(shared)}):')
            for agent in shared:
                # Find owner
                owner_tg = None
                if agent.tags:
                    for tag in agent.tags:
                        if tag.startswith('owner-tg-'):
                            try:
                                owner_tg = int(tag[9:])
                            except ValueError:
                                pass
                            break
                owner_info = f' (owner: tg-{owner_tg})' if owner_tg else ''
                print(f'    • {agent.name}{owner_info}')
                print(f'      ID: {agent.id}')

    print('\n' + '=' * 60)


if __name__ == '__main__':
    main()
