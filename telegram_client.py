"""telegram_client.py — Telegram delivery and collection tools.

This module provides Bot API delivery and optional Telethon/MTProto source
collection. It does not choose message content or channel actions.
"""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from telegram import Bot, InlineKeyboardMarkup
from telegram.error import (
    BadRequest,
    Forbidden,
    NetworkError,
    RetryAfter,
    TelegramError,
    TimedOut,
)
from telegram.ext import Application

from config import TelegramConfig

logger = logging.getLogger(__name__)


class TelegramToolError(RuntimeError):
    """Base error for Telegram tool operations."""


class ToolNotStarted(TelegramToolError):
    """A tool was used before start() or after stop()."""


class DeliveryFailed(TelegramToolError):
    """Delivery failed after retries."""


class RecipientBlocked(TelegramToolError):
    """The recipient blocked the bot or the chat is inaccessible."""


class InvalidContent(TelegramToolError):
    """Telegram rejected the supplied content or file."""


class Throttled(TelegramToolError):
    """A rate limit was encountered; the caller can retry later."""


@dataclass(slots=True)
class RateLimiter:
    """Pace outgoing requests globally and independently per chat."""

    global_per_second: float = 30.0
    per_chat_per_second: float = 1.0
    _global_lock: asyncio.Lock = field(init=False, repr=False)
    _chat_locks: dict[str, asyncio.Lock] = field(init=False, default_factory=dict, repr=False)
    _chat_guard: asyncio.Lock = field(init=False, repr=False)
    _global_next: float = field(init=False, default=0.0, repr=False)
    _chat_next: dict[str, float] = field(init=False, default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if self.global_per_second <= 0 or self.per_chat_per_second <= 0:
            raise ValueError("Rate limits must be positive")
        self._global_lock = asyncio.Lock()
        self._chat_guard = asyncio.Lock()

    async def _chat_lock(self, chat_id: str) -> asyncio.Lock:
        async with self._chat_guard:
            return self._chat_locks.setdefault(chat_id, asyncio.Lock())

    async def _reserve_global(self) -> float:
        async with self._global_lock:
            now = time.monotonic()
            wait = max(0.0, self._global_next - now)
            self._global_next = max(now, self._global_next) + 1.0 / self.global_per_second
            return wait

    async def _reserve_chat(self, chat_id: str) -> float:
        lock = await self._chat_lock(chat_id)
        async with lock:
            now = time.monotonic()
            next_time = self._chat_next.get(chat_id, 0.0)
            wait = max(0.0, next_time - now)
            self._chat_next[chat_id] = max(now, next_time) + 1.0 / self.per_chat_per_second
            return wait

    @asynccontextmanager
    async def slot(self, chat_id: str) -> AsyncIterator[None]:
        """Wait for a globally and per-chat paced request slot."""
        global_wait, chat_wait = await asyncio.gather(
            self._reserve_global(), self._reserve_chat(str(chat_id))
        )
        await asyncio.sleep(max(global_wait, chat_wait))
        yield


class BotClient:
    """Outbound Telegram Bot API tool; callers provide all message content."""

    def __init__(self, config: TelegramConfig, *,
                 rate_limiter: RateLimiter | None = None) -> None:
        config.validate()
        self._config = config
        self._rate = rate_limiter or RateLimiter()
        self._app: Application | None = None
        self._bot: Bot | None = None
        self._lock = asyncio.Lock()
        self._running = False

    async def start(self) -> None:
        """Initialize and start the Application. Safe to call repeatedly."""
        async with self._lock:
            if self._running:
                return
            app = (Application.builder().token(self._config.bot_token)
                   .read_timeout(self._config.request_timeout)
                   .write_timeout(self._config.request_timeout)
                   .connect_timeout(self._config.request_timeout).build())
            self._app = app
            try:
                await app.initialize()
                await app.start()
                self._bot = app.bot
                self._running = True
                logger.info("BotClient started")
            except Exception as exc:
                await self._teardown()
                raise TelegramToolError("BotClient start failed") from exc

    async def stop(self) -> None:
        """Stop and release the Application. Safe to call repeatedly."""
        async with self._lock:
            if self._app is None and not self._running:
                return
            await self._teardown()
            logger.info("BotClient stopped")

    async def _teardown(self) -> None:
        app = self._app
        self._app = None
        self._bot = None
        self._running = False
        if app is None:
            return
        try:
            if app.running:
                await app.stop()
        except Exception:
            logger.exception("BotClient stop error")
        try:
            await app.shutdown()
        except Exception:
            logger.exception("BotClient shutdown error")

    async def __aenter__(self) -> "BotClient":
        await self.start()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.stop()

    def _require_bot(self) -> Bot:
        if not self._running or self._bot is None:
            raise ToolNotStarted("BotClient not started")
        return self._bot

    @property
    def is_running(self) -> bool:
        return self._running

    async def _retry(self, factory, *, max_attempts: int = 3):
        """Retry transient Telegram failures using a zero-argument coroutine."""
        last: Exception | None = None
        for attempt in range(max_attempts):
            try:
                return await factory()
            except RetryAfter as exc:
                last = exc
                wait = float(exc.retry_after) + 1
                logger.warning("Telegram rate limit; retry in %.1fs", wait)
                if attempt + 1 < max_attempts:
                    await asyncio.sleep(wait)
            except (TimedOut, NetworkError) as exc:
                last = exc
                wait = 2 ** attempt
                logger.warning("Transient Telegram error; retry in %ss", wait)
                if attempt + 1 < max_attempts:
                    await asyncio.sleep(wait)
            except Forbidden as exc:
                raise RecipientBlocked(str(exc)) from exc
            except BadRequest as exc:
                raise InvalidContent(str(exc)) from exc
        raise DeliveryFailed(f"Delivery failed after {max_attempts} attempts") from last

    async def send_text(self, *, chat_id: str | int, text: str,
                        parse_mode: str | None = "HTML",
                        disable_preview: bool = True,
                        keyboard: InlineKeyboardMarkup | None = None) -> int:
        """Send caller-provided text and return its message ID."""
        bot = self._require_bot()
        if not text or not text.strip():
            raise InvalidContent("Empty text")

        async def send() -> int:
            async with self._rate.slot(str(chat_id)):
                message = await bot.send_message(
                    chat_id=chat_id, text=text, parse_mode=parse_mode,
                    disable_web_page_preview=disable_preview, reply_markup=keyboard,
                )
            return message.message_id

        return await self._retry(send)

    async def send_photo(self, *, chat_id: str | int, photo_path: str,
                         caption: str = "", parse_mode: str | None = "HTML",
                         keyboard: InlineKeyboardMarkup | None = None) -> int:
        """Send a local photo and return its message ID."""
        bot = self._require_bot()

        async def send() -> int:
            async with self._rate.slot(str(chat_id)):
                with open(photo_path, "rb") as photo:
                    message = await bot.send_photo(
                        chat_id=chat_id, photo=photo,
                        caption=caption[:1024] if caption else None,
                        parse_mode=parse_mode if caption else None,
                        reply_markup=keyboard,
                    )
            return message.message_id

        try:
            return await self._retry(send)
        except FileNotFoundError as exc:
            raise InvalidContent(f"Photo file missing: {photo_path}") from exc

    async def send_document(self, *, chat_id: str | int, file_path: str,
                            caption: str = "", parse_mode: str | None = "HTML") -> int:
        """Send a local file as a document and return its message ID."""
        bot = self._require_bot()

        async def send() -> int:
            async with self._rate.slot(str(chat_id)):
                with open(file_path, "rb") as document:
                    message = await bot.send_document(
                        chat_id=chat_id, document=document,
                        caption=caption[:1024] if caption else None,
                        parse_mode=parse_mode if caption else None,
                    )
            return message.message_id

        try:
            return await self._retry(send)
        except FileNotFoundError as exc:
            raise InvalidContent(f"Document missing: {file_path}") from exc

    async def edit_text(self, *, chat_id: str | int, message_id: int,
                        text: str, parse_mode: str | None = "HTML",
                        keyboard: InlineKeyboardMarkup | None = None) -> bool:
        """Edit message text; return True if changed or already identical."""
        bot = self._require_bot()
        if not text or not text.strip():
            raise InvalidContent("Empty text")

        async def edit() -> bool:
            async with self._rate.slot(str(chat_id)):
                try:
                    await bot.edit_message_text(
                        chat_id=chat_id, message_id=message_id, text=text,
                        parse_mode=parse_mode, reply_markup=keyboard,
                    )
                    return True
                except BadRequest as exc:
                    if "not modified" in str(exc).lower():
                        return True
                    raise

        try:
            return await self._retry(edit)
        except TelegramToolError:
            return False

    async def edit_caption(self, *, chat_id: str | int, message_id: int,
                           caption: str, parse_mode: str | None = "HTML",
                           keyboard: InlineKeyboardMarkup | None = None) -> bool:
        """Edit a photo/document caption."""
        bot = self._require_bot()

        async def edit() -> bool:
            async with self._rate.slot(str(chat_id)):
                try:
                    await bot.edit_message_caption(
                        chat_id=chat_id, message_id=message_id,
                        caption=caption[:1024], parse_mode=parse_mode,
                        reply_markup=keyboard,
                    )
                    return True
                except BadRequest as exc:
                    if "not modified" in str(exc).lower():
                        return True
                    raise

        try:
            return await self._retry(edit)
        except TelegramToolError:
            return False

    async def delete_message(self, *, chat_id: str | int, message_id: int) -> bool:
        """Delete a message; return True if deleted, False if already unavailable."""
        bot = self._require_bot()

        async def delete() -> bool:
            async with self._rate.slot(str(chat_id)):
                try:
                    await bot.delete_message(chat_id=chat_id, message_id=message_id)
                    return True
                except BadRequest:
                    return False

        return await self._retry(delete)

    async def answer_callback(self, *, callback_query_id: str, text: str = "",
                              show_alert: bool = False) -> None:
        """Acknowledge a callback using only caller-provided text."""
        bot = self._require_bot()
        try:
            await bot.answer_callback_query(
                callback_query_id=callback_query_id,
                text=text[:200] if text else None, show_alert=show_alert,
            )
        except TelegramError as exc:
            logger.warning("answer_callback failed: %s", exc)

    async def get_chat_info(self, chat_id: str | int) -> dict[str, Any]:
        """Return basic information about a chat."""
        bot = self._require_bot()

        async def fetch() -> dict[str, Any]:
            chat = await bot.get_chat(chat_id=chat_id)
            return {"ok": True, "id": chat.id,
                    "title": chat.title or chat.full_name or None,
                    "username": chat.username, "type": chat.type}

        try:
            return await self._retry(fetch)
        except TelegramToolError:
            return {"ok": False, "id": None, "title": None,
                    "username": None, "type": None}

    async def get_self_info(self) -> dict[str, Any]:
        """Return the bot's own identity."""
        bot = self._require_bot()

        async def fetch() -> dict[str, Any]:
            me = await bot.get_me()
            return {"id": me.id, "username": me.username, "first_name": me.first_name}

        return await self._retry(fetch)


from telethon import TelegramClient as UserTelegramClient
from telethon.errors import (
    ChannelPrivateError,
    FloodWaitError,
    RPCError,
    UserAlreadyParticipantError,
    UserNotParticipantError,
)
from telethon.tl.functions.channels import (
    GetFullChannelRequest,
    JoinChannelRequest,
    LeaveChannelRequest,
)
from telethon.tl.types import Channel, User


class UserClient:
    """Inbound Telethon tool for reading and managing source channels."""

    def __init__(self, config: TelegramConfig, *, min_join_interval: float = 5.0,
                 min_read_interval: float = 1.0) -> None:
        config.validate()
        self._config = config
        self._min_join_interval = max(0.0, min_join_interval)
        self._min_read_interval = max(0.0, min_read_interval)
        self._client: UserTelegramClient | None = None
        self._lock = asyncio.Lock()
        self._running = False

    async def start(self) -> None:
        async with self._lock:
            if self._running:
                return
            if self._config.api_id <= 0 or not self._config.api_hash:
                raise TelegramToolError("Telethon credentials missing")
            client = UserTelegramClient(
                self._config.session_name,
                api_id=self._config.api_id,
                api_hash=self._config.api_hash,
                flood_sleep_threshold=self._config.flood_wait_limit,
            )
            self._client = client
            try:
                await client.start()
                self._running = True
                logger.info("UserClient started")
            except Exception as exc:
                await self._teardown()
                raise TelegramToolError("UserClient start failed") from exc

    async def stop(self) -> None:
        async with self._lock:
            if self._client is None and not self._running:
                return
            await self._teardown()
            logger.info("UserClient stopped")

    async def _teardown(self) -> None:
        client = self._client
        self._client = None
        self._running = False
        if client is not None:
            try:
                await client.disconnect()
            except Exception:
                logger.exception("UserClient teardown error")

    async def __aenter__(self) -> "UserClient":
        await self.start()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.stop()

    def _require_client(self) -> UserTelegramClient:
        if not self._running or self._client is None:
            raise ToolNotStarted("UserClient not started")
        return self._client

    @property
    def is_running(self) -> bool:
        return self._running

    @asynccontextmanager
    async def _guard(self) -> AsyncIterator[None]:
        try:
            yield
        except FloodWaitError as exc:
            wait = min(int(exc.seconds) + 1, 300)
            logger.warning("Telethon FloodWait %ss", wait)
            await asyncio.sleep(wait)
            raise Throttled(f"FloodWait {wait}s") from exc
        except ChannelPrivateError as exc:
            raise RecipientBlocked("Channel is private") from exc
        except RPCError as exc:
            raise TelegramToolError(f"RPC error: {exc}") from exc

    async def read_channel(self, *, channel: str, min_id: int = 0,
                           limit: int = 100, skip_empty: bool = True
                           ) -> list[dict[str, Any]]:
        """Read recent messages from a source channel."""
        client = self._require_client()
        if not 1 <= limit <= 500:
            raise ValueError("limit must be 1-500")
        async with self._guard():
            try:
                entity = await client.get_entity(channel)
            except ValueError as exc:
                raise RecipientBlocked(f"Cannot resolve channel: {channel}") from exc
            await asyncio.sleep(self._min_read_interval)
            messages = await client.get_messages(entity, min_id=min_id, limit=limit)
        result: list[dict[str, Any]] = []
        for message in messages:
            text = (message.message or "").strip()
            if skip_empty and not text:
                continue
            result.append({"message_id": message.id, "text": text,
                           "date": message.date.isoformat() if message.date else None,
                           "channel": channel})
        return result

    async def join_channel(self, *, channel: str) -> bool:
        """Join a public channel, returning True if already joined."""
        client = self._require_client()
        async with self._guard():
            await asyncio.sleep(self._min_join_interval)
            try:
                entity = await client.get_entity(channel)
                await client(JoinChannelRequest(entity))
                return True
            except UserAlreadyParticipantError:
                return True
            except (ChannelPrivateError, ValueError) as exc:
                logger.warning("join_channel failed for %s: %s", channel, exc)
                return False
            except RPCError as exc:
                logger.warning("join_channel RPC failed for %s: %s", channel, exc)
                return False

    async def leave_channel(self, *, channel: str) -> bool:
        """Leave a channel, returning True if already left."""
        client = self._require_client()
        async with self._guard():
            await asyncio.sleep(self._min_join_interval)
            try:
                entity = await client.get_entity(channel)
                await client(LeaveChannelRequest(entity))
                return True
            except UserNotParticipantError:
                return True
            except (ChannelPrivateError, ValueError) as exc:
                logger.warning("leave_channel failed for %s: %s", channel, exc)
                return False
            except RPCError as exc:
                logger.warning("leave_channel RPC failed for %s: %s", channel, exc)
                return False

    async def get_channel_info(self, *, channel: str) -> dict[str, Any] | None:
        """Return channel or user metadata, or None if it cannot be resolved."""
        client = self._require_client()
        async with self._guard():
            try:
                entity = await client.get_entity(channel)
            except (ValueError, RPCError) as exc:
                logger.warning("get_channel_info failed for %s: %s", channel, exc)
                return None
        if isinstance(entity, Channel):
            participants: int | None = None
            try:
                full = await client(GetFullChannelRequest(entity))
                participants = full.full_chat.participants_count
            except RPCError:
                pass
            return {"kind": "channel", "id": entity.id, "title": entity.title,
                    "username": entity.username, "participants": participants,
                    "is_megagroup": getattr(entity, "megagroup", False)}
        if isinstance(entity, User):
            return {"kind": "user", "id": entity.id, "title": entity.first_name,
                    "username": entity.username}
        return None

    async def get_self_info(self) -> dict[str, Any]:
        """Return the logged-in user's identity."""
        me = await self._require_client().get_me()
        return {"id": me.id, "username": me.username,
                "first_name": me.first_name, "phone": me.phone}


class TelegramTools:
    """Combined Bot API and MTProto tools for the agent."""

    def __init__(self, config: TelegramConfig, *,
                 bot_client: BotClient | None = None,
                 user_client: UserClient | None = None) -> None:
        self._config = config
        self.bot = bot_client or BotClient(config)
        self.user = user_client or UserClient(config)
        self._started = False
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        async with self._lock:
            if self._started:
                return
            bot_started = False
            try:
                if self._config.bot_enabled:
                    await self.bot.start()
                    bot_started = True
                if self._config.user_client_enabled:
                    await self.user.start()
                self._started = True
                logger.info("TelegramTools started")
            except Exception:
                if bot_started:
                    await self.bot.stop()
                raise

    async def stop(self) -> None:
        async with self._lock:
            if not self._started:
                return
            try:
                if self._config.user_client_enabled:
                    await self.user.stop()
            finally:
                if self._config.bot_enabled:
                    await self.bot.stop()
                self._started = False
                logger.info("TelegramTools stopped")

    async def __aenter__(self) -> "TelegramTools":
        await self.start()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.stop()

    async def reply_to_owner(self, *, text: str, photo_path: str | None = None,
                             caption: str | None = None,
                             parse_mode: str | None = "HTML") -> int:
        """Deliver caller-provided content to the primary configured owner."""
        if not self._config.owner_ids:
            raise TelegramToolError("No owner configured")
        owner = self._config.owner_ids[0]
        if photo_path:
            return await self.bot.send_photo(chat_id=owner, photo_path=photo_path,
                                             caption=caption or "", parse_mode=parse_mode)
        return await self.bot.send_text(chat_id=owner, text=text, parse_mode=parse_mode)

    async def publish(self, *, text: str | None = None,
                      photo_path: str | None = None, caption: str | None = None,
                      parse_mode: str | None = "HTML") -> int:
        """Publish exactly one of text or photo to the configured target."""
        target = self._config.target_channel
        if not target:
            raise TelegramToolError("TARGET_CHANNEL not set")
        if bool(text and text.strip()) == bool(photo_path):
            raise InvalidContent("Provide exactly one of text or photo_path")
        if photo_path:
            return await self.bot.send_photo(chat_id=target, photo_path=photo_path,
                                             caption=caption or "", parse_mode=parse_mode)
        return await self.bot.send_text(chat_id=target, text=text or "",
                                        parse_mode=parse_mode)

    async def broadcast_owners(self, *, text: str,
                               parse_mode: str | None = "HTML") -> list[int]:
        """Send caller-provided text to owners; skip individual failures."""
        results: list[int] = []
        for owner_id in self._config.owner_ids:
            try:
                results.append(await self.bot.send_text(
                    chat_id=owner_id, text=text, parse_mode=parse_mode
                ))
            except TelegramToolError:
                logger.exception("broadcast failed for owner %s", owner_id)
        return results

    async def read_sources(self, *, channels: list[str],
                           min_ids: dict[str, int] | None = None,
                           limit: int = 100) -> list[dict[str, Any]]:
        """Read multiple source channels without failing the whole batch."""
        collected: list[dict[str, Any]] = []
        for channel in channels:
            try:
                collected.extend(await self.user.read_channel(
                    channel=channel, min_id=(min_ids or {}).get(channel, 0), limit=limit
                ))
            except TelegramToolError as exc:
                logger.warning("read_sources skipped %s: %s", channel, exc)
        return collected

    async def health(self) -> dict[str, Any]:
        """Report running state and available configuration."""
        return {"bot_running": self.bot.is_running,
                "user_running": self.user.is_running,
                "owners_configured": len(self._config.owner_ids),
                "target_channel_set": bool(self._config.target_channel)}
