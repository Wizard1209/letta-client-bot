"""Test Letta native scheduling API.

This script tests:
1. Schedule creation (one-time with delay)
2. Listing schedules
3. Deleting schedules

Usage:
    uv run python -m devscripts.test_native_scheduling --agent-id <agent-id>
    uv run python -m devscripts.test_native_scheduling  # Uses .agent_id file or LETTA_AGENT_ID env
"""

import argparse
import time

from devscripts.bootstrap import letta, print_config, resolve_agent_id


def test_schedule_api(agent_id: str) -> None:
    """Test the native scheduling API."""
    print(f'Testing scheduling API for agent: {agent_id}')
    print('=' * 60)

    # Step 1: Check if schedule API exists
    print('\n[1/5] Checking if schedule API is available...')
    try:
        if not hasattr(letta.agents, 'schedule'):
            print('ERROR: client.agents.schedule not available in SDK')
            print('The SDK may need to be updated to support native scheduling.')
            print('Checking SDK version...')
            try:
                from letta_client import __version__

                print(f'SDK version: {__version__}')
            except ImportError:
                print('Could not determine SDK version')
            return
        print('OK: client.agents.schedule is available')
    except Exception as e:
        print(f'ERROR checking schedule API: {e}')
        return

    # Step 2: List existing schedules
    print('\n[2/5] Listing existing schedules...')
    try:
        existing = letta.agents.schedule.list(agent_id=agent_id)
        if hasattr(existing, 'scheduled_messages'):
            schedules = existing.scheduled_messages
        elif hasattr(existing, 'items'):
            schedules = existing.items
        else:
            schedules = existing if isinstance(existing, list) else []

        print(f'Found {len(schedules)} existing schedule(s)')
        for s in schedules:
            print(f'  - {s.id}: {getattr(s, "schedule", {}).get("type", "unknown")}')
    except Exception as e:
        print(f'ERROR listing schedules: {e}')
        return

    # Step 3: Create a test schedule (1 hour from now)
    print('\n[3/5] Creating test schedule (1 hour from now)...')
    scheduled_time_ms = int((time.time() + 3600) * 1000)
    try:
        result = letta.agents.schedule.create(
            agent_id=agent_id,
            schedule={'type': 'one-time', 'scheduled_at': scheduled_time_ms},
            messages=[{'role': 'user', 'content': 'Test message from devscript'}],
        )
        schedule_id = result.id
        print(f'OK: Created schedule with ID: {schedule_id}')
    except Exception as e:
        print(f'ERROR creating schedule: {e}')
        return

    # Step 4: Verify schedule appears in list
    print('\n[4/5] Verifying schedule in list...')
    try:
        updated = letta.agents.schedule.list(agent_id=agent_id)
        if hasattr(updated, 'scheduled_messages'):
            schedules = updated.scheduled_messages
        elif hasattr(updated, 'items'):
            schedules = updated.items
        else:
            schedules = updated if isinstance(updated, list) else []

        found = any(getattr(s, 'id', None) == schedule_id for s in schedules)
        if found:
            print(f'OK: Schedule {schedule_id} found in list')
        else:
            print(f'WARNING: Schedule {schedule_id} not found in list')
    except Exception as e:
        print(f'ERROR verifying schedule: {e}')

    # Step 5: Delete the test schedule
    print('\n[5/5] Deleting test schedule...')
    try:
        letta.agents.schedule.delete(
            agent_id=agent_id, scheduled_message_id=schedule_id
        )
        print(f'OK: Deleted schedule {schedule_id}')
    except Exception as e:
        print(f'ERROR deleting schedule: {e}')

    print('\n' + '=' * 60)
    print('Test complete!')


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Test Letta native scheduling API')
    parser.add_argument(
        '-a',
        '--agent-id',
        help='Agent ID to test with',
    )

    args = parser.parse_args()

    agent_id = resolve_agent_id(args.agent_id)
    if not agent_id:
        print('Error: Agent ID required. Provide via --agent-id, LETTA_AGENT_ID env, or .agent_id file')
        return

    print_config(agent_id=agent_id)
    test_schedule_api(agent_id)


if __name__ == '__main__':
    main()
