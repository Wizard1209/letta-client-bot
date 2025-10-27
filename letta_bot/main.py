import argparse
import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiogram.utils.markdown import bold
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from gel import AsyncIOExecutor as GelClient, create_async_client

from letta_bot.config import Config
from letta_bot.agent import init_agent_handlers
from letta_bot.auth import init_auth_handlers
from letta_bot.info import init_info_handlers
from letta_bot.queries.is_registered_async_edgeql import (
    is_registered as is_registered_query,
)
from letta_bot.queries.register_user_async_edgeql import (
    register_user as register_user_query,
)

LOGGER = logging.getLogger('application')
CONFIG = Config()  # type: ignore


def init_common_handlers(
    dp: Dispatcher, bot: Bot, gel_client: GelClient, args: argparse.Namespace
) -> None:
    @dp.message(CommandStart())
    async def command_start_handler(message: Message) -> None:
        user = message.from_user
        if not user:
            message.answer("""Can't identify user""")
            return

        is_registered = await is_registered_query(gel_client, telegram_id=user.id)
        LOGGER.info(f'User is registered: {is_registered and is_registered.telegram_id}')
        if not is_registered:
            user_model = {
                'telegram_id': user.id,
                'is_bot': user.is_bot,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'username': user.username,
                'language_code': user.language_code,
            }
            id_ = (await register_user_query(gel_client, **user_model)).telegram_id
        else:
            id_ = is_registered.telegram_id

        greetings = (
            f'Hello, {bold(user.full_name)}\\! Registered with id\\={str(id_)},'
            'telegram id is {user.id}'
        )

        await message.answer(greetings)


async def on_startup(bot: Bot) -> None:
    LOGGER.info(f'Registering webhook: {CONFIG.webhook_url}')
    await bot.set_webhook(f'{CONFIG.webhook_url}')


def main(bot: Bot, args: argparse.Namespace) -> None:
    dp = Dispatcher()
    gel_client = create_async_client()

    init_common_handlers(dp, bot, gel_client, args)
    init_auth_handlers(dp, bot, gel_client, args)
    # agent messages and management commands
    init_agent_handlers(dp, bot, gel_client, args)
    # privacy'n'security note, contacts'n'author note, help
    init_info_handlers(dp, bot, args)

    dp.startup.register(on_startup)  # register webhook
    dp.shutdown.register(bot.delete_webhook)
    app = web.Application()
    webhook_requests_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_requests_handler.register(app, path=CONFIG.webhook_path)
    setup_application(app, dp, bot=bot)
    web.run_app(app, host=CONFIG.backend_host, port=CONFIG.backend_port)


async def polling(bot: Bot, args: argparse.Namespace) -> None:
    dp = Dispatcher()
    gel_client = create_async_client()

    init_common_handlers(dp, bot, gel_client, args)
    init_auth_handlers(dp, bot, gel_client, args)
    init_agent_handlers(dp, bot, gel_client, args)
    init_info_handlers(dp, bot, args)

    await dp.start_polling(bot)


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)

    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--polling', action='store_true', help='Enable polling mode.')
    parser.add_argument(
        '--info-dir',
        type=str,
        default=None,
        help='Directory name under letta_bot/notes/ for info markdown files.',
    )

    args: argparse.Namespace = parser.parse_args()

    bot = Bot(CONFIG.bot_token, default=DefaultBotProperties(parse_mode='MarkdownV2'))

    if args.polling:
        asyncio.run(polling(bot, args))
    else:
        main(bot, args)
