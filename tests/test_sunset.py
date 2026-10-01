"""Sunset mode answers every message with the fixed text and nothing else."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from aiogram.dispatcher.event.bases import UNHANDLED

from letta_bot.sunset import sunset_router


def test_answers_any_message_with_the_text() -> None:
    router = sunset_router('Бот закрыт, пишите @someone')
    message = MagicMock()
    message.from_user = MagicMock()
    message.answer = AsyncMock()
    result = asyncio.run(router.message.trigger(message))
    assert result is not UNHANDLED
    assert message.answer.await_count == 1
    sent = message.answer.await_args.kwargs.get('text') or message.answer.await_args.args[0]
    assert 'Бот закрыт' in sent


def test_ignores_events_without_a_sender() -> None:
    router = sunset_router('x')
    message = MagicMock()
    message.from_user = None
    message.answer = AsyncMock()
    asyncio.run(router.message.trigger(message))
    message.answer.assert_not_awaited()
