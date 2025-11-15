#!/usr/bin/env python3
"""Send system message to agent for scheduled notification.

This script uses direct HTTP requests to the Letta API to send a system role message
that instructs the agent to send a scheduled notification via Telegram.

NOTE: This version uses the requests library for compatibility with custom tool
execution environments where the Letta SDK may not be available.
"""

import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
AGENT_ID = 'agent-df6ebdef-fede-43fe-9b37-4108b4539709'
LETTA_API_KEY = os.getenv('LETTA_API_KEY')
LETTA_BASE_URL = os.getenv('LETTA_BASE_URL', 'https://api.letta.com')

if not LETTA_API_KEY:
    raise ValueError('LETTA_API_KEY environment variable is required')


def send_system_notification(
    agent_id: str,
    notification_message: str,
    scheduled_time: str | None = None,
    api_key: str | None = None,
    base_url: str = 'https://api.letta.com',
) -> dict:
    """Send system message to agent to trigger scheduled notification.

    Args:
        agent_id: The Letta agent ID to send the message to
        notification_message: The message content the agent should send via telegram
        scheduled_time: Optional time description for when this was scheduled
        api_key: Letta API key (defaults to LETTA_API_KEY env var)
        base_url: Letta API base URL (defaults to https://api.letta.com)

    Returns:
        dict: Response from the Letta API containing Run object

    Raises:
        ValueError: If API key is not provided
        requests.exceptions.RequestException: If the HTTP request fails
    """
    import requests

    # Use provided API key or fall back to environment variable
    token = api_key or os.environ.get('LETTA_API_KEY')
    if not token:
        raise ValueError('LETTA_API_KEY must be provided or set in environment')

    # Construct the system message
    if scheduled_time:
        system_text = (
            f'SYSTEM: This is a scheduled notification reminder. '
            f'The user scheduled this message for {scheduled_time}. '
            f'Please use the notify_via_telegram tool to send the following message to the user:\n\n'
            f'{notification_message}'
        )
    else:
        system_text = (
            f'SYSTEM: This is a scheduled notification reminder. '
            f'Please use the notify_via_telegram tool to send the following message to the user:\n\n'
            f'{notification_message}'
        )

    # Construct API request
    url = f'{base_url}/v1/agents/{agent_id}/messages/async'
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }
    payload = {
        'messages': [
            {
                'role': 'system',
                'content': [{'type': 'text', 'text': system_text}]
            }
        ]
    }

    print(f'Sending system message to agent {agent_id}...')
    print(f'API URL: {url}')
    print(f'Message: {system_text}\n')

    try:
        # Send HTTP POST request to Letta API
        response = requests.post(url, json=payload, headers=headers, timeout=30)

        # Check response status
        if response.status_code == 200:
            result = response.json()
            print('Response received:')
            print(f'Status: Success (HTTP {response.status_code})')
            print(f'Response: {result}')
            return result
        else:
            error_msg = f'HTTP {response.status_code}: {response.text}'
            print(f'Error: {error_msg}')
            raise requests.exceptions.HTTPError(error_msg, response=response)

    except requests.exceptions.RequestException as e:
        print(f'Error sending message: {e}')
        raise


def main() -> None:
    """Main entry point for the script."""
    # Example scheduled notification
    notification_message = (
        'Hello! This is your scheduled reminder: '
        'Time to check your daily tasks and plan your day.'
    )
    scheduled_time = 'today at 9:00 AM'

    # TODO: Customize these values as needed
    print('='*60)
    print('Scheduled Notification Test Script (HTTP version)')
    print('='*60)
    print(f'Agent ID: {AGENT_ID}')
    print(f'Scheduled Time: {scheduled_time}')
    print(f'Notification: {notification_message}')
    print(f'Base URL: {LETTA_BASE_URL}')
    print('='*60 + '\n')

    send_system_notification(
        agent_id=AGENT_ID,
        notification_message=notification_message,
        scheduled_time=scheduled_time,
        api_key=LETTA_API_KEY,
        base_url=LETTA_BASE_URL,
    )

    print('\n' + '='*60)
    print('Script completed successfully')
    print('='*60)


if __name__ == '__main__':
    main()
