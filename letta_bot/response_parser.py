"""Agent response parsing and formatting for Telegram messages.

This module handles parsing of Letta streaming responses and converts them
into formatted Text objects for display in Telegram.
"""

import json
import logging
from typing import Any

from aiogram.utils.formatting import BlockQuote, Bold, Code, Italic, Text
from letta_client.agents.messages.types.letta_streaming_response import (
    LettaStreamingResponse,
)

LOGGER = logging.getLogger(__name__)


async def process_stream_event(event: LettaStreamingResponse) -> Text | None:
    """Process a single stream event and return formatted Text content.

    Args:
        event: Stream event from Letta API

    Returns:
        Formatted Text object for display, or None if event should be skipped.
    """
    if not hasattr(event, 'message_type'):
        return None

    message_type = event.message_type

    if message_type == 'assistant_message':
        return _format_assistant_message(event)

    elif message_type == 'reasoning_message':
        return _format_reasoning_message(event)

    elif message_type == 'tool_call_message':
        return _format_tool_call_message(event)

    elif message_type == 'ping':
        return Text('⏳Working on it⏳')

    return None


def _format_assistant_message(event: LettaStreamingResponse) -> Text | None:
    """Format assistant message response.

    Args:
        event: Stream event containing assistant message

    Returns:
        Formatted Text object or None if content is empty
    """
    content = getattr(event, 'content', '')
    if content and content.strip():
        return Text(Bold('Agent response:'), '\n\n', content)
    return None


def _format_reasoning_message(event: LettaStreamingResponse) -> Text:
    """Format reasoning message response.

    Args:
        event: Stream event containing reasoning message

    Returns:
        Formatted Text object with reasoning content
    """
    reasoning_text = getattr(event, 'reasoning', '')
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
