"""Migrate from Letta Identity API to tag-based access control.

This script:
1. Converts agent.identities to identity-tg-* tags
2. Ensures owner-tg-* tag exists (uses creator-tg or first identity)
3. Reports inconsistencies for manual review

Run BEFORE applying EdgeDB migration that drops identity_id.

Usage:
    uv run python -m devscripts.migrate_identities_to_tags
    uv run python -m devscripts.migrate_identities_to_tags --dry-run
"""

import argparse
from dataclasses import dataclass, field

from letta_client import APIError

from devscripts.bootstrap import letta, print_config


@dataclass
class AgentMigration:
    agent_id: str
    agent_name: str
    identity_tags_added: list[str] = field(default_factory=list)
    owner_tag_added: str | None = None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def modified(self) -> bool:
        return bool(self.identity_tags_added or self.owner_tag_added)


def extract_telegram_id(identifier_key: str) -> int | None:
    """Extract telegram ID from identifier_key (format: tg-{telegram_id})."""
    if identifier_key and identifier_key.startswith('tg-'):
        try:
            return int(identifier_key[3:])
        except ValueError:
            pass
    return None


def parse_tag_telegram_id(tag: str, prefix: str) -> int | None:
    """Extract telegram ID from tag (format: {prefix}{telegram_id})."""
    if tag.startswith(prefix):
        try:
            return int(tag[len(prefix):])
        except ValueError:
            pass
    return None


def migrate_agent(agent_id: str, dry_run: bool) -> AgentMigration:
    """Migrate a single agent from identities to tags."""
    try:
        agent = letta.agents.retrieve(
            agent_id=agent_id,
            include=['agent.identities', 'agent.tags'],
        )
    except APIError as e:
        return AgentMigration(
            agent_id=agent_id,
            agent_name='<unknown>',
            error=f'Failed to retrieve: {e}',
        )

    result = AgentMigration(
        agent_id=agent_id,
        agent_name=agent.name or '<unnamed>',
    )

    existing_tags = set(agent.tags) if agent.tags else set()
    identities = agent.identities or []

    # Extract telegram IDs from Letta identities
    identity_tg_ids: list[int] = []
    for identity in identities:
        if hasattr(identity, 'identifier_key') and identity.identifier_key:
            tg_id = extract_telegram_id(identity.identifier_key)
            if tg_id:
                identity_tg_ids.append(tg_id)

    # Parse existing tags
    existing_identity_tg_ids = {
        tg_id
        for tag in existing_tags
        if (tg_id := parse_tag_telegram_id(tag, 'identity-tg-'))
    }
    existing_owner_tg_ids = [
        tg_id
        for tag in existing_tags
        if (tg_id := parse_tag_telegram_id(tag, 'owner-tg-'))
    ]
    existing_creator_tg_ids = [
        tg_id
        for tag in existing_tags
        if (tg_id := parse_tag_telegram_id(tag, 'creator-tg-'))
    ]

    # Skip agents without identities
    if not identity_tg_ids:
        return result

    # Build new tags
    new_tags = list(existing_tags)

    # 1. Add identity-tg-* tags for all identities
    for tg_id in identity_tg_ids:
        if tg_id not in existing_identity_tg_ids:
            tag = f'identity-tg-{tg_id}'
            new_tags.append(tag)
            result.identity_tags_added.append(tag)

    # 2. Ensure owner-tg-* tag exists
    if not existing_owner_tg_ids:
        # Determine owner from: creator tag → first identity
        if existing_creator_tg_ids:
            owner_tg_id = existing_creator_tg_ids[0]
            result.warnings.append(
                f'No owner tag, using creator-tg-{owner_tg_id} as owner'
            )
        else:
            owner_tg_id = identity_tg_ids[0]
            if len(identity_tg_ids) > 1:
                result.warnings.append(
                    f'No owner/creator tag on shared agent, '
                    f'assigned tg-{owner_tg_id} (first identity)'
                )

        owner_tag = f'owner-tg-{owner_tg_id}'
        new_tags.append(owner_tag)
        result.owner_tag_added = owner_tag

    elif len(existing_owner_tg_ids) > 1:
        result.warnings.append(f'Multiple owner tags: {existing_owner_tg_ids}')

    # 3. Validate owner is in identities
    for owner_id in existing_owner_tg_ids:
        if owner_id not in identity_tg_ids:
            result.warnings.append(
                f'Owner tg-{owner_id} not attached to agent via identity'
            )

    # Skip if no changes needed
    if not result.modified:
        return result

    if dry_run:
        return result

    # Apply changes
    try:
        letta.agents.update(agent_id=agent_id, tags=new_tags)
    except APIError as e:
        result.error = f'Failed to update: {e}'
        result.identity_tags_added = []
        result.owner_tag_added = None

    return result


def main(dry_run: bool = False) -> None:
    """Migrate all agents from Letta Identity API to tag-based system."""
    print_config()
    mode = '[DRY RUN] ' if dry_run else ''
    print(f'{mode}Migrating agents from Letta Identity API to tags...\n')

    results: list[AgentMigration] = []

    for agent in letta.agents.list():
        result = migrate_agent(agent.id, dry_run)
        results.append(result)

        if result.error:
            print(f'  ❌ {result.agent_name}: {result.error}')
        elif result.modified:
            parts = []
            if result.identity_tags_added:
                parts.append(f'{len(result.identity_tags_added)} identity tag(s)')
            if result.owner_tag_added:
                parts.append('owner tag')
            print(f'  ✅ {result.agent_name}: added {", ".join(parts)}')
            for warning in result.warnings:
                print(f'     ⚠️  {warning}')
        elif result.warnings:
            print(f'  ⚠️  {result.agent_name}:')
            for warning in result.warnings:
                print(f'     {warning}')

    # Summary
    migrated = [r for r in results if r.modified]
    with_warnings = [r for r in results if r.warnings]
    with_errors = [r for r in results if r.error]
    total_identity_tags = sum(len(r.identity_tags_added) for r in results)
    total_owner_tags = sum(1 for r in results if r.owner_tag_added)

    print(f'\n{mode}Migration summary:')
    print(f'  Total agents: {len(results)}')
    print(f'  Migrated: {len(migrated)}')
    print(f'  Identity tags added: {total_identity_tags}')
    print(f'  Owner tags added: {total_owner_tags}')
    if with_warnings:
        print(f'  Warnings: {len(with_warnings)}')
    if with_errors:
        print(f'  Errors: {len(with_errors)}')

    if not dry_run and migrated:
        print('\n✅ Migration complete. You can now apply the EdgeDB migration.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Migrate from Letta Identity API to tag-based access control'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without applying them',
    )
    args = parser.parse_args()
    main(dry_run=args.dry_run)
