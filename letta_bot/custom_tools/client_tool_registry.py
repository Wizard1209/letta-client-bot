"""Client-side tool registry: schema collection, dispatch, and result types.

Bridges Letta approval requests with Telegram output and Letta resume messages.
"""

import base64
from dataclasses import dataclass, field
import json
import logging
from typing import Any, Literal

from aiogram import Bot
from aiogram.types import BufferedInputFile

from letta_bot.custom_tools.generate_image import (
    GENERATE_IMAGE_TOOL,
    execute_generate_image,
)
from letta_client.types.agents.message_stream_params import ClientTool

LOGGER = logging.getLogger(__name__)


@dataclass
class TelegramPhoto:
    photo: BufferedInputFile
    caption: str | None = None


@dataclass
class TelegramText:
    text: str


TelegramOutput = TelegramPhoto | TelegramText


@dataclass
class ClientToolResult:
    """Two parallel outputs: Letta resume messages + Telegram user output."""

    letta_messages: list[dict[str, Any]] = field(default_factory=list)
    telegram_output: TelegramOutput | None = None


CLIENT_TOOLS: list[ClientTool] = [
    GENERATE_IMAGE_TOOL,
]


def _build_approval(
    tool_call_id: str,
    tool_return: str,
    status: Literal['success', 'error'] = 'success',
) -> dict[str, Any]:
    """Build an approval message dict for Letta."""
    return {
        'type': 'approval',
        'approvals': [
            {
                'type': 'tool',
                'tool_call_id': tool_call_id,
                'tool_return': tool_return,
                'status': status,
            }
        ],
    }


async def execute_client_tool(
    bot: Bot,
    tool_call_id: str,
    tool_name: str,
    arguments: str,
) -> ClientToolResult:
    """Execute a client-side tool and build both Letta + Telegram outputs."""
    args_obj = json.loads(arguments)

    if tool_name == 'generate_image':
        return await _handle_generate_image(bot, tool_call_id, args_obj)

    LOGGER.warning('Unknown client tool: %s', tool_name)
    return ClientToolResult(
        letta_messages=[_build_approval(
            tool_call_id, f'Error: Unknown client tool: {tool_name}', 'error',
        )],
        telegram_output=TelegramText(text=f'Tool error: Unknown tool {tool_name}'),
    )


async def _handle_generate_image(
    bot: Bot,
    tool_call_id: str,
    args_obj: dict[str, Any],
) -> ClientToolResult:
    """Handle generate_image tool execution."""
    prompt = args_obj.get('prompt', '')
    reference_images = args_obj.get('reference_images')
    model = args_obj.get('model')

    b64_data, media_type, text_summary = await execute_generate_image(
        bot, prompt, reference_images, model
    )

    image_msg: dict[str, Any] = {
        'role': 'user',
        'content': [
            {
                'type': 'image',
                'source': {
                    'type': 'base64',
                    'media_type': media_type,
                    'data': b64_data,
                },
            },
            {
                'type': 'text',
                'text': (
                    '<additional-tool-result tool="generate_image">'
                    '<generated_image file_id="%PENDING%">'
                    'Image generation result attached'
                    '</generated_image>'
                    '</additional-tool-result>'
                ),
            },
        ],
    }

    image_bytes = base64.b64decode(b64_data)

    return ClientToolResult(
        letta_messages=[
            _build_approval(tool_call_id, text_summary),
            image_msg,
        ],
        telegram_output=TelegramPhoto(
            photo=BufferedInputFile(image_bytes, filename='generated.png'),
            caption=None,
        ),
    )
