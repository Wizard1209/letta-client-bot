"""Agent response handling for Telegram messages.

This module handles:
1. Formatting Letta streaming responses into formatted Text objects
2. Splitting long messages to respect Telegram's length limits
3. Managing stream event processing with state (ping indicators, message editing)
4. Sending responses to users
"""

import json
import logging
from typing import Any

from aiogram.types import Message
from aiogram.utils.formatting import BlockQuote, Bold, Code, Italic, Text
from letta_client.agents.messages.types.letta_streaming_response import (
    LettaStreamingResponse,
)

LOGGER = logging.getLogger(__name__)


TELEGRAM_MAX_LEN = 4096


# =============================================================================
# Stream Event Formatting (Helper Functions)
# =============================================================================


def convert_to_telegram_markdown(text: str) -> str:
    """Convert text to Telegram MarkdownV2 using telegramify-markdown."""
    try:
        # Use telegramify-markdown to handle proper escaping and conversion
        import telegramify_markdown  # type: ignore[import-untyped]

        telegram_text: str = telegramify_markdown.markdownify(text)
        return telegram_text
    except Exception as e:
        print(f'Error converting to Telegram markdown: {e}')
        # Fallback: return the original text with basic escaping
        # Escape MarkdownV2 special characters
        special_chars = ('_', '*', '[', ']', '(', ')', '~', '`', '>', '#',
                         '+', '-', '=', '|', '{', '}', '.', '!')
        escaped_text = text
        for char in special_chars:
            escaped_text = escaped_text.replace(char, f'\\{char}')
        return escaped_text


def _format_reasoning_message(event: LettaStreamingResponse) -> Text:
    """Format reasoning message response.

    Args:
        event: Stream event containing reasoning message

    Returns:
        Formatted Text object with reasoning content
    """
    reasoning_text = getattr(event, 'reasoning', '')
    if len(reasoning_text) > TELEGRAM_MAX_LEN:
        LOGGER.warning('Reasoning message too long')
        reasoning_text = reasoning_text[:TELEGRAM_MAX_LEN]
    return Text(Italic('Agent reasoning:'), '\n', BlockQuote(reasoning_text))


def _format_tool_call_message(event: LettaStreamingResponse) -> Text | None:
    """Format tool call message response.

    Args:
        event: Stream event containing tool call

    Returns:
        Formatted Text object or None if tool call should be skipped
    """
    tool_call = event.tool_call  # type: ignore
    tool_name = tool_call.name
    arguments = tool_call.arguments

    # Ensure tool_name is a string
    if not isinstance(tool_name, str):
        return None

    if not arguments or not arguments.strip():
        return None

    try:
        args_obj = json.loads(arguments)
        return _format_tool_by_name(tool_name, args_obj, arguments)

    except json.JSONDecodeError as e:
        LOGGER.warning(f'Error parsing tool arguments: {e}')
        return Text(
            Bold('Agent using tool:'),
            f' {tool_name}\n\n',
            Code('', arguments),
        )


def _format_tool_by_name(
    tool_name: str, args_obj: dict[str, Any], raw_arguments: str
) -> Text | None:
    """Format tool call based on tool name.

    Args:
        tool_name: Name of the tool being called
        args_obj: Parsed JSON arguments
        raw_arguments: Raw JSON string (fallback for generic display)

    Returns:
        Formatted Text object or None for tools that should be hidden
    """
    # Memory operations
    if tool_name == 'archival_memory_insert':
        return _format_archival_memory_insert(args_obj)

    elif tool_name == 'archival_memory_search':
        return _format_archival_memory_search(args_obj)

    elif tool_name == 'memory_insert':
        return _format_memory_insert(args_obj)

    elif tool_name == 'memory_replace':
        return _format_memory_replace(args_obj)

    # Code execution
    elif tool_name == 'run_code':
        return _format_run_code(args_obj)

    # Generic tool display
    else:
        LOGGER.warning('No formating supported for tool %s', tool_name)
        return _format_generic_tool(tool_name, args_obj)


def _format_archival_memory_insert(args_obj: dict[str, Any]) -> Text:
    """Format archival_memory_insert tool call."""
    content_text = args_obj.get('content', '')
    return Text(
        Bold('Agent remembered:'),
        '\n\n',
        BlockQuote(content_text),
    )


def _format_archival_memory_search(args_obj: dict[str, Any]) -> Text:
    """Format archival_memory_search tool call."""
    query = args_obj.get('query', '')
    return Text(Bold('Agent searching:'), ' ', query)


def _format_memory_insert(args_obj: dict[str, Any]) -> Text:
    """Format memory_insert tool call."""
    new_str = args_obj.get('new_str', '')
    return Text(
        Bold('Agent updating memory:'),
        '\n\n',
        BlockQuote(new_str),
    )


def _format_memory_replace(args_obj: dict[str, Any]) -> Text:
    """Format memory_replace tool call."""
    old_str = args_obj.get('old_str', '')
    new_str = args_obj.get('new_str', '')
    return Text(
        Bold('Agent modifying memory:'),
        '\n\n',
        'New:\n',
        BlockQuote(new_str),
        '\n\nOld:\n',
        BlockQuote(old_str),
    )


def _format_run_code(args_obj: dict[str, Any]) -> Text:
    """Format run_code tool call."""
    code = args_obj.get('code', '')
    language = args_obj.get('language', 'python')
    return Text(
        Bold('Agent ran code:'),
        '\n\n',
        Code(language, code),
    )


def _format_generic_tool(tool_name: str, args_obj: dict[str, Any]) -> Text:
    """Format generic tool call with JSON arguments."""
    formatted_args = json.dumps(args_obj, indent=2)
    return Text(
        Bold('Agent using tool:'),
        f' {tool_name}\n\n',
        Code('json', formatted_args),
    )


# =============================================================================
# Message Splitting and Sending
# =============================================================================


def split_raw_text(text: str, max_length: int = TELEGRAM_MAX_LEN) -> list[str]:
    """Split text at natural boundaries (\n or space) near max_length."""
    if len(text) <= max_length:
        return [text]

    chunks = []
    pos = 0

    while pos < len(text):
        remaining = len(text) - pos

        # If remaining text fits, take it all (don't split further)
        if remaining <= max_length:
            chunks.append(text[pos:])
            break

        # Need to split: find natural boundary in next max_length chars
        chunk = text[pos : pos + max_length]
        split = chunk.rfind('\n')
        if split == -1:
            split = chunk.rfind(' ')

        split = split + 1 if split != -1 else len(chunk)
        chunks.append(text[pos : pos + split])
        pos += split

    return chunks


async def send_assistant_message(message: Message, content: str) -> None:
    """Send assistant message, splitting and converting to Telegram markdown.

    Args:
        message: Telegram message to reply to
        content: Raw markdown content from assistant

    Process:
        1. Split raw content at natural boundaries
        2. Convert each chunk to Telegram MarkdownV2
        3. Send each chunk
    """
    for chunk in split_raw_text(content):
        telegram_markdown = convert_to_telegram_markdown(chunk)
        await message.answer(telegram_markdown, parse_mode='MarkdownV2')

# =============================================================================
# Event Handler with State Management
# =============================================================================


class AgentStreamHandler:
    """Handles event processing with automatic send/edit/skip logic."""

    def __init__(self, telegram_message: Message) -> None:
        """Initialize handler.

        Args:
            telegram_message: The user's message to reply to
        """
        self.telegram_message = telegram_message
        self.ping_count = 0
        self.ping_message: Message | None = None

    async def handle_event(self, event: LettaStreamingResponse) -> None:
        """Process event

        Event order during streaming:
        1. Ping indicators (progress updates)
        2. Tool calls and reasoning (processing)
        3. Assistant message (final response)

        Only assistant_message clears ping state.

        Args:
            event: Stream event from Letta API
        """
        # Guard: Do nothing for events without message_type
        if not hasattr(event, 'message_type'):
            return

        message_type = event.message_type

        # Phase 1: Progress indicator (state management)
        if message_type == 'ping':
            await self._handle_ping()
            return

        # Phase 2: Processing content (reasoning, tool calls, system alerts)
        if message_type in ('reasoning_message', 'tool_call_message'):
            formatted_content = self._format_other_event(event)
            if formatted_content:
                await self.telegram_message.answer(**formatted_content.as_kwargs())
            return

        # System alerts (informational messages from Letta)
        if message_type == 'system_alert':
            alert_message = getattr(event, 'message', '')
            if alert_message and alert_message.strip():
                alert_content = Text(Italic('(info: '), alert_message, Italic(')'))
                await self.telegram_message.answer(**alert_content.as_kwargs())
            return

        # Phase 3: Final response (clears ping state)
        if message_type == 'assistant_message':
            raw_content = getattr(event, 'content', '').strip()
            if raw_content:
                await send_assistant_message(self.telegram_message, raw_content)
                self._clear_ping_state()

    async def _handle_ping(self) -> None:
        """Handle ping events with state management."""
        self.ping_count += 1
        ping_text = Text('⏳' * self.ping_count)

        if self.ping_message is None:
            # First ping: Send new message
            self.ping_message = await self.telegram_message.answer(**ping_text.as_kwargs())
        else:
            # Subsequent pings: Edit to add more hourglasses
            try:
                await self.ping_message.edit_text(**ping_text.as_kwargs())
            except Exception as e:
                LOGGER.warning(f'Failed to edit ping message: {e}')

    def _format_other_event(self, event: LettaStreamingResponse) -> Text | None:
        """Format non-assistant event content (reasoning, tool calls).

        Args:
            event: Stream event from Letta API

        Returns:
            Formatted Text object or None
        """
        message_type = event.message_type

        if message_type == 'reasoning_message':
            return _format_reasoning_message(event)

        elif message_type == 'tool_call_message':
            return _format_tool_call_message(event)

        return None

    def _clear_ping_state(self) -> None:
        """Reset ping tracking state."""
        self.ping_count = 0
        self.ping_message = None
