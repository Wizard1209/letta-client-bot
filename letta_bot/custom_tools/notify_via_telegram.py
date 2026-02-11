"""Telegram notification tool for Letta agents.

NOTE: This file is excluded from linting/formatting and designed to be
loaded as a Letta custom tool via source_code registration.

Uses injected Letta context:
- `client`: Pre-authenticated Letta SDK client (injected by runtime)
- `LETTA_AGENT_ID`: Agent's own ID (available via os.getenv)
"""

import os
import re
import time


def notify_via_telegram(
    message: str,
    owner_only: bool = False,
) -> str:
    """Send proactive notification to Telegram user(s).

    CRITICAL: This tool is ONLY for proactive behavior - reactions to triggers OTHER than
    user messages (scheduled events, system events, time-based triggers, etc.).

    Regular conversation responses to user messages go through the normal chat flow.
    The user will ONLY see messages you explicitly send via this tool - they do NOT see
    scheduled messages arriving, nor your internal processing of those messages.

    This tool sends a notification message to Telegram users attached to this agent.
    By default, it sends to ALL users (identities) attached to the agent.
    Set owner_only=True to send only to the agent owner.

    Environment variable TELEGRAM_BOT_TOKEN must be set in the agent's tool
    execution environment.

    Injected by Letta runtime:
    - `client`: Authenticated Letta SDK client
    - `LETTA_AGENT_ID`: This agent's ID (via os.getenv)

    Args:
        message: The proactive notification message to send to the user(s)
        owner_only: If True, send only to agent owner. If False (default),
                   send to all users attached to this agent.

    Returns:
        str: Confirmation of messages sent or error message
    """
    import requests

    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    if not bot_token:
        return 'Error: TELEGRAM_BOT_TOKEN environment variable is not set'

    # Get agent ID from injected environment
    agent_id = os.environ.get('LETTA_AGENT_ID')
    if not agent_id:
        return 'Error: LETTA_AGENT_ID not available in execution environment'

    # Use injected client to fetch agent data
    # `client` is automatically injected by Letta runtime
    try:
        agent = client.agents.retrieve(agent_id=agent_id, include=['agent.tags'])
    except Exception as e:
        return f'Error retrieving agent data: {str(e)}'

    tags = agent.tags or []

    # Determine recipients
    if owner_only:
        # Get owner from agent tags (format: owner-tg-{telegram_id})
        owner_ids = [tag[9:] for tag in tags if tag.startswith('owner-tg-')]
        if not owner_ids:
            return 'Error: owner_only=True but no owner-tg-* tag found on agent'
        chat_ids = owner_ids[:1]
    else:
        # Get all telegram users with access via identity tags (format: identity-tg-{telegram_id})
        chat_ids = [
            tag[12:]  # len('identity-tg-') = 12
            for tag in tags
            if tag.startswith('identity-tg-') and tag[12:].isdigit()
        ]
        if not chat_ids:
            return 'Error: No telegram users found (no identity-tg-* tags on agent)'

    # Escape MarkdownV2 special characters
    escaped = re.sub(r'([_*\[\]()~`>#+=|{}.!-])', r'\\\1', message)

    # Send message to each recipient
    url = f'https://api.telegram.org/bot{bot_token}/sendMessage'
    results = []

    for chat_id in chat_ids:
        try:
            resp = requests.post(url, json={
                'chat_id': chat_id,
                'text': escaped,
                'parse_mode': 'MarkdownV2',
            }, timeout=30)
            results.append((chat_id, resp.ok))
            time.sleep(3)
        except requests.exceptions.RequestException:
            results.append((chat_id, False))

    sent = sum(ok for _, ok in results)
    total = len(results)

    if sent == total:
        return 'Message sent successfully via Telegram' if total == 1 else f'Message sent to {sent} users via Telegram'

    failed = [cid for cid, ok in results if not ok]
    return f'Sent to {sent}/{total} users. Failed: {", ".join(failed)}'
