from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class AppSettings:
    name: str = "PoemBot"
    environment: str = "development"
    timezone: str = "Asia/Yangon"
    language: str = "my"
    debug: bool = False
    data_dir: str = "./data"
    log_level: str = "INFO"


@dataclass(frozen=True)
class TelegramSettings:
    bot_token: str = ""
    api_id: int = 0
    api_hash: str = ""
    owner_ids: tuple[int, ...] = ()
    target_channel: str = "@poem_channel"
    bot_enabled: bool = True
    user_client_enabled: bool = False
    session_name: str = "poembot_session"


@dataclass(frozen=True)
class AISettings:
    provider: str = "openrouter"
    api_key: str = ""
    model: str = "openai/gpt-4o-mini"
    base_url: str = "https://openrouter.ai/api/v1"
    temperature: float = 0.4
    max_tokens: int = 3000
    timeout: int = 60
    retries: int = 3


@dataclass(frozen=True)
class DatabaseSettings:
    url: str = "sqlite:///./data/poembot.db"
    echo: bool = False


@dataclass(frozen=True)
class ImageSettings:
    sources: tuple[str, ...] = ("wikimedia",)
    daily_limit: int = 5
    max_file_size_mb: int = 15
    download_timeout: int = 30
    cache_days: int = 7
    directory: str = "./data/images"


@dataclass(frozen=True)
class PostingSettings:
    daily_limit: int = 5
    interval_minutes: int = 30
    draft_expiry_hours: int = 48
    approval_required: bool = True


@dataclass(frozen=True)
class SecuritySettings:
    app_secret: str = "change_me_to_a_secure_random_string_of_at_least_32_chars"
    confirmation_timeout: int = 120
    max_pending_actions: int = 5


@dataclass(frozen=True)
class Settings:
    app: AppSettings
    telegram: TelegramSettings
    ai: AISettings
    database: DatabaseSettings
    images: ImageSettings
    posting: PostingSettings
    security: SecuritySettings


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int = 0) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float = 0.0) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _env_list(name: str, default: Iterable[str] = ()) -> tuple[str, ...]:
    value = os.getenv(name)
    if value is None:
        return tuple(default)
    return tuple(item.strip() for item in value.split(",") if item.strip())


def load_settings() -> Settings:
    app = AppSettings(
        name=os.getenv("APP_NAME", "PoemBot"),
        environment=os.getenv("APP_ENV", "development").lower(),
        timezone=os.getenv("APP_TIMEZONE", "Asia/Yangon"),
        language=os.getenv("APP_LANGUAGE", "my"),
        debug=_env_bool("APP_DEBUG", False),
        data_dir=os.getenv("DATA_DIR", "./data"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )

    owner_ids_raw = _env_list("OWNER_IDS")
    owner_ids = tuple(int(item) for item in owner_ids_raw if item.isdigit())

    telegram = TelegramSettings(
        bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        api_id=_env_int("TELEGRAM_API_ID", 0),
        api_hash=os.getenv("TELEGRAM_API_HASH", ""),
        owner_ids=owner_ids,
        target_channel=os.getenv("TARGET_CHANNEL", "@poem_channel"),
        bot_enabled=_env_bool("TELEGRAM_BOT_ENABLED", True),
        user_client_enabled=_env_bool("TELEGRAM_USER_CLIENT_ENABLED", False),
        session_name=os.getenv("TELEGRAM_SESSION_NAME", "poembot_session"),
    )

    ai = AISettings(
        provider=os.getenv("AI_PROVIDER", "openrouter").lower(),
        api_key=os.getenv("AI_API_KEY", ""),
        model=os.getenv("AI_MODEL", "openai/gpt-4o-mini"),
        base_url=os.getenv("AI_BASE_URL", "https://openrouter.ai/api/v1"),
        temperature=_env_float("AI_TEMPERATURE", 0.4),
        max_tokens=_env_int("AI_MAX_TOKENS", 3000),
        timeout=_env_int("AI_TIMEOUT", 60),
        retries=_env_int("AI_RETRIES", 3),
    )

    database = DatabaseSettings(
        url=os.getenv("DATABASE_URL", "sqlite:///./data/poembot.db"),
        echo=_env_bool("DATABASE_ECHO", False),
    )

    images = ImageSettings(
        sources=_env_list("IMAGE_SOURCES", ("wikimedia",)),
        daily_limit=_env_int("IMAGE_DAILY_LIMIT", 5),
        max_file_size_mb=_env_int("IMAGE_MAX_FILE_SIZE_MB", 15),
        download_timeout=_env_int("IMAGE_DOWNLOAD_TIMEOUT", 30),
        cache_days=_env_int("IMAGE_CACHE_DAYS", 7),
        directory=os.getenv("IMAGE_DIR", "./data/images"),
    )

    posting = PostingSettings(
        daily_limit=_env_int("DAILY_POST_LIMIT", 5),
        interval_minutes=_env_int("POST_INTERVAL_MINUTES", 30),
        draft_expiry_hours=_env_int("DRAFT_EXPIRY_HOURS", 48),
        approval_required=_env_bool("APPROVAL_REQUIRED", True),
    )

    security = SecuritySettings(
        app_secret=os.getenv("APP_SECRET_KEY", "change_me_to_a_secure_random_string_of_at_least_32_chars"),
        confirmation_timeout=_env_int("CONFIRMATION_TIMEOUT", 120),
        max_pending_actions=_env_int("MAX_PENDING_ACTIONS", 5),
    )

    return Settings(app, telegram, ai, database, images, posting, security)
