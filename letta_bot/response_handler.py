"""Agent response handling for Telegram messages.

This module handles:
1. Formatting Letta streaming responses into formatted Text objects
2. Splitting long messages to respect Telegram's length limits
3. Managing stream event processing with state (ping indicators, message editing)
4. Sending responses to users
"""

from collections import deque
import json
import logging
from typing import Any

from aiogram.types import Message
from aiogram.utils.formatting import BlockQuote, Bold, Code, Italic, Text
from letta_client.types.agents.letta_streaming_response import LettaStreamingResponse

LOGGER = logging.getLogger(__name__)


TELEGRAM_MAX_LEN = 4096
MARKDOWN_TOKENS = {'`': ('```', '`'), '*': ('*',), '_': ('_',), '~': ('~',)}

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
        special_chars = (
            '_',
            '*',
            '[',
            ']',
            '(',
            ')',
            '~',
            '`',
            '>',
            '#',
            '+',
            '-',
            '=',
            '|',
            '{',
            '}',
            '.',
            '!',
        )
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
def _get_next_token(text: str, pos: int, escaped: bool) -> tuple[str | None, int]:
    """Find the next Markdown token at the given position.

    Checks if the text starting from `pos` begins with any known Markdown token,
    unless the preceding character was an escape character '\'.

    Args:
        text: The string to search within.
        pos: The starting position in the text to check for a token.
        escaped: True if the character immediately preceding `pos` was an
                 escape character ('\'), False otherwise.

    Returns:
        A tuple containing:
        - The found Markdown token (str) or None if no token is found
          at the position or if it's escaped.
        - The length of the found token (int), or 0 if no token is found.
    """
    if escaped:
        return None, 0
    first = text[pos]
    for token in MARKDOWN_TOKENS.get(first, ()):
        if text.startswith(token, pos):
            return token, len(token)
    return None, 0


def split_markdown_v2(
    text: str,
    limit: int = TELEGRAM_MAX_LEN,
    recommended_margin: int = 400,
    safety_margin: int = 50,
) -> list[str]:
    """Split a Markdown text into chunks while trying to preserve formatting.

    Attempts to split the text into chunks smaller than `limit`. It tracks
    opening and closing Markdown tokens using a stack. When a chunk needs to be
    split, it appends the necessary closing tokens to the end of the current
    chunk and prepends the corresponding opening tokens to the beginning of the
    next chunk.

    Splitting priority:
    1. At a newline character when the buffer size is close to the limit
       (within `recommended_margin`).
    2. Anywhere when the buffer size is very close to the limit
       (within `safety_margin`).

    Args:
        text: The Markdown string to split.
        limit: The maximum desired length for each chunk. Defaults to
               `constants.MessageLimit.MAX_TEXT_LENGTH`.
        recommended_margin: The preferred distance from the `limit` at which
               to split, ideally looking for a newline.
        safety_margin: The absolute minimum distance from the `limit` at which
               a split must occur, regardless of the character.

    Returns:
        A list of strings, where each string is a chunk of the original text,
        with formatting tokens adjusted to maintain validity across chunks.
    """

    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    buffer: list[str] = []
    buf_len = 0
    stack: deque[str] = deque()
    i = 0
    n = len(text)
    escaped = False

    while i < n:
        token, shift = _get_next_token(text, i, escaped)
        next_piece = token if token else text[i]
        next_len = len(next_piece)
        escaped = text[i] == '\\'

        if buf_len + next_len > limit - safety_margin:
            closing_sequence = ''.join(reversed(stack))
            chunks.append(''.join(buffer) + closing_sequence)
            buffer = list(stack)
            buf_len = sum(len(t) for t in stack)

        buffer.append(next_piece)
        buf_len += next_len

        if token:
            if stack and stack[-1] == token:
                stack.pop()
            else:
                stack.append(token)
            i += shift
        else:
            i += 1

        if buf_len >= limit - recommended_margin and i < n and text[i] == '\n':
            closing_sequence = ''.join(reversed(stack))
            chunks.append(''.join(buffer) + closing_sequence)
            buffer = list(stack)
            buf_len = sum(len(t) for t in stack)
            i += 1  # skip newline

    if buffer:
        chunks.append(''.join(buffer))

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
    telegram_markdown = convert_to_telegram_markdown(content)
    for chunk in split_markdown_v2(telegram_markdown):
        await message.answer(chunk, parse_mode='MarkdownV2')


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
