from pathlib import Path

from pydantic import ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    if Path('.env').exists():
        model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8')
    else:
        model_config = SettingsConfigDict()

    bot_token: str

    webhook_host: str
    webhook_path: str = ''

    backend_host: str = '0.0.0.0'
    backend_port: int = 80

    admin_ids: list[int] | None = None

    @field_validator('admin_ids', mode='before')
    def split_ids(cls, ids: int | str | None) -> list[int]:
        if not ids:
            return []
        elif isinstance(ids, int):
            return [ids]
        elif isinstance(ids, str):
            return list(map(int, ids.split(',')))
        else:
            raise ValidationError(
                'admin_ids must be an int or comma separated list of ints, instead of %s',
                type(ids),
            )

    @property
    def webhook_url(self) -> str:
        return f'https://{self.webhook_host}{self.webhook_path}'
