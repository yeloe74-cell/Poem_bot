from __future__ import annotations
import logging
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
class ConfigurationError(ValueError):
    """Raised when application configuration is invalid."""
_ENV_KEY = re.compile(r"[A-Z][A-Z0-9_]*\Z")
_USERNAME = re.compile(r"@[A-Za-z][A-Za-z0-9_]{4,31}\Z")
_CHAT_ID = re.compile(r"-?\d{5,20}\Z")
_BOT_TOKEN = re.compile(r"\d{5,15}:[A-Za-z0-9_-]{20,}\Z")
_LOG_LEVELS = frozenset(logging.getLevelNamesMapping())

def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            raise ConfigurationError(f"Invalid environment entry at {path}:{number}")
        key, value = (part.strip() for part in line.split("=", 1))
        if not _ENV_KEY.fullmatch(key):
            raise ConfigurationError(f"Invalid variable name at {path}:{number}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values

def _parse_owner_ids(raw: str) -> tuple[int, ...]:
    result: list[int] = []
    seen: set[int] = set()
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            owner_id = int(item)
        except ValueError as exc:
            raise ConfigurationError(f"Invalid OWNER_IDS value: {item}") from exc
        if owner_id <= 0:
            raise ConfigurationError("OWNER_IDS must contain positive IDs")
        if owner_id not in seen:
            result.append(owner_id)
            seen.add(owner_id)
    return tuple(result)
def _parse_list(raw: str) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for item in raw.split(","):
        value = item.strip().lower()
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return tuple(result)
def _normalize_channel(value: str, key: str) -> str:
    item = value.strip()
    if not item:
        raise ConfigurationError(f"{key} is required")
    if "://" in item:
        parsed = urlparse(item)
        try:
            port = parsed.port
        except ValueError as exc:
            raise ConfigurationError(f"{key} contains an invalid URL") from exc
        if (parsed.scheme != "https" or parsed.hostname not in {"t.me", "www.t.me"}
                or parsed.username or parsed.password or port is not None
                or parsed.query or parsed.fragment):
            raise ConfigurationError(f"{key} contains an unsupported Telegram URL")
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) != 1:
            raise ConfigurationError(f"{key} contains an unsupported Telegram URL")
        item = f"@{parts[0]}"
    if _CHAT_ID.fullmatch(item):
        return item
    if not item.startswith("@"):
        item = f"@{item}"
    if _USERNAME.fullmatch(item):
        return item.lower()
    raise ConfigurationError(f"{key} must be a Telegram username or chat ID")
def _parse_channels(raw: str, key: str) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for item in raw.split(","):
        if item.strip():
            channel = _normalize_channel(item, key)
            identity = channel.casefold()
            if identity not in seen:
                result.append(channel)
                seen.add(identity)
    return tuple(result)
def _safe_session_path(directory: Path, filename: str) -> Path:
    name = filename.strip()
    candidate = Path(name).expanduser()
    if (not name or candidate.is_absolute() or len(candidate.parts) != 1
            or "/" in name or "\\" in name or candidate.name in {"", ".", ".."}):
        raise ConfigurationError("TELEGRAM_SESSION_NAME must be a filename")
    return directory / candidate

class Environment:
    """Reads values from a dotenv file and the process environment."""
    def __init__(self, environ: Mapping[str, str] | None = None,
                 env_file: Path | None = None) -> None:
        values = _read_env_file(env_file or Path(".env"))
        values.update(dict(os.environ if environ is None else environ))
        self._values = values
    def string(self, key: str, default: str = "", *, required: bool = False) -> str:
        value = self._values.get(key, default).strip()
        if required and not value:
            raise ConfigurationError(f"{key} is required")
        return value
    def boolean(self, key: str, default: bool = False) -> bool:
        raw = self._values.get(key)
        if raw is None:
            return default
        value = raw.strip().lower()
        if value in {"1", "true", "yes", "on"}:
            return True
        if value in {"0", "false", "no", "off"}:
            return False
        raise ConfigurationError(f"{key} must be true or false")
    def integer(self, key: str, default: int, *, minimum: int | None = None,
                maximum: int | None = None) -> int:
        raw = self._values.get(key)
        try:
            value = default if raw is None else int(raw.strip())
        except (TypeError, ValueError) as exc:
            raise ConfigurationError(f"{key} must be an integer") from exc
        if minimum is not None and value < minimum: raise ConfigurationError(f"{key} must be at least {minimum}")
        if maximum is not None and value > maximum: raise ConfigurationError(f"{key} must be at most {maximum}")
        return value
    def number(self, key: str, default: float, *, minimum: float | None = None,
               maximum: float | None = None) -> float:
        raw = self._values.get(key)
        try:
            value = default if raw is None else float(raw.strip())
        except (TypeError, ValueError) as exc:
            raise ConfigurationError(f"{key} must be a number") from exc
        if not math.isfinite(value): raise ConfigurationError(f"{key} must be finite")
        if minimum is not None and value < minimum: raise ConfigurationError(f"{key} must be at least {minimum}")
        if maximum is not None and value > maximum: raise ConfigurationError(f"{key} must be at most {maximum}")
        return value
@dataclass(frozen=True, slots=True)
class AppConfig:
    name: str
    environment: str
    timezone: str
    language: str
    debug: bool
    data_dir: Path
    log_level: str
    def validate(self) -> None:
        if not self.name or not self.language: raise ConfigurationError("APP_NAME and APP_LANGUAGE are required")
        if self.environment not in {"development", "testing", "production"}: raise ConfigurationError("Invalid APP_ENV")
        if self.environment == "production" and self.debug: raise ConfigurationError("APP_DEBUG must be false in production")
        if self.log_level not in _LOG_LEVELS: raise ConfigurationError(f"Invalid LOG_LEVEL: {self.log_level}")
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ConfigurationError(f"Invalid APP_TIMEZONE: {self.timezone}") from exc
@dataclass(frozen=True, slots=True)
class TelegramConfig:
    bot_token: str
    api_id: int
    api_hash: str
    owner_ids: tuple[int, ...]
    target_channel: str
    session_name: str
    bot_enabled: bool
    user_client_enabled: bool
    request_timeout: int
    flood_wait_limit: int
    def __post_init__(self) -> None:
        if self.target_channel:
            object.__setattr__(self, "target_channel",
                               _normalize_channel(self.target_channel, "TARGET_CHANNEL"))
    def validate(self) -> None:
        if self.bot_enabled and not _BOT_TOKEN.fullmatch(self.bot_token):
            raise ConfigurationError("TELEGRAM_BOT_TOKEN format is invalid")
        if self.user_client_enabled and (self.api_id <= 0 or not self.api_hash):
            raise ConfigurationError("Telegram user-client credentials are required")
        if not self.owner_ids: raise ConfigurationError("At least one OWNER_ID is required")
        if not self.target_channel: raise ConfigurationError("TARGET_CHANNEL is required")
        if not self.session_name: raise ConfigurationError("TELEGRAM_SESSION_NAME is required")
        if self.request_timeout < 5:
            raise ConfigurationError("TELEGRAM_TIMEOUT must be at least 5")
        if self.flood_wait_limit < 0:
            raise ConfigurationError("TELEGRAM_FLOOD_WAIT_LIMIT cannot be negative")
@dataclass(frozen=True, slots=True)
class AIConfig:
    provider: str
    api_key: str
    model: str
    base_url: str
    temperature: float
    max_tokens: int
    timeout: int
    retries: int
    def validate(self) -> None:
        if self.provider not in {"openai", "openrouter", "gemini", "custom"}:
            raise ConfigurationError(f"Unsupported AI_PROVIDER: {self.provider}")
        if self.provider != "custom" and not self.api_key:
            raise ConfigurationError("AI_API_KEY is required")
        if not self.model or self.model == "provider-model-name":
            raise ConfigurationError("A real AI_MODEL must be configured")
        if not 0 <= self.temperature <= 2:
            raise ConfigurationError("AI_TEMPERATURE must be between 0 and 2")
        if self.base_url:
            parsed = urlparse(self.base_url)
            if parsed.scheme != "https" or not parsed.hostname:
                raise ConfigurationError("AI_BASE_URL must be an HTTPS URL")
        if self.max_tokens < 100 or self.timeout < 1 or self.retries < 0:
            raise ConfigurationError("AI limits are invalid")
@dataclass(frozen=True, slots=True)
class DatabaseConfig:
    url: str
    timeout: int
    pool_size: int
    echo: bool
    def validate(self) -> None:
        parsed = urlparse(self.url)
        if parsed.scheme == "sqlite+aiosqlite":
            valid = bool(parsed.path) and not parsed.netloc
        elif parsed.scheme == "postgresql+asyncpg":
            try:
                port = parsed.port
            except ValueError as exc:
                raise ConfigurationError("DATABASE_URL has an invalid port") from exc
            valid = bool(parsed.hostname and parsed.path.strip("/")
                         and (port is None or 1 <= port <= 65535))
        else:
            valid = False
        if not valid:
            raise ConfigurationError("DATABASE_URL must be a valid async database URL")
        if self.timeout < 1 or self.pool_size < 1:
            raise ConfigurationError("Database limits must be positive")
@dataclass(frozen=True, slots=True)
class ImageConfig:
    daily_limit: int
    max_file_size_mb: int
    download_timeout: int
    cache_days: int
    sources: tuple[str, ...]
    directory: Path
    def validate(self) -> None:
        if not self.sources: raise ConfigurationError("IMAGE_SOURCES cannot be empty")
        if not 1 <= self.daily_limit <= 10:
            raise ConfigurationError("IMAGE_DAILY_LIMIT must be between 1 and 10")
        if not 1 <= self.max_file_size_mb <= 50:
            raise ConfigurationError("IMAGE_MAX_FILE_SIZE_MB must be between 1 and 50")
        if self.download_timeout < 1 or self.cache_days < 1:
            raise ConfigurationError("Image limits must be positive")
@dataclass(frozen=True, slots=True)
class CollectorConfig:
    source_channels: tuple[str, ...]
    scan_interval: int
    batch_size: int
    history_limit: int
    def validate(self) -> None:
        if not self.source_channels:
            raise ConfigurationError("SOURCE_CHANNELS needs at least one channel")
        if self.scan_interval < 1:
            raise ConfigurationError("COLLECTOR_SCAN_INTERVAL must be positive")
        if not 1 <= self.batch_size <= 1000:
            raise ConfigurationError("COLLECTOR_BATCH_SIZE must be between 1 and 1000")
        if self.history_limit < 100: raise ConfigurationError("COLLECTOR_HISTORY_LIMIT must be at least 100")
@dataclass(frozen=True, slots=True)
class PostingConfig:
    daily_limit: int
    interval_minutes: int
    draft_expiry_hours: int
    approval_required: bool
    scheduled_posts: bool
    def validate(self) -> None:
        if not self.approval_required: raise ConfigurationError("Owner approval is mandatory")
        if min(self.daily_limit, self.interval_minutes, self.draft_expiry_hours) < 1:
            raise ConfigurationError("Posting limits must be positive")
@dataclass(frozen=True, slots=True)
class SecurityConfig:
    app_secret: str
    session_dir: Path
    confirmation_timeout: int
    max_pending_actions: int
    def validate(self) -> None:
        if len(self.app_secret) < 32: raise ConfigurationError("APP_SECRET_KEY needs at least 32 characters")
        if self.confirmation_timeout < 10: raise ConfigurationError("CONFIRMATION_TIMEOUT must be at least 10")
        if not 1 <= self.max_pending_actions <= 50: raise ConfigurationError("MAX_PENDING_ACTIONS must be between 1 and 50")
@dataclass(frozen=True, slots=True)
class Settings:
    app: AppConfig
    telegram: TelegramConfig
    ai: AIConfig
    database: DatabaseConfig
    images: ImageConfig
    collector: CollectorConfig
    posting: PostingConfig
    security: SecurityConfig
    def validate(self) -> None:
        for section in (self.app, self.telegram, self.ai, self.database,
                        self.images, self.collector, self.posting, self.security):
            section.validate()
    def prepare_directories(self) -> None:
        paths = {self.app.data_dir, self.app.data_dir / "logs",
                 self.images.directory, self.security.session_dir}
        for path in paths:
            path.mkdir(parents=True, exist_ok=True)
def load_settings(env_file: Path | None = None, *,
                  environ: Mapping[str, str] | None = None,
                  prepare_directories: bool = True) -> Settings:
    env = Environment(environ=environ, env_file=env_file)
    root = Path(env.string("DATA_DIR", "data")).expanduser().resolve()
    session_dir = root / "sessions"
    session_path = _safe_session_path(
        session_dir, env.string("TELEGRAM_SESSION_NAME", "poembot_user"))
    raw_target = env.string("TARGET_CHANNEL")
    target = _normalize_channel(raw_target, "TARGET_CHANNEL") if raw_target else ""
    app = AppConfig(
        name=env.string("APP_NAME", "PoemBot"),
        environment=env.string("APP_ENV", "development").lower(),
        timezone=env.string("APP_TIMEZONE", "Asia/Yangon"),
        language=env.string("APP_LANGUAGE", "my"),
        debug=env.boolean("APP_DEBUG", False), data_dir=root,
        log_level=env.string("LOG_LEVEL", "INFO").upper(),
    )
    telegram = TelegramConfig(
        bot_token=env.string("TELEGRAM_BOT_TOKEN"),
        api_id=env.integer("TELEGRAM_API_ID", 0, minimum=0),
        api_hash=env.string("TELEGRAM_API_HASH"),
        owner_ids=_parse_owner_ids(env.string("OWNER_IDS")),
        target_channel=target, session_name=str(session_path),
        bot_enabled=env.boolean("TELEGRAM_BOT_ENABLED", True),
        user_client_enabled=env.boolean("TELEGRAM_USER_CLIENT_ENABLED", True),
        request_timeout=env.integer("TELEGRAM_TIMEOUT", 30, minimum=5, maximum=180),
        flood_wait_limit=env.integer("TELEGRAM_FLOOD_WAIT_LIMIT", 60,
                                     minimum=0, maximum=3600),
    )
    ai = AIConfig(
        provider=env.string("AI_PROVIDER", "openrouter").lower(),
        api_key=env.string("AI_API_KEY"), model=env.string("AI_MODEL"),
        base_url=env.string("AI_BASE_URL"),
        temperature=env.number("AI_TEMPERATURE", 0.7, minimum=0, maximum=2),
        max_tokens=env.integer("AI_MAX_TOKENS", 3000, minimum=100, maximum=32000),
        timeout=env.integer("AI_TIMEOUT", 60, minimum=5, maximum=300),
        retries=env.integer("AI_RETRIES", 3, minimum=0, maximum=10),
    )
    database = DatabaseConfig(
        url=env.string("DATABASE_URL",
            f"sqlite+aiosqlite:///{(root / 'poembot.db').as_posix()}"),
        timeout=env.integer("DATABASE_TIMEOUT", 30, minimum=1),
        pool_size=env.integer("DATABASE_POOL_SIZE", 5, minimum=1),
        echo=env.boolean("DATABASE_ECHO", False),
    )
    images = ImageConfig(
        daily_limit=env.integer("IMAGE_DAILY_LIMIT", 5, minimum=1, maximum=10),
        max_file_size_mb=env.integer("IMAGE_MAX_FILE_SIZE_MB", 15,
                                     minimum=1, maximum=50),
        download_timeout=env.integer("IMAGE_DOWNLOAD_TIMEOUT", 30,
                                     minimum=5, maximum=180),
        cache_days=env.integer("IMAGE_CACHE_DAYS", 7, minimum=1),
        sources=_parse_list(env.string("IMAGE_SOURCES", "wikimedia")),
        directory=root / "images",
    )
    collector = CollectorConfig(
        source_channels=_parse_channels(env.string("SOURCE_CHANNELS"),
                                        "SOURCE_CHANNELS"),
        scan_interval=env.integer("COLLECTOR_SCAN_INTERVAL", 15, minimum=1),
        batch_size=env.integer("COLLECTOR_BATCH_SIZE", 100,
                               minimum=1, maximum=1000),
        history_limit=env.integer("COLLECTOR_HISTORY_LIMIT", 5000, minimum=100),
    )
    posting = PostingConfig(
        daily_limit=env.integer("DAILY_POST_LIMIT", 5, minimum=1, maximum=30),
        interval_minutes=env.integer("POST_INTERVAL_MINUTES", 30, minimum=1),
        draft_expiry_hours=env.integer("DRAFT_EXPIRY_HOURS", 48, minimum=1),
        approval_required=env.boolean("APPROVAL_REQUIRED", True),
        scheduled_posts=env.boolean("SCHEDULED_POSTS_ENABLED", True),
    )
    security = SecurityConfig(
        app_secret=env.string("APP_SECRET_KEY", required=True),
        session_dir=session_dir,
        confirmation_timeout=env.integer("CONFIRMATION_TIMEOUT", 120, minimum=10),
        max_pending_actions=env.integer("MAX_PENDING_ACTIONS", 5,
                                        minimum=1, maximum=50),
    )
    settings = Settings(app, telegram, ai, database, images,
                        collector, posting, security)
    settings.validate()
    if prepare_directories:
        settings.prepare_directories()
    return settings
