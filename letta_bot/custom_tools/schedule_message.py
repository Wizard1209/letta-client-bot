"""Schedule delayed message tool for Letta agents.

NOTE: This file is excluded from linting/formatting and designed to be
loaded as a Letta custom tool via source_code registration.

This tool enables agents to schedule messages to themselves for delayed execution
using Scheduler's delay/queue service (https://scheduler.io).
"""

from datetime import datetime, timedelta, timezone
import os


def schedule_message(message_to_self: str, delay_seconds: int = 0, schedule_at: str = '') -> str:
    """Schedule a delayed message to self for proactive behavior.

    This tool allows the agent to send a message to itself after a specified delay
    or at a specific time, enabling proactive reminders, scheduled tasks, and delayed actions.

    You must provide EITHER delay_seconds OR schedule_at (not both):
    - delay_seconds: Relative delay from now (e.g., 3600 for 1 hour from now)
    - schedule_at: Absolute timestamp in ISO format with timezone (e.g., '2025-01-15T14:30:00-05:00')

    IMPORTANT: After scheduling, tell the user when they'll receive the notification.
    Only use schedule_at when you know the user's timezone (from conversation or memory).

    Environment variables required:
    - LETTA_API_KEY: Letta API authentication token
    - SCHEDULER_URL: Scheduler service base URL
    - SCHEDULER_API_KEY: Scheduler service API token
    - AGENT_ID: The agent's ID (for self-messaging)
    - LETTA_BASE_URL: Letta API base URL (optional, defaults to https://api.letta.com)

    Args:
        message_to_self (str): The system message to send to yourself after the delay
        delay_seconds (int): Delay in seconds before message delivery (default: 0, use schedule_at instead)
        schedule_at (str): ISO format timestamp with timezone for absolute scheduling (default: '', use delay_seconds instead)

    Returns:
        str: Confirmation that the scheduled message was queued or error message
    """
    import requests

    # Get required environment variables
    letta_api_key = os.environ.get('LETTA_API_KEY')
    scheduler_url = os.environ.get('SCHEDULER_URL')
    scheduler_api_key = os.environ.get('SCHEDULER_API_KEY')
    agent_id = os.environ.get('AGENT_ID')
    base_url = os.environ.get('LETTA_BASE_URL', 'https://api.letta.com')

    # Validate environment variables
    if not letta_api_key:
        return 'Error: LETTA_API_KEY environment variable is not set'
    if not scheduler_url:
        return 'Error: SCHEDULER_URL environment variable is not set'
    if not scheduler_api_key:
        return 'Error: SCHEDULER_API_KEY environment variable is not set'
    if not agent_id:
        return 'Error: AGENT_ID environment variable is not set'

    # Validate scheduling parameters - exactly one must be provided
    has_delay = delay_seconds > 0
    has_timestamp = schedule_at != ''

    if not has_delay and not has_timestamp:
        return 'Error: Must provide either delay_seconds or schedule_at'
    if has_delay and has_timestamp:
        return 'Error: Cannot provide both delay_seconds and schedule_at - choose one'

    # Calculate timing information
    now_utc = datetime.now(timezone.utc)

    if has_timestamp:
        # Parse ISO timestamp and validate
        try:
            expected_arrival = datetime.fromisoformat(schedule_at)
        except (ValueError, TypeError) as e:
            return f'Error: Invalid ISO timestamp format for schedule_at: {str(e)}'

        # Ensure timestamp is timezone-aware
        if expected_arrival.tzinfo is None:
            return 'Error: schedule_at must include timezone (e.g., +00:00 or Z)'

        # Check if timestamp is in the future
        if expected_arrival <= now_utc:
            return f'Error: schedule_at must be in the future (got {schedule_at}, now is {now_utc.isoformat()})'
    else:
        # Validate delay
        if delay_seconds < 0:
            return 'Error: delay_seconds must be a positive integer'
        expected_arrival = now_utc + timedelta(seconds=delay_seconds)

    # Format in simple readable format: "2025-01-15 14:30 UTC"
    scheduled_at_str = now_utc.strftime('%Y-%m-%d %H:%M UTC')

    if has_timestamp:
        # Preserve user's timezone from schedule_at
        tz_label = expected_arrival.strftime('%Z') or expected_arrival.strftime('%z')
        expected_at_str = expected_arrival.strftime(f'%Y-%m-%d %H:%M {tz_label}')
    else:
        # No timezone context from delay_seconds, use UTC
        expected_at_str = expected_arrival.strftime('%Y-%m-%d %H:%M UTC')

    # Build system message for self with timing info
    system_text = (
        f'Scheduled at: {scheduled_at_str}\n'
        f'Expected at: {expected_at_str}\n'
        f'Message: {message_to_self}'
    )

    # Construct Letta API endpoint (without executing it directly)
    letta_endpoint = f'{base_url}/v1/agents/{agent_id}/messages/async'

    # Build Letta API request payload
    letta_payload = {
        'messages': [
            {
                'role': 'system',
                'content': [{'type': 'text', 'text': system_text}]
            }
        ]
    }

    # Construct Scheduler URL (prefix letta endpoint with scheduler.to/)
    # Scheduler will forward the request after the specified delay
    scheduler_url = f'https://{scheduler_url}/{letta_endpoint}'

    # Prepare headers
    headers = {
        # Scheduler authentication
        'X-API-Key': scheduler_api_key,
        # Letta API authentication (forwarded by Scheduler)
        'Authorization': f'Bearer {letta_api_key}',
        'Content-Type': 'application/json',
    }

    # Add scheduling header based on mode
    if has_timestamp:
        # Use absolute timestamp scheduling
        headers['X-Schedule-At'] = expected_arrival.isoformat()
    else:
        # Use relative delay scheduling
        headers['X-Delay-Seconds'] = str(delay_seconds)

    try:
        # Send request to Scheduler, which will queue and forward to Letta
        response = requests.post(scheduler_url, json=letta_payload, headers=headers, timeout=10)

        if response.status_code == 200:
            return f'Scheduled at: {scheduled_at_str}\nExpected at: {expected_at_str}'
        elif response.status_code == 201:
            # Scheduler returns 201 when job is created
            return f'Scheduled at: {scheduled_at_str}\nExpected at: {expected_at_str}'
        else:
            return f'Failed to schedule message: {response.status_code} - {response.text}'

    except requests.exceptions.RequestException as e:
        return f'Error scheduling message: {str(e)}'
