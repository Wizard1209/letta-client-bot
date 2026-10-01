"""Sunset mode: the bot answers everything with one fixed text and talks to nothing else.

Enabled by `SUNSET_MESSAGE` in the environment. The message is Markdown, the dialect the
agents answered in, so a `@handle` or a link renders the usual way.
"""

from aiogram import Router
from aiogram.types import Message

from letta_bot.response_handler import send_markdown_message


def sunset_router(text: str) -> Router:
    router = Router(name='sunset')

    @router.message()
    async def answer(message: Message) -> None:
        # channel posts and service messages have nobody to answer
        if not message.from_user:
            return
        await send_markdown_message(message, text)

    return router
