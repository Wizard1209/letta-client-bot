"""Delete scheduled message tool for Letta agents.

NOTE: This file is excluded from linting/formatting and designed to be
loaded as a Letta custom tool via source_code registration.

This tool enables agents to delete/cancel scheduled messages using Letta's
native scheduling API.

Uses injected Letta context:
- `client`: Letta SDK client (injected by runtime as global)
- `LETTA_AGENT_ID`: Agent's own ID (available via os.getenv, injected by runtime)
"""

import os
from typing import Literal

from letta_client._models import BaseModel


class ScheduleDeleteResponse(BaseModel):
    """Response from schedule delete endpoint."""
    success: Literal[True]


def delete_scheduled_message(scheduled_message_id: str) -> str:
    """Delete a scheduled message by its ID.

    Use this to cancel a scheduled reminder or stop a recurring message.
    Get the schedule ID from list_scheduled_messages.

    For one-time messages: Prevents the message from being delivered.
    For recurring messages: Stops all future executions.

    Injected by Letta runtime:
    - client: Letta SDK client for API calls
    - LETTA_AGENT_ID: This agent's ID

    Args:
        scheduled_message_id (str): The ID of the scheduled message to delete
                                    (get this from list_scheduled_messages)

    Returns:
        str: Confirmation of deletion or error message
    """
    # Get agent ID from injected environment (provided by Letta runtime)
    agent_id = os.environ.get('LETTA_AGENT_ID')

    if not agent_id:
        return 'Error: LETTA_AGENT_ID not available in execution environment'

    if not scheduled_message_id or not scheduled_message_id.strip():
        return 'Error: scheduled_message_id is required. Use list_scheduled_messages to get IDs.'

    scheduled_message_id = scheduled_message_id.strip()

    try:
        # Try SDK method first, fall back to direct API call
        try:
            client.agents.schedule.delete(  # type: ignore[name-defined]
                agent_id=agent_id,
                scheduled_message_id=scheduled_message_id,
            )
        except AttributeError:
            client.delete(  # type: ignore[name-defined]
                f'/v1/agents/{agent_id}/schedule/{scheduled_message_id}',
                cast_to=ScheduleDeleteResponse,
            )

        return f'Successfully deleted scheduled message: {scheduled_message_id}'

    except NameError:
        return 'Error: Letta client not available in execution environment'
    except Exception as e:
        error_str = str(e)
        if '404' in error_str or 'not found' in error_str.lower():
            return f'Error: Scheduled message not found: {scheduled_message_id}. It may have already been deleted or executed.'
        return f'Error deleting scheduled message: {error_str}'
