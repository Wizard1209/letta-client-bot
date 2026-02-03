"""List scheduled messages tool for Letta agents.

NOTE: This file is excluded from linting/formatting and designed to be
loaded as a Letta custom tool via source_code registration.

This tool enables agents to view their scheduled messages using Letta's
native scheduling API.

Uses injected Letta context:
- `client`: Letta SDK client (injected by runtime as global)
- `LETTA_AGENT_ID`: Agent's own ID (available via os.getenv, injected by runtime)
"""

import os
from typing import Union

from letta_client._models import BaseModel


# Models matching letta_client.types.agents.schedule_list_response


class MessageContent(BaseModel):
    """Message content (text or structured)."""
    content: Union[list, str]  # str or list of content parts
    role: str


class MessageWrapper(BaseModel):
    """Wrapper containing messages list."""
    messages: list[MessageContent]


class OneTimeSchedule(BaseModel):
    """One-time schedule."""
    scheduled_at: float  # Unix ms
    type: str | None = None


class RecurringSchedule(BaseModel):
    """Recurring schedule."""
    cron_expression: str
    type: str


class ScheduledMessage(BaseModel):
    """Single scheduled message."""
    id: str
    agent_id: str
    message: MessageWrapper
    schedule: Union[OneTimeSchedule, RecurringSchedule]
    next_scheduled_time: str | None = None  # ISO string


class ScheduleListResponse(BaseModel):
    """Response from schedule list endpoint."""
    has_next_page: bool
    scheduled_messages: list[ScheduledMessage]


def list_scheduled_messages() -> str:
    """List all scheduled messages for this agent.

    Returns a formatted list of all active scheduled messages, including:
    - Schedule ID (for deletion/management)
    - Schedule type (one-time or recurring)
    - Next execution time or cron expression
    - Message preview

    Use this to check what reminders or recurring tasks are currently active.

    Injected by Letta runtime:
    - client: Letta SDK client for API calls
    - LETTA_AGENT_ID: This agent's ID

    Returns:
        str: Formatted list of scheduled messages, or message if none exist
    """
    # Get agent ID from injected environment (provided by Letta runtime)
    agent_id = os.environ.get('LETTA_AGENT_ID')

    if not agent_id:
        return 'Error: LETTA_AGENT_ID not available in execution environment'

    try:
        # Try SDK method first, fall back to direct API call
        try:
            response = client.agents.schedule.list(agent_id=agent_id)  # type: ignore[name-defined]
        except AttributeError:
            response = client.get(  # type: ignore[name-defined]
                f'/v1/agents/{agent_id}/schedule',
                cast_to=ScheduleListResponse,
            )

        if not response.scheduled_messages:
            return 'No scheduled messages. Use schedule_message to create one.'

        lines = [f'{len(response.scheduled_messages)} scheduled:\n']

        for msg in response.scheduled_messages:
            # Schedule type and timing
            sched = msg.schedule
            stype = sched.type or 'one-time'
            cron = getattr(sched, 'cron_expression', None)

            if stype == 'recurring' and cron:
                timing = cron
            elif msg.next_scheduled_time:
                # ISO '2026-01-23T14:35:45.849Z' -> '2026-01-23 14:35 UTC'
                timing = msg.next_scheduled_time.replace('T', ' ')[:16] + ' UTC'
            else:
                timing = '?'

            # Message content: msg.message.messages[0].content
            content = msg.message.messages[0].content if msg.message.messages else ''
            if isinstance(content, list):
                # Handle structured content (text parts)
                content = content[0].get('text', '') if content else ''
            preview = (content[:20] + '...') if len(content) > 20 else (content or '-')

            lines.append(f'• {msg.id} | {stype} | {timing} | "{preview}"')

        return '\n'.join(lines)

    except NameError:
        return 'Error: Letta client not available in execution environment'
    except Exception as e:
        return f'Error listing scheduled messages: {str(e)}'
