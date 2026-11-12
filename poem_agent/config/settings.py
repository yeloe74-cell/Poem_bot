from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigurationError(ValueError):
    """Raised when required environment configuration is invalid."""


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value not in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
        raise ConfigurationError(f"{name} must be a boolean")
    return value in {"true", "1", "yes", "on"}


def _int(name: str, default: int, minimum: int, maximum: int | None = None) -> int:
    raw = os.getenv(name)
    try:
        value = default if raw is None else int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if value < minimum or (maximum is not None and value > maximum):
        raise ConfigurationError(f"{name} is outside allowed bounds")
    return value


@dataclass(frozen=True, slots=True)
class AppSettings:
    name: str
    environment: str
    timezone: str
    data_dir: Path
    log_level: str


@dataclass(frozen=True, slots=True)
class TelegramSettings:
    bot_token: str
    owner_ids: tuple[int, ...]
    target_channel: str
    polling_timeout: int = 30


@dataclass(frozen=True, slots=True)
class AISettings:
    api_key: str = ""
    model: str = ""
    base_url: str = "https://openrouter.ai/api/v1"
    timeout: int = 30


@dataclass(frozen=True, slots=True)
class Settings:
    app: AppSettings
    telegram: TelegramSettings
    ai: AISettings
    approval_required: bool = True

    @property
    def database_path(self) -> Path:
        return self.app.data_dir / "poembot.sqlite3"

    def prepare(self) -> None:
        self.app.data_dir.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    data_dir = Path(os.getenv("DATA_DIR", "./data")).expanduser().resolve()
    raw_owners = os.getenv("OWNER_IDS", "").split(",")
    try:
        owners = tuple(dict.fromkeys(int(item.strip()) for item in raw_owners if item.strip()))
    except ValueError as exc:
        raise ConfigurationError("OWNER_IDS must be comma-separated Telegram numeric IDs") from exc
    if not owners or any(owner <= 0 for owner in owners):
        raise ConfigurationError("Set at least one valid positive OWNER_IDS value")

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    target = os.getenv("TARGET_CHANNEL", "").strip()
    if not token:
        raise ConfigurationError("TELEGRAM_BOT_TOKEN is required")
    if not target:
        raise ConfigurationError("TARGET_CHANNEL is required (for example @your_channel)")
    approval_required = _bool("APPROVAL_REQUIRED", True)
    if not approval_required:
        raise ConfigurationError("APPROVAL_REQUIRED=false is unsafe and is not supported")

    app = AppSettings(
        name=os.getenv("APP_NAME", "PoemBot"),
        environment=os.getenv("APP_ENV", "production"),
        timezone=os.getenv("APP_TIMEZONE", "Asia/Yangon"),
        data_dir=data_dir,
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )
    if app.log_level not in logging_levels():
        raise ConfigurationError("LOG_LEVEL must be a standard Python logging level")
    telegram = TelegramSettings(
        bot_token=token,
        owner_ids=owners,
        target_channel=target,
        polling_timeout=_int("TELEGRAM_POLLING_TIMEOUT", 30, 5, 120),
    )
    ai = AISettings(
        api_key=os.getenv("AI_API_KEY", "").strip(),
        model=os.getenv("AI_MODEL", "").strip(),
        base_url=os.getenv("AI_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/"),
        timeout=_int("AI_TIMEOUT", 30, 5, 180),
    )
    return Settings(app=app, telegram=telegram, ai=ai)


def logging_levels() -> set[str]:
    return {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
