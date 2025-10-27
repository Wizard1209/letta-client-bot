import argparse

from aiogram import Bot, Dispatcher
from gel import AsyncIOExecutor as GelClient

from letta_client import AsyncLetta as LettaClient

client = LettaClient()


def request_resource():
    # get templates list

def register_request_resource():
    # create authentification request in the table
    # notify admin about new request

def init_agent_handlers(dp: Dispatcher, bot: Bot,
                        gel_client: GelClient, args: argparse.Namespace):
    ...
