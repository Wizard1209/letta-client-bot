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


def _parse_tg_error(resp):
    """Parse Telegram API error into agent-friendly message."""
    try:
        data = resp.json()
    except Exception:
        return f'Telegram API HTTP {resp.status_code}'

    code = data.get('error_code', resp.status_code)
    desc = data.get('description', '')
    desc_lower = desc.lower()

    if code == 400:
        if 'message_too_long' in desc_lower or 'message is too long' in desc_lower:
            return 'Message too long (limit 4096). Shorten and retry.'
        if 'chat not found' in desc_lower:
            return 'Chat not found.'
        if 'message text is empty' in desc_lower:
            return 'Message text is empty.'
        return f'Bad request: {desc}'

    if code == 403:
        if 'blocked' in desc_lower:
            return 'User blocked the bot.'
        if 'kicked' in desc_lower:
            return 'Bot was removed from chat.'
        if 'deactivated' in desc_lower:
            return 'User account is deactivated.'
        return f'Forbidden: {desc}'

    if code == 429:
        retry_after = data.get('parameters', {}).get('retry_after', '?')
        return f'Rate limited. Retry after {retry_after}s.'

    return f'Telegram error {code}: {desc}'


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

    msg_len = len(escaped.encode('utf-16-le')) // 2
    if msg_len > 4096:
        orig_len = len(message.encode('utf-16-le')) // 2
        return (
            f'Error: escaped message is {msg_len} UTF-16 chars (original: {orig_len}), '
            f'Telegram limit is 4096. Shorten your message and try again.'
        )

    # Send message to each recipient
    url = f'https://api.telegram.org/bot{bot_token}/sendMessage'
    sent = 0
    errors = []

    for chat_id in chat_ids:
        try:
            resp = requests.post(url, json={
                'chat_id': chat_id,
                'text': escaped,
                'parse_mode': 'MarkdownV2',
            }, timeout=30)
            if resp.ok:
                sent += 1
            else:
                errors.append(_parse_tg_error(resp))
            time.sleep(3)
        except requests.exceptions.RequestException as e:
            errors.append(f'Network error: {e}. Retryable.')

    if not errors:
        return 'Sent.' if sent == 1 else f'Sent to {sent} users.'

    summary = '; '.join(set(errors))
    if sent:
        return f'Sent to {sent}/{sent + len(errors)}. Errors: {summary}'
    return f'Error: {summary}'
