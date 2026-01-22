"""Agent response handling for Telegram messages.

This module handles:
1. Formatting Letta streaming responses into formatted Text objects
2. Splitting long messages to respect Telegram's length limits
3. Managing stream event processing with state (ping indicators, message editing)
4. Sending responses to users
"""

from datetime import datetime, timedelta
import difflib
from itertools import islice
import json
import logging
from typing import Any

from aiogram.types import Message
from aiogram.utils.formatting import (
    Bold,
    Italic,
    Pre,
    Text,
    Url,
    as_key_value,
    as_line,
    as_marked_list,
)
from letta_client.types.agents.letta_streaming_response import LettaStreamingResponse

from letta_bot.utils import merge_with_entity
from md_tg import markdown_to_telegram

LOGGER = logging.getLogger(__name__)

# Telegram message limit in characters
TELEGRAM_MAX_LEN = 4096


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


def _format_tool_call_message(event: LettaStreamingResponse) -> dict[str, Any] | str | None:
    """Format tool call message response.

    Args:
        event: Stream event containing tool call

    Returns:
        Formatted dict with text and entities, markdown string,
        or None if tool call should be skipped
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
        return Text(as_key_value('Agent using tool', tool_name), Pre(arguments)).as_kwargs()


def _format_tool_by_name(
    tool_name: str, args_obj: dict[str, Any], raw_arguments: str
) -> dict[str, Any] | str | None:
    """Format tool call based on tool name.

    Args:
        tool_name: Name of the tool being called
        args_obj: Parsed JSON arguments
        raw_arguments: Raw JSON string (fallback for generic display)

    Returns:
        Formatted dict with text and entities, markdown string,
        or None for tools that should be hidden
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

        # File operations
        case 'open_files':
            return _format_open_files(args_obj)

        case 'grep_files':
            return _format_grep_files(args_obj)

        case 'semantic_search_files':
            return _format_semantic_search_files(args_obj)

        # Notifications and scheduling
        case 'schedule_message':
            return _format_schedule_message(args_obj)

        case 'notify_via_telegram':
            return _format_notify_via_telegram(args_obj)

        # Generic tool
        case _:
            LOGGER.warning('No formatting supported for tool %s', tool_name)
            return _format_generic_tool(tool_name, args_obj)


def _format_conversation_search(args_obj: dict[str, Any]) -> dict[str, Any]:
    """Format conversation_search tool call."""
    query = args_obj.get('query', '')
    limit = args_obj.get('limit')
    start_date = args_obj.get('start_date', '')
    end_date = args_obj.get('end_date', '')
    roles = args_obj.get('roles', [])

    parts = []

    if limit:
        parts.append(f'top {limit} results')

    if start_date and end_date:
        start = _format_datetime(start_date)
        end = _format_datetime(end_date)
        parts.append(f'between {start} and {end}')
    elif start_date:
        start = _format_datetime(start_date)
        parts.append(f'after {start}')
    elif end_date:
        end = _format_datetime(end_date)
        parts.append(f'before {end}')

    if roles:
        formatted_roles = ', '.join(roles)
        parts.append(f'roles: {formatted_roles}')

    elements = [
        Italic('🔍 Searching conversation history...'),
        as_key_value('Query', f'"{query}"'),
    ]
    if parts:
        elements.append(as_marked_list(*parts, marker='• '))

    return as_line(*elements, sep='\n').as_kwargs()


def _format_open_files(args_obj: dict[str, Any]) -> dict[str, Any]:
    """Format open_files tool call."""
    file_requests = args_obj.get('file_requests', [])
    close_all_others = args_obj.get('close_all_others', False)

    elements: list[Any] = [Italic('📂 Opening files...')]

    # List files being opened
    file_parts = []
    for req in file_requests[:5]:  # Show max 5 files
        file_name = req.get('file_name', '')
        # Extract just the filename from path
        short_name = file_name.split('/')[-1] if '/' in file_name else file_name
        offset = req.get('offset')
        length = req.get('length')

        if offset is not None and length is not None:
            file_parts.append(f'{short_name} (lines {offset + 1}-{offset + length})')
        elif offset is not None:
            file_parts.append(f'{short_name} (from line {offset + 1})')
        else:
            file_parts.append(short_name)

    if len(file_requests) > 5:
        file_parts.append(f'...and {len(file_requests) - 5} more')

    if file_parts:
        elements.append(as_marked_list(*file_parts, marker='• '))

    if close_all_others:
        elements.append(Italic('(closing other files)'))

    return as_line(*elements, sep='\n').as_kwargs()


def _format_grep_files(args_obj: dict[str, Any]) -> dict[str, Any]:
    """Format grep_files tool call."""
    pattern = args_obj.get('pattern', '')
    include = args_obj.get('include', '')
    context_lines = args_obj.get('context_lines')
    offset = args_obj.get('offset')

    elements: list[Any] = [
        Italic('🔍 Searching in files...'),
        as_key_value('Pattern', f'"{pattern}"'),
    ]

    parts = []
    if include:
        parts.append(f'filter: {include}')
    if context_lines:
        parts.append(f'{context_lines} context lines')
    if offset:
        parts.append(f'starting from match #{offset + 1}')

    if parts:
        elements.append(as_marked_list(*parts, marker='• '))

    return as_line(*elements, sep='\n').as_kwargs()


def _format_semantic_search_files(args_obj: dict[str, Any]) -> dict[str, Any]:
    """Format semantic_search_files tool call."""
    query = args_obj.get('query', '')
    limit = args_obj.get('limit')

    elements: list[Any] = [
        Italic('🔍 Searching by meaning...'),
        as_key_value('Query', f'"{query}"'),
    ]

    if limit:
        elements.append(Text(f'top {limit} results'))

    return as_line(*elements, sep='\n').as_kwargs()


def _format_schedule_message(args_obj: dict[str, Any]) -> dict[str, Any]:
    """Format schedule_message tool call."""

    message_to_self = args_obj.get('message_to_self', '')
    delay_seconds = args_obj.get('delay_seconds')
    schedule_at = args_obj.get('schedule_at', '')

    elements: list[Any] = [Italic('⏱️ Setting self activation...')]

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

        elements.append(Text(Bold('When: '), f'in {time_str}'))
    elif schedule_at:
        formatted_time = _format_datetime(schedule_at)
        elements.append(Text(Bold('When: '), formatted_time))

    elements.append(as_key_value('Message', f'"{message_to_self}"'))

    return as_line(*elements, sep='\n').as_kwargs()


def _format_notify_via_telegram(args_obj: dict[str, Any]) -> dict[str, Any]:
    """Format notify_via_telegram tool call."""
    owner_only = args_obj.get('owner_only', False)
    if owner_only:
        return Italic('📲 Sending message to owner...').as_kwargs()
    return Italic('📲 Sending message to Telegram...').as_kwargs()


def _format_web_search(args_obj: dict[str, Any]) -> dict[str, Any]:
    query = args_obj.get('query', '')
    num_results = args_obj.get('num_results', '')
    category = args_obj.get('category', '')
    include_text = args_obj.get('include_text', False)
    include_domains = args_obj.get('include_domains', [])
    exclude_domains = args_obj.get('exclude_domains', [])
    start_published_date = args_obj.get('start_published_date', '')
    end_published_date = args_obj.get('end_published_date', '')
    user_location = args_obj.get('user_location', '')

    parts = []

    if num_results:
        parts.append(f'top {num_results} results')
    if category:
        parts.append(f'category: {category}')

    if include_domains:
        domains_str = ', '.join(include_domains)
        parts.append(f'limited to [{domains_str}]')
    if exclude_domains:
        domains_str = ', '.join(exclude_domains)
        parts.append(f'excluding [{domains_str}]')
    if include_text:
        parts.append('retrieving full page content')
    if start_published_date and end_published_date:
        start = _format_datetime(start_published_date)
        end = _format_datetime(end_published_date)
        parts.append(f'published between {start} and {end}')
    elif start_published_date:
        start = _format_datetime(start_published_date)
        parts.append(f'published after {start}')
    elif end_published_date:
        end = _format_datetime(end_published_date)
        parts.append(f'published before {end}')

    if user_location:
        parts.append(f'localized for {user_location} users')

    elements = [Italic('🔍 Let me search for this...'), as_key_value('Query', f'"{query}"')]
    if parts:
        elements.append(as_marked_list(*parts, marker='• '))

    return as_line(*elements, sep='\n').as_kwargs()


def _format_fetch_webpage(args_obj: dict[str, Any]) -> dict[str, Any]:
    url = args_obj.get('url', '')
    return as_line(
        *(
            Italic('🌐 Fetching webpage...'),
            Text(Italic('Retrieving content from '), Url(url)),
        ),
        sep='\n',
    ).as_kwargs()


def _format_archival_memory_insert(args_obj: dict[str, Any]) -> str:
    """Format archival_memory_insert tool call."""
    content_text = args_obj.get('content', '')
    tags = args_obj.get('tags', [])

    parts = ['*💾 Storing in archival memory...*\n']

    if tags:
        formatted_tags = ', '.join(tags)
        parts.append(f'**Tags:** {formatted_tags}\n')

    parts.append(f'**Content:**\n{content_text}')

    return ''.join(parts)


def _format_archival_memory_search(args_obj: dict[str, Any]) -> dict[str, Any]:
    """Format archival_memory_search tool call."""
    query = args_obj.get('query', '')
    start_datetime = args_obj.get('start_datetime', '')
    end_datetime = args_obj.get('end_datetime', '')
    tags = args_obj.get('tags', [])
    tag_match_mode = args_obj.get('tag_match_mode', '')
    top_k = args_obj.get('top_k')

    parts = []
    if top_k:
        parts.append(f'top {top_k} results')

    if start_datetime and end_datetime:
        start = _format_datetime(start_datetime)
        end = _format_datetime(end_datetime)
        parts.append(f'between {start} and {end}')
    elif start_datetime:
        start = _format_datetime(start_datetime)
        parts.append(f'after {start}')
    elif end_datetime:
        end = _format_datetime(end_datetime)
        parts.append(f'before {end}')

    if tags:
        formatted_tags = ', '.join(tags)
        tag_mode = f' ({tag_match_mode})' if tag_match_mode else ''
        parts.append(f'tags: {formatted_tags}{tag_mode}')

    elements = [
        Italic('🔍 Searching archival memory...'),
        as_key_value('Query', f'"{query}"'),
    ]
    if parts:
        elements.append(as_marked_list(*parts, marker='• '))

    return as_line(*elements, sep='\n').as_kwargs()


def _format_memory_insert(args_obj: dict[str, Any], legacy: bool = False) -> dict[str, Any]:
    """Format memory_insert tool call."""
    insert_text = args_obj.get('new_str' if legacy else 'insert_text', '')
    path = args_obj.get('path', '')

    return as_line(
        *(
            Italic('📝 Updating memory block...'),
            Text(
                as_key_value(
                    'Path',
                    path,
                ),
                '\n',
            ),
            Text(insert_text),
        ),
        sep='\n',
    ).as_kwargs()


def _format_memory_replace(args_obj: dict[str, Any]) -> str:
    """Format memory_replace tool call."""
    path = args_obj.get('path', '')
    old_string = args_obj.get('old_string', '')
    new_string = args_obj.get('new_string', '')

    diff = _get_diff_text(old_string, new_string)
    parts = ['*🔧 Modifying memory block...*\n']

    if path:
        parts.append(f'**Path:** {path}\n')

    parts.append(f'```diff\n{diff}```')

    return ''.join(parts)


def _format_memory_rename(args_obj: dict[str, Any]) -> dict[str, Any]:
    description = args_obj.get('description', '')
    path = args_obj.get('path', '')
    new_path = args_obj.get('new_path', '')
    old_path = args_obj.get('old_path', '')

    if description and path:
        return as_line(
            *(
                Italic('🏷️ Updating memory description...'),
                as_key_value('Path', path),
                as_key_value('New description', f'"{description}"'),
            ),
            sep='\n',
        ).as_kwargs()
    return as_line(
        *(
            Italic('📂 Renaming memory block...'),
            as_key_value('From', old_path),
            as_key_value('To', new_path),
        ),
        sep='\n',
    ).as_kwargs()


def _format_memory_delete(args_obj: dict[str, Any]) -> dict[str, Any]:
    path = args_obj.get('path', '')
    return as_line(
        *(
            Italic('🧹 Removing a memory block...'),
            Text('Deleting ', Bold(f'"{path}"'), ' permanently.'),
        ),
        sep='\n',
    ).as_kwargs()


def _format_memory_create(args_obj: dict[str, Any]) -> str:
    """Format memory create tool call.

    Handles two scenarios:
    1. Creating memory block with initial content (has 'file_text')
    2. Creating empty memory block (no 'file_text')
    """
    path = args_obj.get('path', '')
    description = args_obj.get('description', '')
    file_text = args_obj.get('file_text', '')

    parts = ['*📝 Creating new memory block...*\n', f'**Path:** {path}\n']

    if description:
        parts.append(f'**Description:** "{description}"\n')

    if file_text:
        parts.append(f'**Initial content:**\n{file_text}')

    return ''.join(parts)


def _format_memory(args_obj: dict[str, Any]) -> dict[str, Any] | str | None:
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
    code = args_obj.get('code', '')
    language = args_obj.get('language', 'python')

    parts = ['*⚙️ Executing code...*\n', f'**Language:** {language}\n']
    parts.append(f'```{language}\n{code}\n```')

    return ''.join(parts)


def _format_generic_tool(tool_name: str, args_obj: dict[str, Any]) -> str:
    """Format generic tool call with JSON arguments."""
    formatted_args = json.dumps(args_obj, indent=2)

    parts = ['*🔧 Using tool...*\n', f'**Tool:** {tool_name}\n']
    parts.append(f'**Arguments:**\n```json\n{formatted_args}\n```')

    return ''.join(parts)


# =============================================================================
# Message Sending
# =============================================================================
async def _send_error_message(message: Message, reason: Exception, content: str) -> None:
    """Send formatted error message to user and log the reason.

    Args:
        message: Original message from user
        reason: Error description to log
    """
    LOGGER.warning('Failed to send message: %s\nContent: %s', reason, content)
    LOGGER.debug('Full content: %s', content)

    await message.answer(**Text('❌ Something went wrong').as_kwargs())


async def send_markdown_message(message: Message, content: str) -> None:
    """Send markdown message, converting to Telegram entities.

    Args:
        message: Telegram message to reply to
        content: Standard Markdown content

    Process:
        1. Convert markdown to Telegram entities (auto-splits if > 4096 chars)
        2. Send each chunk as separate message
    """
    # markdown_to_telegram returns list of chunks
    # Automatically splits long text at block boundaries (never mid-word)
    chunks = markdown_to_telegram(content)

    # Send each chunk as separate message
    for text, entities in chunks:
        await message.answer(text, entities=entities)


async def send_reasoning_message(message: Message, reasoning_text: str) -> None:
    """Send reasoning message with expandable blockquote.

    Header stays visible, content is wrapped in expandable_blockquote.
    Code blocks (```) are stripped (pre entities break blockquote).

    Args:
        message: Telegram message to reply to
        reasoning_text: Raw reasoning content
    """
    chunks = merge_with_entity(
        header=Italic('Agent reasoning:'),
        content=reasoning_text.replace('```', ''),
        entity_type='expandable_blockquote',
    )
    for text, entities in chunks:
        await message.answer(text, entities=entities)


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
        if message_type == 'reasoning_message':
            reasoning_text = getattr(event, 'reasoning', '')
            if reasoning_text:
                try:
                    await send_reasoning_message(self.telegram_message, reasoning_text)
                except Exception as e:
                    await _send_error_message(self.telegram_message, e, reasoning_text)
            return

        if message_type == 'tool_call_message':
            formatted_content = _format_tool_call_message(event)
            if formatted_content:
                try:
                    # Handle both dict (aiogram formatting) and str (markdown) formats
                    if isinstance(formatted_content, str):
                        await send_markdown_message(
                            self.telegram_message, formatted_content
                        )
                    else:
                        await self.telegram_message.answer(**formatted_content)
                except Exception as e:
                    await _send_error_message(
                        self.telegram_message, e, str(formatted_content)
                    )
            return

        # System alerts (informational messages from Letta)
        if message_type == 'system_message':
            alert_message = getattr(event, 'message', '')
            if alert_message and alert_message.strip():
                alert_content = Italic(f'info: {alert_message}').as_kwargs()
                await self.telegram_message.answer(**alert_content)
            return

        # Phase 3: Final response (clears ping state)
        if message_type == 'assistant_message':
            raw_content = getattr(event, 'content', '').strip()
            if raw_content:
                await send_markdown_message(self.telegram_message, raw_content)
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

    def _clear_ping_state(self) -> None:
        """Reset ping tracking state."""
        self.ping_count = 0
        self.ping_message = None
