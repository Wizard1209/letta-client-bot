"""Agent response handling for Telegram messages.

This module handles:
1. Formatting Letta streaming responses into formatted Text objects
2. Splitting long messages to respect Telegram's length limits
3. Managing stream event processing with state (ping indicators, message editing)
4. Sending responses to users
"""

from collections import deque
from datetime import datetime, timedelta
import difflib
from itertools import islice
import json
import logging
import re
from typing import Any

from aiogram.enums import ParseMode
from aiogram.types import Message
from letta_client.types.agents.letta_streaming_response import LettaStreamingResponse

LOGGER = logging.getLogger(__name__)


TELEGRAM_MAX_LEN = 4096
MARKDOWN_TOKENS = {'`': ('```', '`'), '*': ('*',), '_': ('_',), '~': ('~',)}

# =============================================================================
# Stream Event Formatting (Helper Functions)
# =============================================================================


def _get_diff_text(old: str, new: str) -> str:
    """Generate a unified diff between two text strings, excluding header lines."""
    if not old.endswith('\n'):
        old += '\n'
    if not new.endswith('\n'):
        new += '\n'

    diff = difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile='old',
        tofile='new',
    )
    return ''.join(
        islice(diff, 3, None)  # skip first three lines
    )


def _format_datetime(dt_string: str) -> str:
    """Format datetime string to readable format with timezone.

    Args:
        dt_string: ISO datetime string (e.g., "2024-01-01" or "2024-01-01T10:30:00+05:00")

    Returns:
        Formatted datetime string with timezone
        (e.g., "Jan 01, 2024" or "Jan 01, 2024 10:30 (UTC+05:00)")
    """
    try:
        # Try parsing with time component
        if 'T' in dt_string:
            dt = datetime.fromisoformat(dt_string.replace('Z', '+00:00'))

            # Get UTC offset
            offset = dt.strftime('%z')  # e.g., '+0500'
            offset_formatted = f'{offset[:3]}:{offset[3:]}'  # '+05:00'

            return f'{dt.strftime("%b %d, %Y %H:%M")} (UTC{offset_formatted})'
        else:
            # Date only
            dt = datetime.fromisoformat(dt_string)
            return dt.strftime('%b %d, %Y')
    except (ValueError, AttributeError):
        # Fallback to original string if parsing fails
        return dt_string


def _escape_markdown_v2(text: str) -> str:
    """Escape all special characters required by Telegram MarkdownV2."""
    pattern = re.compile(r'([\_\*\[\]\(\)\~\`\>\#\+\-\=\|\{\}\.\!\/\\])')
    return pattern.sub(r'\\\1', text)


def convert_to_telegram_markdown(text: str) -> str:
    """Convert text to Telegram MarkdownV2 using telegramify-markdown."""
    try:
        # Use telegramify-markdown to handle proper escaping and conversion
        import telegramify_markdown  # type: ignore[import-untyped]

        telegram_text: str = telegramify_markdown.markdownify(text)
        return telegram_text
    except Exception as e:
        LOGGER.warning('Error converting to Telegram markdown: %s', e)
        # Fallback: return the original text with basic escaping
        # Escape MarkdownV2 special characters
        return _escape_markdown_v2(text)


def _make_blockquote(text: str) -> str:
    """Format plain text as a Markdown-style blockquote for Telegram."""
    return '\n'.join(f'>{line}' for line in text.splitlines())


def _format_reasoning_message(event: LettaStreamingResponse) -> str:
    """Format reasoning message response.

    Args:
        event: Stream event containing reasoning message

    Returns:
        Formatted Text object with reasoning content
    """
    reasoning_text = _escape_markdown_v2(getattr(event, 'reasoning', ''))
    if len(reasoning_text) > TELEGRAM_MAX_LEN:
        LOGGER.warning('Reasoning message too long')
        reasoning_text = reasoning_text[:TELEGRAM_MAX_LEN]
    return f'_Agent reasoning:_\n{_make_blockquote(reasoning_text)}'


def _format_tool_call_message(event: LettaStreamingResponse) -> str | None:
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
        return f'*Agent using tool: {_escape_markdown_v2(tool_name)}\
                \n\n```{_escape_markdown_v2(arguments)}```'


def _format_tool_by_name(
    tool_name: str, args_obj: dict[str, Any], raw_arguments: str
) -> str | None:
    """Format tool call based on tool name.

    Args:
        tool_name: Name of the tool being called
        args_obj: Parsed JSON arguments
        raw_arguments: Raw JSON string (fallback for generic display)

    Returns:
        Formatted Text object or None for tools that should be hidden
    """
    match tool_name:
        # Memory operations
        case 'archival_memory_insert':
            return _format_archival_memory_insert(args_obj)

        case 'archival_memory_search':
            return _format_archival_memory_search(args_obj)

        case 'memory_insert':
            return _format_memory_insert(args_obj, legacy=True)

        case 'memory_replace':
            return _format_memory_replace(args_obj)

        case 'memory':
            return _format_memory(args_obj)

        # Code execution
        case 'run_code':
            return _format_run_code(args_obj)

        case 'web_search':
            return _format_web_search(args_obj)

        case 'fetch_webpage':
            return _format_fetch_webpage(args_obj)

        case 'conversation_search':
            return _format_conversation_search(args_obj)

        # Notifications and scheduling
        case 'schedule_message':
            return _format_schedule_message(args_obj)

        case 'notify_via_telegram':
            return _format_notify_via_telegram()

        # Generic tool
        case _:
            LOGGER.warning('No formatting supported for tool %s', tool_name)
            return _format_generic_tool(tool_name, args_obj)


def _format_conversation_search(args_obj: dict[str, Any]) -> str:
    """Format conversation_search tool call."""
    query = _escape_markdown_v2(args_obj.get('query', ''))
    limit = args_obj.get('limit')
    start_date = args_obj.get('start_date', '')
    end_date = args_obj.get('end_date', '')
    roles = args_obj.get('roles', [])

    header = '🔍 _Searching conversation history\\.\\.\\._\n'
    header += f'*Query:* "{query}"'

    parts = []

    if limit:
        parts.append(f'top {limit} results')

    if start_date and end_date:
        formatted_start = _escape_markdown_v2(_format_datetime(start_date))
        formatted_end = _escape_markdown_v2(_format_datetime(end_date))
        parts.append(f'between {formatted_start} and {formatted_end}')
    elif start_date:
        formatted_start = _escape_markdown_v2(_format_datetime(start_date))
        parts.append(f'after {formatted_start}')
    elif end_date:
        formatted_end = _escape_markdown_v2(_format_datetime(end_date))
        parts.append(f'before {formatted_end}')

    if roles:
        formatted_roles = ', '.join(_escape_markdown_v2(role) for role in roles)
        parts.append(f'roles: {formatted_roles}')

    if parts:
        header += '\n' + '\n'.join(f'• {part}' for part in parts)

    return header


def _format_schedule_message(args_obj: dict[str, Any]) -> str:
    """Format schedule_message tool call."""

    message_to_self = _escape_markdown_v2(args_obj.get('message_to_self', ''))
    delay_seconds = args_obj.get('delay_seconds')
    schedule_at = args_obj.get('schedule_at', '')

    header = '⏱️ _Setting self activation\\.\\.\\._\n'

    # Show timing first (most important info)
    if delay_seconds is not None:
        td = timedelta(seconds=delay_seconds)
        total_seconds = int(td.total_seconds())

        # Format human-readable string (prioritize largest unit)
        if td.days >= 365:
            years = td.days // 365
            time_str = f'{years} year{"s" if years != 1 else ""}'
        elif td.days > 0:
            time_str = f'{td.days} day{"s" if td.days != 1 else ""}'
        elif total_seconds >= 3600:
            hours = total_seconds // 3600
            time_str = f'{hours} hour{"s" if hours != 1 else ""}'
        elif total_seconds >= 60:
            minutes = total_seconds // 60
            time_str = f'{minutes} minute{"s" if minutes != 1 else ""}'
        else:
            time_str = f'{total_seconds} second{"s" if total_seconds != 1 else ""}'

        header += f'*When:* in {_escape_markdown_v2(time_str)}\n'
    elif schedule_at:
        formatted_time = _escape_markdown_v2(_format_datetime(schedule_at))
        header += f'*When:* {formatted_time}\n'

    # Message content last
    header += f'*Message:* "{message_to_self}"'

    return header


def _format_notify_via_telegram() -> str:
    """Format notify_via_telegram tool call."""
    return '📲 _Sending message to Telegram\\.\\.\\._'


def _format_web_search(args_obj: dict[str, Any]) -> str:
    query = args_obj.get('query', '')
    num_results = args_obj.get('num_results', '')
    category = args_obj.get('category', '')
    include_text = args_obj.get('include_text', False)
    include_domains = args_obj.get('include_domains', [])
    exclude_domains = args_obj.get('exclude_domains', [])
    start_published_date = args_obj.get('start_published_date', '')
    end_published_date = args_obj.get('end_published_date', '')
    user_location = args_obj.get('user_location', '')

    def format_domains(domains: list[str]) -> str:
        return '\\[' + ', '.join(_escape_markdown_v2(item) for item in domains) + '\\]'

    header = '🔍 _Let me search for this\\.\\.\\._\n'
    header += f'*Query:* "{_escape_markdown_v2(query)}"'

    parts = []

    if num_results:
        parts.append(f'top {num_results} results')
    if category:
        parts.append(f'category: {_escape_markdown_v2(category)}')

    if include_domains:
        parts.append(f'limited to {format_domains(include_domains)}')
    if exclude_domains:
        parts.append(f'excluding {format_domains(exclude_domains)}')
    if include_text:
        parts.append('retrieving full page content')
    if start_published_date and end_published_date:
        formatted_start = _escape_markdown_v2(_format_datetime(start_published_date))
        formatted_end = _escape_markdown_v2(_format_datetime(end_published_date))
        parts.append(f'published between {formatted_start} and {formatted_end}')
    elif start_published_date:
        formatted_start = _escape_markdown_v2(_format_datetime(start_published_date))
        parts.append(f'published after {formatted_start}')
    elif end_published_date:
        formatted_end = _escape_markdown_v2(_format_datetime(end_published_date))
        parts.append(f'published before {formatted_end}')

    if user_location:
        parts.append(f'localized for {_escape_markdown_v2(user_location)} users')

    if parts:
        header += '\n' + '\n'.join(f'• {part}' for part in parts)

    return header


def _format_fetch_webpage(args_obj: dict[str, Any]) -> str:
    url = _escape_markdown_v2(args_obj.get('url', ''))
    return f'🌐 _Fetching webpage_\\.\\.\\.\n_Retrieving content from_ {url}'


def _format_archival_memory_insert(args_obj: dict[str, Any]) -> str:
    """Format archival_memory_insert tool call."""
    content_text = args_obj.get('content', '')
    tags = args_obj.get('tags', [])

    # Convert content using the same conversion as assistant messages
    converted_content = convert_to_telegram_markdown(
        content_text
    )  # FIXME: split long message

    header = '💾 _Storing in archival memory\\.\\.\\._\n'

    if tags:
        formatted_tags = ', '.join(_escape_markdown_v2(tag) for tag in tags)
        header += f'*Tags:* {formatted_tags}\n'

    header += f'\n*Content:*\n{converted_content}'

    return header


def _format_archival_memory_search(args_obj: dict[str, Any]) -> str:
    """Format archival_memory_search tool call."""
    query = _escape_markdown_v2(args_obj.get('query', ''))
    start_datetime = args_obj.get('start_datetime', '')
    end_datetime = args_obj.get('end_datetime', '')
    tags = args_obj.get('tags', [])
    tag_match_mode = args_obj.get('tag_match_mode', '')
    top_k = args_obj.get('top_k')

    header = '🔍 _Searching archival memory\\.\\.\\._\n'
    header += f'*Query:* "{query}"'

    parts = []
    if top_k:
        parts.append(f'top {top_k} results')

    if start_datetime and end_datetime:
        formatted_start = _escape_markdown_v2(_format_datetime(start_datetime))
        formatted_end = _escape_markdown_v2(_format_datetime(end_datetime))
        parts.append(f'between {formatted_start} and {formatted_end}')
    elif start_datetime:
        formatted_start = _escape_markdown_v2(_format_datetime(start_datetime))
        parts.append(f'after {formatted_start}')
    elif end_datetime:
        formatted_end = _escape_markdown_v2(_format_datetime(end_datetime))
        parts.append(f'before {formatted_end}')

    if tags:
        formatted_tags = ', '.join(_escape_markdown_v2(tag) for tag in tags)
        tag_mode = f' \\({tag_match_mode}\\)' if tag_match_mode else ''
        parts.append(f'tags: {formatted_tags}{tag_mode}')

    if parts:
        header += '\n' + '\n'.join(f'• {part}' for part in parts)

    return header


def _format_memory_insert(args_obj: dict[str, Any], legacy: bool = False) -> str:
    """Format memory_insert tool call."""
    insert_text = _escape_markdown_v2(
        args_obj.get('new_str' if legacy else 'insert_text', '')
    )
    path = _escape_markdown_v2(args_obj.get('path', ''))

    return f'📝 _Updating memory block\\.\\.\\._\n*Path:* {path}\n\n{insert_text}'


def _format_memory_replace(args_obj: dict[str, Any]) -> str | None:
    """Format memory_replace tool call."""
    path = _escape_markdown_v2(args_obj.get('path', ''))
    old_str = _escape_markdown_v2(args_obj.get('old_str', ''))
    new_str = _escape_markdown_v2(args_obj.get('new_str', ''))

    diff = _get_diff_text(old_str, new_str)
    header = '🔧 _Modifying memory block\\.\\.\\._\n'
    if path:
        header += f'*Path:* {path}\n'
    return f'{header}```diff\n{diff}```'


def _format_memory_rename(args_obj: dict[str, Any]) -> str:
    description = _escape_markdown_v2(args_obj.get('description', ''))
    path = _escape_markdown_v2(args_obj.get('path', ''))
    new_path = _escape_markdown_v2(args_obj.get('new_path', ''))
    old_path = _escape_markdown_v2(args_obj.get('old_path', ''))

    if description and path:
        return (
            '🏷️ _Updating memory description\\.\\.\\._\n'
            f'*Path:* {path}\n'
            f'*New description:* "{description}"'
        )
    return f'📂 _Renaming memory block\\.\\.\\._\n*From:* {old_path}\n*To:* {new_path}'


def _format_memory_delete(args_obj: dict[str, Any]) -> str:
    path = _escape_markdown_v2(args_obj.get('path', ''))
    return f'🧹 _Removing a memory block\\.\\.\\._\nDeleting *"{path}"* permanently\\.'


def _format_memory_create(args_obj: dict[str, Any]) -> str:
    """Format memory create tool call.

    Handles two scenarios:
    1. Creating memory block with initial content (has 'file_text')
    2. Creating empty memory block (no 'file_text')
    """
    path = _escape_markdown_v2(args_obj.get('path', ''))
    description = _escape_markdown_v2(args_obj.get('description', ''))
    file_text = args_obj.get('file_text', '')

    if file_text:
        # Creating memory with initial content
        # Convert file_text using the same conversion as assistant messages
        converted_content = convert_to_telegram_markdown(
            file_text
        )  # FIXME: split long message
        header = '📝 _Creating new memory block\\.\\.\\._\n'
        header += f'*Path:* {path}\n'
        if description:
            header += f'*Description:* "{description}"\n'
        header += f'\n*Initial content:*\n{converted_content}'
        return header
    else:
        # Creating empty memory block
        header = '📝 _Creating new memory block\\.\\.\\._\n'
        header += f'*Path:* {path}\n'
        if description:
            header += f'*Description:* "{description}"'
        return header


def _format_memory(args_obj: dict[str, Any]) -> None | str:
    """Format memory tool call."""
    match args_obj:
        case {'command': 'str_replace'}:
            return _format_memory_replace(args_obj)
        case {'command': 'insert'}:
            return _format_memory_insert(args_obj)
        case {'command': 'rename'}:
            return _format_memory_rename(args_obj)
        case {'command': 'delete'}:
            return _format_memory_delete(args_obj)
        case {'command': 'create'}:
            return _format_memory_create(args_obj)
        case _:
            LOGGER.warning('Not implemented features: %s', args_obj)
            return None


def _format_run_code(args_obj: dict[str, Any]) -> str:
    """Format run_code tool call."""
    code = _escape_markdown_v2(args_obj.get('code', ''))  # FIXME: maybe long message?
    language = args_obj.get('language', 'python')

    header = '⚙️ _Executing code\\.\\.\\._\n'
    header += f'*Language:* {_escape_markdown_v2(language)}\n'
    header += f'```{language}\n{code}\n```'

    return header


def _format_generic_tool(tool_name: str, args_obj: dict[str, Any]) -> str:
    """Format generic tool call with JSON arguments."""
    formatted_args = _escape_markdown_v2(json.dumps(args_obj, indent=2))

    header = '🔧 _Using tool\\.\\.\\._\n'
    header += f'*Tool:* {_escape_markdown_v2(tool_name)}\n'
    header += f'\n*Arguments:*\n```json\n{formatted_args}\n```'

    return header


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


async def _send_error_message(message: Message, reason: Exception, content: str) -> None:
    """Send formatted error message to user and log the reason.

    Args:
        message: Original message from user
        reason: Error description to log
    """
    LOGGER.warning('Failed to send message: %s\ncontent: %s', reason)
    LOGGER.debug('Content: %s', reason)

    error_text = '❌ Something went wrong'

    await message.answer(text=error_text, parse_mode=ParseMode.MARKDOWN_V2)


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
        try:
            await message.answer(chunk, parse_mode=ParseMode.MARKDOWN_V2)
        except Exception as e:
            await _send_error_message(message, e, chunk)
            continue


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
                try:
                    await self.telegram_message.answer(
                        formatted_content, parse_mode=ParseMode.MARKDOWN_V2
                    )
                except Exception as e:
                    await _send_error_message(self.telegram_message, e, formatted_content)
            return

        # System alerts (informational messages from Letta)
        if message_type == 'system_message':
            alert_message = getattr(event, 'message', '')
            if alert_message and alert_message.strip():
                alert_content = f'_\\(info: _{_escape_markdown_v2(alert_message)}_\\)_'
                await self.telegram_message.answer(
                    alert_content, parse_mode=ParseMode.MARKDOWN_V2
                )
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
        ping_text = '⏳' * self.ping_count

        if self.ping_message is None:
            # First ping: Send new message
            self.ping_message = await self.telegram_message.answer(ping_text)
        else:
            # Subsequent pings: Edit to add more hourglasses
            try:
                await self.ping_message.edit_text(ping_text)
            except Exception as e:
                LOGGER.warning(f'Failed to edit ping message: {e}')

    def _format_other_event(self, event: LettaStreamingResponse) -> str | None:
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
