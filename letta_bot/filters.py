import logging
from typing import Final

from aiogram import F
from aiogram.filters import Filter
from aiogram.filters.magic_data import MagicData

from letta_bot.config import CONFIG

LOGGER = logging.getLogger(__name__)

AdminOnlyFilter: Final[Filter] = MagicData(F.event_from_user.id.in_(CONFIG.admin_ids))  # type: ignore
