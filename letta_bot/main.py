import argparse
import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart
from aiogram.types import Message, User
from aiogram.utils.formatting import Text
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from gel import AsyncIOExecutor as GelClient, create_async_client

from letta_bot.agent import get_general_agent_router
from letta_bot.auth import get_auth_router
from letta_bot.config import CONFIG
from letta_bot.info import get_info_router, load_info_command_content
from letta_bot.queries.is_registered_async_edgeql import (
    is_registered as is_registered_query,
)
from letta_bot.queries.register_user_async_edgeql import (
    register_user as register_user_query,
)

LOGGER = logging.getLogger(__name__)


async def register_user(user: User, gel_client: GelClient) -> None:
    is_registered = await is_registered_query(gel_client, telegram_id=user.id)
    if is_registered:
        return
    # TODO: Add user update logic
    user_model = {
        'telegram_id': user.id,
        'is_bot': user.is_bot,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'username': user.username,
        'language_code': user.language_code,
    }
    id_ = (await register_user_query(gel_client, **user_model)).telegram_id
    LOGGER.info(f'New user registered: {id_}')


def register_start_command(dp: Dispatcher, gel_client: GelClient) -> None:
    @dp.message(CommandStart())
    async def welcome_handler(message: Message) -> None:
        """Display welcome information."""
        if not message.from_user:
            await message.answer(Text("Can't identify user").as_markdown())
            LOGGER.warning('User invoked start command cant be identified')
            return
        await register_user(message.from_user, gel_client)
        content = load_info_command_content('welcome')
        await message.answer(content)


def setup_bot_handlers(
    dp: Dispatcher, bot: Bot, gel_client: GelClient, args: argparse.Namespace
) -> None:
    """Register all common bot handlers (commands, routers, etc.)."""
    # Register /start command
    register_start_command(dp, gel_client)
    # Privacy, security, help, about, contact commands
    dp.include_router(get_info_router())
    # Admin authorization handlers
    dp.include_router(get_auth_router(bot, gel_client))
    # Agent messages and management commands
    # NOTE: all other messages fall to the agent
    dp.include_router(get_general_agent_router(bot, gel_client))


async def on_startup(bot: Bot) -> None:
    LOGGER.info(f'Registering webhook: {CONFIG.webhook_url}')
    await bot.set_webhook(f'{CONFIG.webhook_url}')


def run_webhook(bot: Bot, args: argparse.Namespace) -> None:
    dp = Dispatcher()
    gel_client = create_async_client()

    # Register all common bot handlers
    setup_bot_handlers(dp, bot, gel_client, args)

    # Webhook-specific setup
    dp.startup.register(on_startup)  # register webhook
    dp.shutdown.register(bot.delete_webhook)
    app = web.Application()
    webhook_requests_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_requests_handler.register(app, path=CONFIG.webhook_path)
    setup_application(app, dp, bot=bot)
    web.run_app(app, host=CONFIG.backend_host, port=CONFIG.backend_port)


async def run_polling(bot: Bot, args: argparse.Namespace) -> None:
    dp = Dispatcher()
    gel_client = create_async_client()

    # Register all common bot handlers
    setup_bot_handlers(dp, bot, gel_client, args)

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
