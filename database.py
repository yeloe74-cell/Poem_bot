"""database.py — Async database layer for PoemBot.

Schema, validation helpers, and repository methods for poems, channels,
drafts, and cached images.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, AsyncIterator, Mapping
from urllib.parse import urlparse

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    and_,
    delete,
    event,
    insert,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    create_async_engine,
)

from config import DatabaseConfig

logger = logging.getLogger(__name__)

# ─── Schema ────────────────────────────────────────────────────────────────

metadata = MetaData()

poems = Table(
    "poems",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("source_channel", String(255), nullable=False),
    Column("source_message_id", String(100), nullable=False),
    Column("author", String(255)),
    Column("content", Text, nullable=False),
    Column("content_hash", String(64), nullable=False, unique=True),
    Column("category", String(100)),
    Column("emotion", String(100)),
    Column("quality_score", Integer),
    Column("analysis", Text),
    Column("collected_at", DateTime(timezone=True), nullable=False),
    Column("analyzed_at", DateTime(timezone=True)),
    UniqueConstraint("source_channel", "source_message_id", name="uq_poem_source"),
)
Index("ix_poems_analysis_queue", poems.c.analyzed_at, poems.c.collected_at)
Index("ix_poems_category", poems.c.category)

source_channels = Table(
    "source_channels",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("channel", String(255), nullable=False, unique=True),
    Column("enabled", Boolean, nullable=False, default=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

scan_states = Table(
    "scan_states",
    metadata,
    Column(
        "channel",
        String(255),
        ForeignKey("source_channels.channel", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("last_message_id", String(100)),
    Column("last_scanned_at", DateTime(timezone=True)),
    Column("last_error", Text),
    Column("consecutive_errors", Integer, nullable=False, default=0),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

drafts = Table(
    "drafts",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("poem_id", String(36), ForeignKey("poems.id", ondelete="CASCADE"), nullable=False),
    Column("image_url", Text),
    Column("image_source", String(100)),
    Column("image_credit", Text),
    Column("caption", Text, nullable=False),
    Column("status", String(30), nullable=False),
    Column("scheduled_at", DateTime(timezone=True)),
    Column("published_at", DateTime(timezone=True)),
    Column("publish_message_id", String(100)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("reviewed_by", String(50)),
    Column("reviewed_at", DateTime(timezone=True)),
    Column("error_message", Text),
)
Index("ix_drafts_status_expiry", drafts.c.status, drafts.c.expires_at)
Index("ix_drafts_poem", drafts.c.poem_id)

image_cache = Table(
    "image_cache",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("image_url", Text, nullable=False),
    Column("url_hash", String(64), nullable=False, unique=True),
    Column("source", String(100), nullable=False),
    Column("description", Text),
    Column("credit", Text),
    Column("local_path", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
)
Index("ix_image_cache_expiry", image_cache.c.expires_at)


class DatabaseError(RuntimeError):
    """Raised when a database operation fails."""


class AddResult(str, Enum):
    CREATED = "created"
    DUPLICATE = "duplicate"


class DraftStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUBLISHED = "published"
    FAILED = "failed"


def utc_now() -> datetime:
    """Return an aware UTC datetime (compatible with Python 3.10+)."""
    return datetime.now(timezone.utc)


def make_id() -> str:
    return str(uuid.uuid4())


def _enable_fk(connection: Any, _: Any) -> None:
    """Enable SQLite foreign-key enforcement for each new DB connection."""
    cursor = connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


_TG_HOSTS = {"t.me", "www.t.me", "telegram.me", "www.telegram.me"}
_INVITE_RE = re.compile(r"^[A-Za-z0-9_-]{8,}$")
_USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")


def normalize_channel(value: str) -> str:
    """Normalize a Telegram username, invite link, or numeric channel ID."""
    raw = value.strip()
    if not raw:
        raise ValueError("Channel is empty")
    if raw.startswith("-100") and raw[4:].isdigit():
        return raw
    if raw.startswith("@"):
        username = raw[1:].lower()
        if not _USERNAME_RE.fullmatch(username):
            raise ValueError("Invalid Telegram username")
        return username

    candidate = raw
    if "://" not in candidate and candidate.lower().startswith(("t.me/", "telegram.me/")):
        candidate = "https://" + candidate
    if "://" in candidate:
        parsed = urlparse(candidate)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("Unsupported scheme")
        if parsed.netloc.lower() not in _TG_HOSTS or parsed.query or parsed.fragment:
            raise ValueError("Not a supported Telegram link")
        path = parsed.path.strip("/")
        if path.startswith("+"):
            token = path[1:]
            if not _INVITE_RE.fullmatch(token):
                raise ValueError("Invalid invite")
            return f"invite:+{token}"
        if path.startswith("joinchat/"):
            token = path.split("/", 1)[1]
            if not _INVITE_RE.fullmatch(token):
                raise ValueError("Invalid invite")
            return f"invite:joinchat/{token}"
        parts = path.split("/")
        if len(parts) != 1 or not _USERNAME_RE.fullmatch(parts[0]):
            raise ValueError("Unsupported link")
        return parts[0].lower()
    if raw.startswith("+") and _INVITE_RE.fullmatch(raw[1:]):
        return f"invite:+{raw[1:]}"
    if raw.startswith("joinchat/"):
        token = raw.split("/", 1)[1]
        if _INVITE_RE.fullmatch(token):
            return f"invite:joinchat/{token}"
    if raw.isdigit():
        raise ValueError("Use channel ID beginning with -100")
    raise ValueError("Invalid channel identifier")


def hash_content(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value).strip().casefold()
    if not normalized:
        raise ValueError("Content empty")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def hash_url(value: str) -> str:
    if not value.strip():
        raise ValueError("URL empty")
    return hashlib.sha256(value.strip().encode("utf-8")).hexdigest()


def _rows(result: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in result.mappings().all()]


def _validate_https(value: str) -> None:
    parsed = urlparse(value.strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Valid HTTPS URL required")


class Database:
    """Async SQLAlchemy repository for poems, channels, drafts, and images."""

    def __init__(self, config: DatabaseConfig) -> None:
        config.validate()
        options: dict[str, Any] = {"echo": config.echo, "pool_pre_ping": True}
        if config.url.startswith("sqlite"):
            options["connect_args"] = {"timeout": config.timeout}
        else:
            options.update(pool_size=config.pool_size, pool_timeout=config.timeout)
        self.config = config
        self.engine: AsyncEngine = create_async_engine(config.url, **options)
        if config.url.startswith("sqlite"):
            event.listen(self.engine.sync_engine, "connect", _enable_fk)
        self._initialized = False
        self._closed = False

    async def initialize(self) -> None:
        if self._closed:
            raise DatabaseError("Closed")
        if self._initialized:
            return
        try:
            async with self.engine.begin() as connection:
                await connection.run_sync(metadata.create_all)
            self._initialized = True
            logger.info("Database initialized")
        except SQLAlchemyError as exc:
            raise DatabaseError("Init failed") from exc

    async def close(self) -> None:
        if not self._closed:
            await self.engine.dispose()
            self._closed = True
            self._initialized = False

    def _ready(self) -> None:
        if self._closed or not self._initialized:
            raise DatabaseError("Not initialized")

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncConnection]:
        self._ready()
        try:
            async with self.engine.begin() as connection:
                yield connection
        except SQLAlchemyError as exc:
            logger.exception("Transaction failed")
            raise DatabaseError("Transaction failed") from exc

    def _ignore(self, table: Table, values: Mapping[str, Any]) -> Any:
        dialect = self.engine.dialect.name
        if dialect == "sqlite":
            statement = sqlite_insert(table).values(**values)
        elif dialect == "postgresql":
            statement = pg_insert(table).values(**values)
        else:
            raise DatabaseError(f"Unsupported dialect: {dialect}")
        return statement.on_conflict_do_nothing()

    def _upsert(
        self,
        table: Table,
        values: Mapping[str, Any],
        column: Column,
        updates: Mapping[str, Any],
    ) -> Any:
        dialect = self.engine.dialect.name
        if dialect == "sqlite":
            statement = sqlite_insert(table).values(**values)
        elif dialect == "postgresql":
            statement = pg_insert(table).values(**values)
        else:
            raise DatabaseError(f"Unsupported dialect: {dialect}")
        return statement.on_conflict_do_update(
            index_elements=[column], set_=dict(updates)
        )

    # Poems
    async def add_poem(
        self,
        *,
        channel: str,
        message_id: str | int,
        content: str,
        author: str | None = None,
    ) -> tuple[AddResult, str | None]:
        channel_key = normalize_channel(channel)
        message_key = str(message_id).strip()
        text = content.strip()
        if not message_key or not text:
            raise ValueError("Required fields")
        poem_id = make_id()
        values = {
            "id": poem_id,
            "source_channel": channel_key,
            "source_message_id": message_key,
            "author": author.strip() if author and author.strip() else None,
            "content": text,
            "content_hash": hash_content(text),
            "collected_at": utc_now(),
        }
        async with self.transaction() as connection:
            result = await connection.execute(self._ignore(poems, values))
            if result.rowcount == 0:
                return AddResult.DUPLICATE, None
        return AddResult.CREATED, poem_id

    async def get_poem(self, poem_id: str) -> dict[str, Any] | None:
        self._ready()
        try:
            async with self.engine.connect() as connection:
                result = await connection.execute(select(poems).where(poems.c.id == poem_id))
                row = result.mappings().first()
                return dict(row) if row else None
        except SQLAlchemyError as exc:
            raise DatabaseError("Get poem failed") from exc

    async def get_unanalyzed_poems(self, limit: int = 100) -> list[dict[str, Any]]:
        if not 1 <= limit <= 1000:
            raise ValueError("Limit must be between 1 and 1000")
        self._ready()
        try:
            async with self.engine.connect() as connection:
                result = await connection.execute(
                    select(poems)
                    .where(poems.c.analyzed_at.is_(None))
                    .order_by(poems.c.collected_at.asc())
                    .limit(limit)
                )
                return _rows(result)
        except SQLAlchemyError as exc:
            raise DatabaseError("Get unanalyzed poems failed") from exc

    async def update_poem_analysis(
        self,
        poem_id: str,
        *,
        category: str,
        emotion: str,
        quality_score: int,
        analysis: Mapping[str, Any],
    ) -> bool:
        if not 0 <= quality_score <= 100:
            raise ValueError("Score must be between 0 and 100")
        payload = json.dumps(analysis, ensure_ascii=False, default=str)
        async with self.transaction() as connection:
            result = await connection.execute(
                update(poems)
                .where(poems.c.id == poem_id)
                .values(
                    category=category.strip(),
                    emotion=emotion.strip(),
                    quality_score=quality_score,
                    analysis=payload,
                    analyzed_at=utc_now(),
                )
            )
            return result.rowcount == 1

    # Source channels
    async def add_source_channel(self, channel: str) -> bool:
        key, now = normalize_channel(channel), utc_now()
        async with self.transaction() as connection:
            result = await connection.execute(
                self._ignore(
                    source_channels,
                    {"id": make_id(), "channel": key, "enabled": True, "created_at": now},
                )
            )
            await connection.execute(
                self._ignore(
                    scan_states,
                    {
                        "channel": key,
                        "last_message_id": None,
                        "last_scanned_at": None,
                        "last_error": None,
                        "consecutive_errors": 0,
                        "updated_at": now,
                    },
                )
            )
            return result.rowcount == 1

    async def list_source_channels(self, enabled_only: bool = True) -> list[dict[str, Any]]:
        self._ready()
        query = select(source_channels)
        if enabled_only:
            query = query.where(source_channels.c.enabled.is_(True))
        try:
            async with self.engine.connect() as connection:
                result = await connection.execute(
                    query.order_by(source_channels.c.created_at.asc())
                )
                return _rows(result)
        except SQLAlchemyError as exc:
            raise DatabaseError("List channels failed") from exc

    async def set_channel_enabled(self, channel: str, enabled: bool) -> bool:
        key = normalize_channel(channel)
        async with self.transaction() as connection:
            result = await connection.execute(
                update(source_channels)
                .where(source_channels.c.channel == key)
                .values(enabled=enabled)
            )
            return result.rowcount == 1

    # Scan state
    async def update_scan_state(
        self,
        channel: str,
        *,
        message_id: str | int | None = None,
        error: str | None = None,
    ) -> None:
        if (message_id is None) == (error is None):
            raise ValueError("Provide exactly one: message_id or error")
        if error is not None and not error.strip():
            raise ValueError("Error message cannot be empty")
        key, now = normalize_channel(channel), utc_now()
        values = {
            "channel": key,
            "last_message_id": str(message_id) if message_id is not None else None,
            "last_scanned_at": now if message_id is not None else None,
            "last_error": error[:2000] if error else None,
            "consecutive_errors": 1 if error else 0,
            "updated_at": now,
        }
        updates: dict[str, Any] = {"updated_at": now}
        if message_id is not None:
            updates.update(
                last_message_id=str(message_id),
                last_scanned_at=now,
                last_error=None,
                consecutive_errors=0,
            )
        else:
            updates.update(
                last_error=error[:2000],
                consecutive_errors=scan_states.c.consecutive_errors + 1,
            )
        async with self.transaction() as connection:
            await connection.execute(
                self._upsert(scan_states, values, scan_states.c.channel, updates)
            )

    async def get_scan_state(self, channel: str) -> dict[str, Any] | None:
        key = normalize_channel(channel)
        self._ready()
        try:
            async with self.engine.connect() as connection:
                result = await connection.execute(
                    select(scan_states).where(scan_states.c.channel == key)
                )
                row = result.mappings().first()
                return dict(row) if row else None
        except SQLAlchemyError as exc:
            raise DatabaseError("Get scan state failed") from exc

    # Drafts
    async def create_draft(
        self,
        *,
        poem_id: str,
        caption: str,
        image_url: str | None = None,
        image_source: str | None = None,
        image_credit: str | None = None,
        expiry_hours: int = 48,
    ) -> str:
        if not caption.strip():
            raise ValueError("Caption required")
        if not 1 <= expiry_hours <= 720:
            raise ValueError("Expiry must be between 1 and 720 hours")
        if image_url:
            _validate_https(image_url)
        draft_id, now = make_id(), utc_now()
        async with self.transaction() as connection:
            result = await connection.execute(
                select(poems.c.id).where(poems.c.id == poem_id)
            )
            if result.first() is None:
                raise ValueError("Poem missing")
            await connection.execute(
                insert(drafts).values(
                    id=draft_id,
                    poem_id=poem_id,
                    image_url=image_url,
                    image_source=image_source,
                    image_credit=image_credit,
                    caption=caption.strip(),
                    status=DraftStatus.PENDING.value,
                    created_at=now,
                    expires_at=now + timedelta(hours=expiry_hours),
                )
            )
        return draft_id

    async def get_draft(self, draft_id: str) -> dict[str, Any] | None:
        self._ready()
        query = (
            select(drafts, poems.c.content, poems.c.author, poems.c.source_channel)
            .join(poems, drafts.c.poem_id == poems.c.id)
            .where(drafts.c.id == draft_id)
        )
        try:
            async with self.engine.connect() as connection:
                result = await connection.execute(query)
                row = result.mappings().first()
                return dict(row) if row else None
        except SQLAlchemyError as exc:
            raise DatabaseError("Get draft failed") from exc

    async def list_pending_drafts(self, limit: int = 20) -> list[dict[str, Any]]:
        if not 1 <= limit <= 200:
            raise ValueError("Limit must be between 1 and 200")
        self._ready()
        try:
            async with self.engine.connect() as connection:
                result = await connection.execute(
                    select(drafts)
                    .where(
                        drafts.c.status == DraftStatus.PENDING.value,
                        drafts.c.expires_at > utc_now(),
                    )
                    .order_by(drafts.c.created_at.asc())
                    .limit(limit)
                )
                return _rows(result)
        except SQLAlchemyError as exc:
            raise DatabaseError("List drafts failed") from exc

    async def _change_status(
        self,
        draft_id: str,
        expected: DraftStatus,
        target: DraftStatus,
        owner_id: str | int,
    ) -> bool:
        async with self.transaction() as connection:
            result = await connection.execute(
                update(drafts)
                .where(
                    and_(
                        drafts.c.id == draft_id,
                        drafts.c.status == expected.value,
                        drafts.c.expires_at > utc_now(),
                    )
                )
                .values(
                    status=target.value,
                    reviewed_by=str(owner_id),
                    reviewed_at=utc_now(),
                )
            )
            return result.rowcount == 1

    async def approve_draft(self, draft_id: str, owner_id: str | int) -> bool:
        return await self._change_status(
            draft_id, DraftStatus.PENDING, DraftStatus.APPROVED, owner_id
        )

    async def reject_draft(self, draft_id: str, owner_id: str | int) -> bool:
        return await self._change_status(
            draft_id, DraftStatus.PENDING, DraftStatus.REJECTED, owner_id
        )

    async def mark_draft_published(self, draft_id: str, message_id: str | int) -> bool:
        message_key = str(message_id).strip()
        if not message_key:
            raise ValueError("Message ID required")
        async with self.transaction() as connection:
            result = await connection.execute(
                update(drafts)
                .where(
                    drafts.c.id == draft_id,
                    drafts.c.status == DraftStatus.APPROVED.value,
                )
                .values(
                    status=DraftStatus.PUBLISHED.value,
                    published_at=utc_now(),
                    publish_message_id=message_key,
                    error_message=None,
                )
            )
            return result.rowcount == 1

    async def mark_draft_failed(self, draft_id: str, reason: str) -> bool:
        if not reason.strip():
            raise ValueError("Reason required")
        async with self.transaction() as connection:
            result = await connection.execute(
                update(drafts)
                .where(
                    drafts.c.id == draft_id,
                    drafts.c.status == DraftStatus.APPROVED.value,
                )
                .values(
                    status=DraftStatus.FAILED.value,
                    error_message=reason[:2000],
                )
            )
            return result.rowcount == 1

    async def delete_expired_drafts(self, grace_hours: int = 24) -> int:
        if not 0 <= grace_hours <= 8760:
            raise ValueError("Grace must be between 0 and 8760 hours")
        cutoff = utc_now() - timedelta(hours=grace_hours)
        async with self.transaction() as connection:
            result = await connection.execute(
                delete(drafts).where(
                    drafts.c.expires_at < cutoff,
                    drafts.c.status.in_(
                        [
                            DraftStatus.PENDING.value,
                            DraftStatus.REJECTED.value,
                            DraftStatus.FAILED.value,
                        ]
                    ),
                )
            )
            return result.rowcount or 0

    # Image cache
    async def cache_image(
        self,
        *,
        url: str,
        source: str,
        description: str | None = None,
        credit: str | None = None,
        local_path: str | None = None,
        expiry_days: int = 30,
    ) -> bool:
        _validate_https(url)
        if not source.strip() or not 1 <= expiry_days <= 365:
            raise ValueError("Source and expiry (1-365 days) are required")
        now = utc_now()
        values = {
            "id": make_id(),
            "image_url": url.strip(),
            "url_hash": hash_url(url),
            "source": source.strip(),
            "description": description,
            "credit": credit,
            "local_path": local_path,
            "created_at": now,
            "expires_at": now + timedelta(days=expiry_days),
        }
        updates = {
            "image_url": url.strip(),
            "source": source.strip(),
            "description": description,
            "credit": credit,
            "local_path": local_path,
            "expires_at": values["expires_at"],
        }
        async with self.transaction() as connection:
            await connection.execute(
                self._upsert(image_cache, values, image_cache.c.url_hash, updates)
            )
        return True

    async def get_cached_image(self, url: str) -> dict[str, Any] | None:
        self._ready()
        try:
            async with self.engine.connect() as connection:
                result = await connection.execute(
                    select(image_cache).where(
                        image_cache.c.url_hash == hash_url(url),
                        image_cache.c.expires_at > utc_now(),
                    )
                )
                row = result.mappings().first()
                return dict(row) if row else None
        except SQLAlchemyError as exc:
            raise DatabaseError("Get image failed") from exc

    async def purge_expired_images(self) -> int:
        async with self.transaction() as connection:
            result = await connection.execute(
                delete(image_cache).where(image_cache.c.expires_at <= utc_now())
            )
            return result.rowcount or 0
