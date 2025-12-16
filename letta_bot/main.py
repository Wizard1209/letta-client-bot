import argparse
import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiogram.utils.formatting import Text
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from gel import create_async_client

from letta_bot.agent import agent_commands_router, agent_router
from letta_bot.auth import auth_router
from letta_bot.config import CONFIG
from letta_bot.info import info_router, load_info_command_content
from letta_bot.middlewares import setup_middlewares
from letta_bot.tools import tools_router

LOGGER = logging.getLogger(__name__)


def start_command(dp: Dispatcher) -> None:
    @dp.message(CommandStart())
    async def welcome_handler(message: Message) -> None:
        """Display welcome information."""
        if not message.from_user:
            await message.answer(Text("Can't identify user").as_markdown())
            LOGGER.warning('User invoked start command cant be identified')
            return
        content = load_info_command_content('welcome')
        await message.answer(content)


def setup_bot_handlers(dp: Dispatcher) -> None:
    """Register all common bot handlers (commands, routers, etc.)."""
    # Register /start command
    start_command(dp)
    # Privacy, help, about, contact commands
    dp.include_router(info_router)
    LOGGER.info('Info handlers initialized')
    # Admin authorization handlers
    dp.include_router(auth_router)
    LOGGER.info('Auth handlers initialized')
    # Agent messages and management commands
    # NOTE: all other messages fall to the agent
    agent_commands_router.include_router(tools_router)
    agent_commands_router.include_router(agent_router)
    dp.include_router(agent_commands_router)
    LOGGER.info('Tools handlers initialized')
    LOGGER.info('Agent handlers initialized')


async def on_startup(bot: Bot) -> None:
    LOGGER.info(f'Registering webhook: {CONFIG.webhook_url}')
    await bot.set_webhook(f'{CONFIG.webhook_url}')


def run_webhook(bot: Bot, args: argparse.Namespace) -> None:
    gel_client = create_async_client()
    dp = Dispatcher(gel_client=gel_client)

    setup_middlewares(dp)

    # Register all common bot handlers
    setup_bot_handlers(dp)

    # Webhook-specific setup
    dp.startup.register(on_startup)  # register webhook
    dp.shutdown.register(bot.delete_webhook)
    app = web.Application()
    webhook_requests_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_requests_handler.register(app, path=CONFIG.webhook_path)
    setup_application(app, dp, bot=bot)
    web.run_app(app, host=CONFIG.backend_host, port=CONFIG.backend_port)


async def run_polling(bot: Bot, args: argparse.Namespace) -> None:
    gel_client = create_async_client()
    dp = Dispatcher(gel_client=gel_client)

    setup_middlewares(dp)

    # Register all common bot handlers
    setup_bot_handlers(dp)

    # Polling-specific setup - start polling loop
    await dp.start_polling(bot)


if __name__ == '__main__':
    logging.basicConfig(level=getattr(logging, CONFIG.logging_level), stream=sys.stdout)

    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--polling', action='store_true', help='Enable polling mode.')

    args: argparse.Namespace = parser.parse_args()

    bot = Bot(CONFIG.bot_token, default=DefaultBotProperties(parse_mode='MarkdownV2'))

    if args.polling:
        asyncio.run(run_polling(bot, args))
    else:
        run_webhook(bot, args)
