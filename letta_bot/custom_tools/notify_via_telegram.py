"""Telegram notification tool for Letta agents.

NOTE: This file is excluded from linting/formatting and designed to be
loaded as a Letta custom tool via source_code registration.
"""

import os


def notify_via_telegram(message: str) -> str:
    """Send proactive notification to Telegram user.

    CRITICAL: This tool is ONLY for proactive behavior - reactions to triggers OTHER than
    user messages (scheduled events, system events, time-based triggers, etc.).

    Regular conversation responses to user messages go through the normal chat flow.
    The user will ONLY see messages you explicitly send via this tool - they do NOT see
    scheduled messages arriving, nor your internal processing of those messages.

    This tool sends a notification message to the Telegram chat using the bot API.
    Environment variables TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set
    in the agent's tool execution environment.

    Args:
        message (str): The proactive notification message to send to the user

    Returns:
        str: Confirmation that the message was sent or error message
    """
    import requests

    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID')

    if not bot_token:
        return 'Error: TELEGRAM_BOT_TOKEN environment variable is not set'
    if not chat_id:
        return 'Error: TELEGRAM_CHAT_ID environment variable is not set'

    # Escape MarkdownV2 special characters
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    markdown_text = message
    for char in special_chars:
        markdown_text = markdown_text.replace(char, f'\\{char}')

    # Send message via Telegram API
    url = f'https://api.telegram.org/bot{bot_token}/sendMessage'
    payload = {'chat_id': chat_id, 'text': markdown_text, 'parse_mode': 'MarkdownV2'}

    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            return 'Message sent successfully via Telegram'
        return f'Failed to send Telegram message: {response.status_code} - {response.text}'
    except requests.exceptions.RequestException as e:
        return f'Error sending Telegram message: {str(e)}'
