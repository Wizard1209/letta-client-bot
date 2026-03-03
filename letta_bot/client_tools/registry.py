"""Client-side tool infrastructure for Letta agent interactions.

Provides a registry for tools that the agent can request the bot to execute
locally (e.g., generate images, send photos). The registry manages tool
schemas and dispatches execution to registered handlers.

The approval loop helpers (resolve, error builders) live here so that
``agent.py`` only orchestrates the stream — all tool-specific logic is
contained in this module.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
import json
import logging

from aiogram.types import BufferedInputFile, Message
from aiogram.utils.formatting import Text
from letta_client.types.agents import ApprovalRequestMessage, ToolCall
from letta_client.types.agents.message_stream_params import ClientTool

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class TelegramPhoto:
    """Photo output to send to Telegram."""

    file: BufferedInputFile
    caption: str | None = None


type TelegramOutput = TelegramPhoto | str
"""Union type for outputs sent directly to Telegram chat."""

# Messages exchanged with the Letta API during the approval loop.
type LettaMessage = dict[str, object]

FILE_ID_PLACEHOLDER = '{file_id}'
"""Placeholder in ``tool_return`` that gets replaced with actual Telegram file_id."""

ToolExecutor = Callable[..., Awaitable['ClientToolResult']]
"""Async callable that executes a client-side tool."""


@dataclass
class ClientToolResult:
    """Result of a client-side tool execution.

    Executors return only the result string — the approval protocol
    (``tool_call_id``, ``status``) is handled by :func:`resolve_approval`.

    Attributes:
        tool_return: Result string to send back to the agent.
        telegram_output: Optional output to send directly to Telegram chat.
        extra_messages: Additional messages to send to the agent after the
            tool approval (e.g., base64 image for visual feedback).
    """

    tool_return: str
    telegram_output: TelegramOutput | None = None
    extra_messages: list[LettaMessage] = field(default_factory=list)


@dataclass(frozen=True)
class ClientToolSchema:
    """Schema definition for a client-side tool.

    Attributes:
        name: Tool function name (must match what agent calls).
        description: Human-readable description of what the tool does.
        parameters: JSON Schema for the function parameters.
    """

    name: str
    description: str
    parameters: dict[str, object]

    def to_client_tool(self) -> ClientTool:
        """Convert to SDK ``ClientTool`` TypedDict for Letta API."""
        return ClientTool(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
        )


@dataclass(frozen=True)
class _ToolEntry:
    """Internal registry entry combining executor and schema."""

    executor: ToolExecutor
    schema: ClientToolSchema


class ClientToolRegistry:
    """Registry for client-side tools.

    Manages tool schemas and dispatches execution to registered handlers.
    """

    def __init__(self) -> None:
        self._tools: dict[str, _ToolEntry] = {}

    def register(
        self,
        name: str,
        executor: ToolExecutor,
        schema: ClientToolSchema,
    ) -> None:
        """Register a client-side tool.

        Args:
            name: Tool name (must be unique).
            executor: Async function that executes the tool.
            schema: Tool schema for Letta API.

        Raises:
            ValueError: If a tool with the same name is already registered.
        """
        if name in self._tools:
            msg = f'Client tool already registered: {name}'
            raise ValueError(msg)
        self._tools[name] = _ToolEntry(executor=executor, schema=schema)

    def get_schemas(self) -> list[ClientTool]:
        """Get all registered tool schemas for Letta API ``client_tools`` param."""
        return [entry.schema.to_client_tool() for entry in self._tools.values()]

    def is_registered(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    async def dispatch(
        self, name: str, *, message: Message, **kwargs: object
    ) -> ClientToolResult:
        """Execute a registered tool.

        Args:
            name: Tool name to execute.
            message: Telegram message for context (bot access, chat info).
            **kwargs: Arguments to pass to the tool executor.

        Returns:
            ClientToolResult with messages for agent and optional Telegram output.

        Raises:
            KeyError: If tool is not registered (via dict lookup).
            TypeError: If arguments don't match executor signature (propagated).
        """
        return await self._tools[name].executor(message=message, **kwargs)


registry = ClientToolRegistry()
"""Global client tool registry instance."""


# =============================================================================
# Approval Loop Helpers
# =============================================================================


def extract_tool_calls(approval_request: ApprovalRequestMessage) -> list[ToolCall]:
    """Extract tool calls from an approval request message.

    Checks ``tool_calls`` list first, falls back to single ``tool_call``.
    """
    if approval_request.tool_calls and isinstance(approval_request.tool_calls, list):
        return approval_request.tool_calls
    return [approval_request.tool_call]  # type: ignore[list-item]


def _patch_file_id_placeholder(messages: list[LettaMessage], file_id: str) -> None:
    """Replace FILE_ID_PLACEHOLDER with actual file_id in messages (in-place)."""
    for msg in messages:
        content = msg.get('content')
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            text = part.get('text')
            if isinstance(text, str) and FILE_ID_PLACEHOLDER in text:
                part['text'] = text.replace(FILE_ID_PLACEHOLDER, file_id)


async def send_telegram_output(message: Message, output: TelegramOutput) -> Message:
    """Send a client-tool output to Telegram."""
    if isinstance(output, TelegramPhoto):
        return await message.answer_photo(output.file, caption=output.caption)
    return await message.answer(**Text(output).as_kwargs())


async def resolve_approval(
    approval_request: ApprovalRequestMessage,
    message: Message,
) -> list[LettaMessage]:
    """Process an approval request from the agent.

    For each tool call:
    - If registered in the client-tool registry: execute and collect results.
    - If not registered (server-side tool): deny with reason.

    All tool approvals are grouped into a single approval message with
    ``approval_request_id`` so Letta can match the response to the request.

    Returns:
        List of messages to send back to the agent on the next stream call.
    """
    tool_calls = extract_tool_calls(approval_request)
    approvals: list[dict[str, object]] = []
    extra_messages: list[LettaMessage] = []

    for tc in tool_calls:
        if not registry.is_registered(tc.name):
            approvals.append(
                {
                    'type': 'approval',
                    'tool_call_id': tc.tool_call_id,
                    'approve': False,
                    'reason': 'Server-side tool approval is not supported',
                }
            )
            continue

        try:
            args = json.loads(tc.arguments) if tc.arguments else {}
            result = await registry.dispatch(tc.name, message=message, **args)

            tool_return = result.tool_return

            # Send Telegram output and substitute file_id placeholder
            if result.telegram_output is not None:
                sent_msg = await send_telegram_output(message, result.telegram_output)
                if isinstance(result.telegram_output, TelegramPhoto) and sent_msg.photo:
                    actual_file_id = sent_msg.photo[-1].file_id
                    tool_return = tool_return.replace(FILE_ID_PLACEHOLDER, actual_file_id)
                    _patch_file_id_placeholder(result.extra_messages, actual_file_id)

            approvals.append(
                {
                    'type': 'tool',
                    'tool_call_id': tc.tool_call_id,
                    'tool_return': tool_return,
                    'status': 'success',
                }
            )
            extra_messages.extend(result.extra_messages)

        except Exception:
            LOGGER.exception('Client tool %s failed, sending error approval', tc.name)
            approvals.append(
                {
                    'type': 'tool',
                    'tool_call_id': tc.tool_call_id,
                    'tool_return': 'Tool execution failed',
                    'status': 'error',
                }
            )
            await message.answer(**Text(f'❌ Tool "{tc.name}" failed').as_kwargs())

    # Single approval message with all tool results
    approval_msg: LettaMessage = {
        'type': 'approval',
        'approval_request_id': approval_request.id,
        'approvals': approvals,
    }

    return [approval_msg, *extra_messages]
