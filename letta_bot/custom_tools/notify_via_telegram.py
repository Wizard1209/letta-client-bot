"""Telegram notification tool for Letta agents.

NOTE: This file is excluded from linting/formatting and designed to be
loaded as a Letta custom tool via source_code registration.
"""

import os
import re


def notify_via_telegram(
    message: str,
    *,
    owner_only: bool = False,
    agent_state: 'AgentState',
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

    Args:
        message: The proactive notification message to send to the user(s)
        agent_state: Automatically injected by Letta runtime
        owner_only: If True, send only to agent owner. If False (default),
                   send to all users attached to this agent.

    Returns:
        str: Confirmation of messages sent or error message
    """
    import requests

    if not (bot_token := os.environ.get('TELEGRAM_BOT_TOKEN')):
        return 'Error: TELEGRAM_BOT_TOKEN environment variable is not set'

    # Extract telegram IDs from identities (identifier_key format: tg-{telegram_id})
    identities = getattr(agent_state, 'identities', []) or []
    chat_ids = [
        key[3:]
        for identity in identities
        if (key := getattr(identity, 'identifier_key', ''))
        and key.startswith('tg-')
        and key[3:].isdigit()
    ]

    # Fallback to legacy env var for backwards compatibility
    if not chat_ids:
        if legacy_id := os.environ.get('TELEGRAM_CHAT_ID'):
            chat_ids = [legacy_id]
        else:
            return 'Error: No telegram users found (no identities with tg-* identifier_key)'

    # Filter to owner only if requested
    if owner_only:
        tags = getattr(agent_state, 'tags', []) or []
        owner_ids = [tag[9:] for tag in tags if tag.startswith('owner-tg-')]

        if not owner_ids:
            return 'Error: owner_only=True but no owner-tg-* tag found on agent'
        if owner_ids[0] not in chat_ids:
            return f'Error: Owner {owner_ids[0]} not in attached identities'

        chat_ids = owner_ids[:1]

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
            }, timeout=10)
            results.append((chat_id, resp.ok))
        except requests.exceptions.RequestException:
            results.append((chat_id, False))

    sent = sum(ok for _, ok in results)
    total = len(results)

    if sent == total:
        return 'Message sent successfully via Telegram' if total == 1 else f'Message sent to {sent} users via Telegram'

    failed = [cid for cid, ok in results if not ok]
    return f'Sent to {sent}/{total} users. Failed: {", ".join(failed)}'
