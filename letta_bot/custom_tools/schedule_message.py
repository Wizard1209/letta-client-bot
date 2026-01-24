"""Schedule delayed message tool for Letta agents.

NOTE: This file is excluded from linting/formatting and designed to be
loaded as a Letta custom tool via source_code registration.

This tool enables agents to schedule messages to themselves using Letta's
native scheduling API. Supports one-time (delay or timestamp) and recurring
(cron expression) schedules.

Uses injected Letta context:
- `client`: Letta SDK client (injected by runtime as global)
- `LETTA_AGENT_ID`: Agent's own ID (available via os.getenv, injected by runtime)
"""

from datetime import datetime, timedelta, timezone
import os

from letta_client._models import BaseModel


class ScheduleResponse(BaseModel):
    """Response from schedule create endpoint."""
    id: str
    next_scheduled_at: str | None = None


def schedule_message(
    message_to_self: str,
    delay_seconds: int = 0,
    schedule_at: str = '',
    cron_expression: str = '',
) -> str:
    """Schedule a delayed or recurring message to self for proactive behavior.

    This tool allows the agent to send a message to itself after a specified delay,
    at a specific time, or on a recurring schedule using cron expressions.

    You must provide EXACTLY ONE scheduling method:
    - delay_seconds: Relative delay from now (e.g., 3600 for 1 hour from now)
    - schedule_at: Absolute timestamp in ISO format with timezone (e.g., '2025-01-15T14:30:00-05:00')
    - cron_expression: 5-field cron for recurring schedules (e.g., '0 9 * * *' for daily at 9 AM)

    IMPORTANT: After scheduling, tell the user when they'll receive the notification.
    Only use schedule_at when you know the user's timezone (from conversation or memory).

    Cron expression format (5 fields):
        minute (0-59) | hour (0-23) | day of month (1-31) | month (1-12) | day of week (0-6, 0=Sunday)

    Injected by Letta runtime:
    - client: Letta SDK client for API calls
    - LETTA_AGENT_ID: This agent's ID (for self-messaging)

    Args:
        message_to_self (str): The message to send to yourself after the delay/at scheduled time
        delay_seconds (int): Delay in seconds before message delivery (default: 0)
        schedule_at (str): ISO format timestamp with timezone for absolute scheduling (default: '')
        cron_expression (str): 5-field cron expression for recurring schedules (default: '')

    Returns:
        str: Confirmation with schedule details and ID, or error message
    """
    # Get agent ID from injected environment (provided by Letta runtime)
    agent_id = os.environ.get('LETTA_AGENT_ID')

    if not agent_id:
        return 'Error: LETTA_AGENT_ID not available in execution environment'

    # Validate scheduling parameters - exactly one must be provided
    has_delay = delay_seconds > 0
    has_timestamp = schedule_at != ''
    has_cron = cron_expression != ''

    method_count = sum([has_delay, has_timestamp, has_cron])

    if method_count == 0:
        return 'Error: Must provide exactly one of: delay_seconds, schedule_at, or cron_expression'
    if method_count > 1:
        return 'Error: Cannot provide multiple scheduling methods - choose only one'

    # Calculate timing information
    now_utc = datetime.now(timezone.utc)
    scheduled_at_str = now_utc.strftime('%Y-%m-%d %H:%M UTC')

    # Build schedule configuration
    if has_cron:
        import re
        # Matches 5 whitespace-separated fields, each containing only: * digits , / -
        if not re.match(r'^([*\d,/-]+\s+){4}[*\d,/-]+$', cron_expression.strip()):
            return 'Error: invalid cron format. Expected 5 fields (minute hour day month weekday)'

        schedule_config = {
            'type': 'recurring',
            'cron_expression': cron_expression.strip(),
        }
        timing_description = f'Recurring: {cron_expression}'

    elif has_timestamp:
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

        # Convert to Unix milliseconds
        unix_ms = int(expected_arrival.timestamp() * 1000)

        schedule_config = {
            'type': 'one-time',
            'scheduled_at': unix_ms,
        }

        # Preserve user's timezone from schedule_at
        tz_label = expected_arrival.strftime('%Z') or expected_arrival.strftime('%z')
        expected_at_str = expected_arrival.strftime(f'%Y-%m-%d %H:%M {tz_label}')
        timing_description = f'Scheduled for: {expected_at_str}'

    else:
        # Delay-based scheduling
        if delay_seconds < 0:
            return 'Error: delay_seconds must be a positive integer'

        # Calculate target time
        unix_ms = int((now_utc.timestamp() + delay_seconds) * 1000)

        schedule_config = {
            'type': 'one-time',
            'scheduled_at': unix_ms,
        }

        # Format: "1 day, 2:03:04" or "5:30:00"
        timing_description = f'In {timedelta(seconds=delay_seconds)}'

    # Build messages payload
    messages_payload = [
        {
            'role': 'system',
            'content': message_to_self,
        }
    ]

    try:
        # Try SDK method first, fall back to direct API call
        try:
            response = client.agents.schedule.create(  # type: ignore[name-defined]
                agent_id=agent_id,
                schedule=schedule_config,
                messages=messages_payload,
            )
            schedule_id = response.id
        except AttributeError:
            # SDK doesn't have schedule method - use direct API call
            response = client.post(  # type: ignore[name-defined]
                f'/v1/agents/{agent_id}/schedule',
                body={'messages': messages_payload, 'schedule': schedule_config},
                cast_to=ScheduleResponse,
            )
            schedule_id = response.id

        return (
            f'Scheduled at: {scheduled_at_str}\n'
            f'{timing_description}\n'
            f'Schedule ID: {schedule_id}'
        )

    except NameError:
        return 'Error: Letta client not available in execution environment'
    except Exception as e:
        return f'Error scheduling message: {str(e)}'
