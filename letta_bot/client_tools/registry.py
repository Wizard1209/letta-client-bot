"""Client-side tool registry for Letta agent integration.

Client-side tools are tools that the agent can call, but are executed by the bot
(client) rather than the Letta server. This enables agent-driven Telegram actions
like sending photos, stickers, and managing chat interactions.

Flow:
1. Tools registered at import time via register_tool()
2. Schemas passed to Letta API via client_tools parameter
3. Agent calls tool -> ApprovalRequestMessage in stream
4. Bot executes tool via execute_client_tool() -> returns result to Letta
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import logging
from typing import Any, Literal

from aiogram import Bot
from aiogram.types import Message
from letta_client.types.agents.message_create_params import ClientTool

LOGGER = logging.getLogger(__name__)


# =============================================================================
# Result Types
# =============================================================================


@dataclass
class TelegramPhoto:
    """Photo to send to the user."""

    data: bytes | str  # bytes data or Telegram file_id
    caption: str | None = None


TelegramResult = TelegramPhoto | None


@dataclass
class ClientToolResult:
    """Result of client tool execution."""

    tool_return: str  # string for Letta (JSON or text)
    status: Literal['success', 'error']
    telegram_result: TelegramResult = None


# =============================================================================
# Registry
# =============================================================================


ClientToolExecutor = Callable[..., Awaitable[ClientToolResult]]

_REGISTRY: dict[str, ClientToolExecutor] = {}
CLIENT_TOOL_SCHEMAS: list[ClientTool] = []

PENDING_PLACEHOLDER = '%PENDING%'


def register_tool(
    name: str,
    executor: ClientToolExecutor,
    schema: ClientTool,
) -> None:
    """Register a client-side tool."""
    _REGISTRY[name] = executor
    CLIENT_TOOL_SCHEMAS.append(schema)


async def execute_client_tool(
    tool_name: str,
    arguments: dict[str, Any],
    bot: Bot,
    message: Message,
) -> ClientToolResult:
    """Dispatch tool call by name. Returns error result for unknown tools."""
    executor = _REGISTRY.get(tool_name)
    if executor is None:
        return ClientToolResult(
            tool_return=f'Unknown client tool: {tool_name}',
            status='error',
        )
    try:
        return await executor(bot=bot, message=message, **arguments)
    except TypeError as exc:
        return ClientToolResult(
            tool_return=f'Invalid arguments for {tool_name}: {exc}',
            status='error',
        )
