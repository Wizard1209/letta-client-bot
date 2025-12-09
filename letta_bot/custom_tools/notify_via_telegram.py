"""Telegram notification tool for Letta agents.

NOTE: This file is excluded from linting/formatting and designed to be
loaded as a Letta custom tool via source_code registration.
"""

import os
import re
import time


# =============================================================================
# WORKAROUND: Fetch agent data via API (injected agent_state is incomplete)
# TODO: Remove when Letta fixes injected AgentState to include all fields
# =============================================================================
def _fetch_agent_via_api(agent_id: str) -> 'Agent | None':
    """Fetch full agent data via Letta API.

    Workaround for agent_state fields being empty/incomplete in injected state.
    Requires LETTA_API_KEY environment variable.

    Returns:
        Agent object or None if API call fails
    """
    from letta_client import Letta

    api_key = os.environ.get('LETTA_API_KEY')
    if not api_key:
        return None

    client = Letta(api_key=api_key)
    return client.agents.retrieve(agent_id=agent_id, include=['agent.identities'])


def _fetch_identifier_keys_via_api(agent_id: str) -> list[str]:
    """Fetch identifier_keys from agent's identities via Letta API.

    Returns:
        List of identifier_key strings (e.g., ['tg-123456789'])
    """
    agent = _fetch_agent_via_api(agent_id)
    if not agent:
        return []

    identifier_keys = []
    for identity in agent.identities or []:
        if hasattr(identity, 'identifier_key') and identity.identifier_key:
            identifier_keys.append(identity.identifier_key)

    return identifier_keys


def _fetch_tags_via_api(agent_id: str) -> list[str]:
    """Fetch tags from agent via Letta API.

    Returns:
        List of tag strings (e.g., ['owner-tg-123456789'])
    """
    agent = _fetch_agent_via_api(agent_id)
    if not agent:
        return []

    return agent.tags or []
# =============================================================================


def notify_via_telegram(
    message: str,
    agent_state: 'AgentState',
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

    Args:
        message: The proactive notification message to send to the user(s)
        agent_state: Automatically injected by Letta runtime
        owner_only: If True, send only to agent owner. If False (default),
                   send to all users attached to this agent.

    Returns:
        str: Confirmation of messages sent or error message
    """
    import requests

    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    if not bot_token:
        return 'Error: TELEGRAM_BOT_TOKEN environment variable is not set'

    # Determine recipients
    if owner_only:
        # WORKAROUND: Fetch tags via API (agent_state.tags may be empty)
        tags = _fetch_tags_via_api(agent_state.id)
        owner_ids = [tag[9:] for tag in tags if tag.startswith('owner-tg-')]
        if not owner_ids:
            return 'Error: owner_only=True but no owner-tg-* tag found on agent'
        chat_ids = owner_ids[:1]
    else:
        # WORKAROUND: Fetch all identities via API (agent_state.identities is empty)
        identifier_keys = _fetch_identifier_keys_via_api(agent_state.id)
        chat_ids = [
            key[3:]
            for key in identifier_keys
            if key.startswith('tg-') and key[3:].isdigit()
        ]
        if not chat_ids:
            return 'Error: No telegram users found (no identities with tg-* identifier_key)'

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
