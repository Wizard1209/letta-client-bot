import argparse

from aiogram import Bot, Dispatcher
from gel import AsyncIOExecutor as GelClient



def init_auth_handlers(dp: Dispatcher, bot: Bot,
                       gel_client: GelClient, args: argparse.Namespace):
    ...
