"""Client-side tools package.

Re-exports public API from ``registry`` module. Tool modules in this
package register themselves at import time — just add an import below
to activate a new tool.

Adding a new client tool:
    1. Create ``letta_bot/client_tools/my_tool.py``
    2. In that file, import ``registry`` and call ``registry.register(...)``
    3. Add ``from letta_bot.client_tools import my_tool as my_tool  # noqa: F401``
       to this file
"""

from letta_bot.client_tools.registry import (
    FILE_ID_PLACEHOLDER,
    ClientToolError,
    ClientToolResult,
    ClientToolSchema,
    LettaMessage,
    TelegramOutput,
    TelegramPhoto,
    extract_tool_calls,
    registry,
    resolve_approval,
    send_telegram_output,
)

__all__ = [
    'FILE_ID_PLACEHOLDER',
    'ClientToolError',
    'ClientToolResult',
    'ClientToolSchema',
    'LettaMessage',
    'TelegramOutput',
    'TelegramPhoto',
    'extract_tool_calls',
    'registry',
    'resolve_approval',
    'send_telegram_output',
]

# ---- Tool registration imports ----
# Each module registers its tools when imported.
# Add new tool modules here:
from letta_bot.client_tools import generate_image as generate_image  # noqa: F401, E402
