from pathlib import Path
from typing import Literal

from pydantic import ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    if Path('.env').exists():
        model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8')
    else:
        model_config = SettingsConfigDict()

    telegram_bot_token: str

    webhook_host: str
    webhook_path: str = ''

    # Webhook listener
    backend_host: str = '0.0.0.0'
    backend_port: int = 80

    admin_ids: list[int] | None = None

    letta_project_id: str
    letta_api_key: str

    # Scheduler configuration for schedule_message tool
    scheduler_url: str | None = None
    scheduler_api_key: str | None = None

    # Info notes directory (optional)
    info_dir: Path = Path.cwd() / 'notes'

    # Logging level
    logging_level: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] = 'INFO'

    # Error notifications to admins (can be spammy, off by default)
    notify_admins_on_error: bool = False

    # OpenAI config for audio transcription (optional, voice disabled if not set)
    openai_api_key: str | None = None
    whisper_model: str = 'gpt-4o-mini-transcribe'

    # ElevenLabs config for audio transcription (optional)
    elevenlabs_api_key: str | None = None
    elevenlabs_stt_model: str = 'scribe_v2'

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

    @field_validator('info_dir', mode='before')
    def validate_info_dir(cls, notes_full_path: str | Path | None) -> Path:
        if not notes_full_path:
            notes_full_path = Path.cwd() / 'notes'
        if isinstance(notes_full_path, str):
            notes_full_path = Path(notes_full_path)
        if not notes_full_path.exists():
            raise ValidationError('Bot info directory doesnt exist')
        return notes_full_path

    @property
    def webhook_url(self) -> str:
        return f'https://{self.webhook_host}{self.webhook_path}'


CONFIG = Config()
