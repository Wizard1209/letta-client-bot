#!/usr/bin/env python3
"""Stop (cancel/delete) all active/pending Scheduler scheduled requests."""

import os
import sys
import argparse
import requests
from dotenv import load_dotenv


def main():
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description='Stop (cancel/delete) all active/pending Scheduler scheduled requests')
    parser.add_argument('-y', '--yes', action='store_true', help='Auto-confirm without prompting')
    args = parser.parse_args()

    # Load environment variables
    load_dotenv()

    scheduler_api_key = os.getenv('SCHEDULER_API_KEY')
    if not scheduler_api_key:
        print('Error: SCHEDULER_API_KEY not found in .env file')
        sys.exit(1)

    base_url = 'https://app.scheduler.io'
    headers = {
        'X-Scheduler-Token': scheduler_api_key,
        'Content-Type': 'application/json'
    }

    print('Fetching all Scheduler schedules...')

    # List all schedules
    try:
        response = requests.get(f'{base_url}/schedules', headers=headers, timeout=10)
        response.raise_for_status()
        schedules_data = response.json()
    except requests.exceptions.RequestException as e:
        print(f'Error fetching schedules: {e}')
        sys.exit(1)

    # Filter for pending/active schedules only
    stoppable_schedules = []
    if isinstance(schedules_data, list):
        stoppable_schedules = [
            sched for sched in schedules_data
            if sched.get('status') in ['PENDING', 'ACTIVE']
        ]
    elif isinstance(schedules_data, dict) and 'schedules' in schedules_data:
        stoppable_schedules = [
            sched for sched in schedules_data['schedules']
            if sched.get('status') in ['PENDING', 'ACTIVE']
        ]

    if not stoppable_schedules:
        print('No active or pending schedules found to stop.')
        return

    print(f'\nFound {len(stoppable_schedules)} stoppable schedule(s):')
    for sched in stoppable_schedules:
        sched_id = sched.get('id', 'unknown')
        status = sched.get('status', 'unknown')
        url = sched.get('url', 'N/A')
        print(f'  - ID: {sched_id}, Status: {status}, URL: {url}')

    # Ask for confirmation (unless -y flag is set)
    if not args.yes:
        try:
            confirm = input('\nStop (cancel/delete) all these schedules? (y/n): ').strip().lower()
            if confirm != 'y':
                print('Cancelled.')
                return
        except (EOFError, KeyboardInterrupt):
            print('\nCancelled.')
            return
    else:
        print('\nAuto-confirming (--yes flag set)...')

    # Stop each schedule
    print('\nStopping schedules...')
    stopped_count = 0
    failed_count = 0

    for sched in stoppable_schedules:
        sched_id = sched.get('id')
        if not sched_id:
            continue

        try:
            stop_response = requests.delete(
                f'{base_url}/schedules/{sched_id}',
                headers=headers,
                timeout=10
            )
            stop_response.raise_for_status()
            print(f'✓ Stopped schedule {sched_id}')
            stopped_count += 1
        except requests.exceptions.RequestException as e:
            print(f'✗ Failed to stop schedule {sched_id}: {e}')
            failed_count += 1

    print(f'\nSummary: {stopped_count} stopped, {failed_count} failed')


if __name__ == '__main__':
    main()
