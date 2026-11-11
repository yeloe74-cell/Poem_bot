"""collector.py — The Agent's Eyes.

Collects structured poem candidates from source channels through telegram_client.
It does not call AI, persist data, or decide whether a poem is good.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from telegram_client import UserClient, TelegramToolError

logger = logging.getLogger(__name__)

_MIN_POEM_CHARS = 20
_MAX_POEM_CHARS = 4000
_MIN_LINES = 2
_MAX_BATCH_SIZE = 500

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_TG_LINK_RE = re.compile(r"(?:t\.me|telegram\.me)/\S+", re.IGNORECASE)
_MENTION_RE = re.compile(r"@\w+")
_EMOJI_ONLY_RE = re.compile(r"^[\U0001F300-\U0001FAFF\s]+$")
_HASHTAG_ONLY_LINE = re.compile(r"^#\w+(\s+#\w+)*\s*$")


@dataclass(frozen=True, slots=True)
class PoemCandidate:
    """A collected message, before any AI analysis."""

    channel: str
    message_id: int
    text: str
    content_hash: str
    line_count: int
    date_iso: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "message_id": self.message_id,
            "text": self.text,
            "content_hash": self.content_hash,
            "line_count": self.line_count,
            "date_iso": self.date_iso,
        }


@dataclass(slots=True)
class ScanState:
    """Per-channel progress supplied by the caller and persisted externally."""

    channel: str
    last_message_id: int = 0


@dataclass(slots=True)
class CollectResult:
    """Aggregate result from a collection pass."""

    candidates: list[PoemCandidate] = field(default_factory=list)
    new_state: dict[str, int] = field(default_factory=dict)
    skipped_duplicate: int = 0
    skipped_short: int = 0
    skipped_url: int = 0
    skipped_hashtag: int = 0
    skipped_other: int = 0
    errors: dict[str, str] = field(default_factory=dict)


def normalize_text(raw: str) -> str:
    """Trim and normalize whitespace while preserving poetic line breaks."""
    text = raw.replace("\r\n", "\n").replace("\r", "\n").strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)


def hash_poem(text: str) -> str:
    """Return a stable hash insensitive to case and whitespace differences."""
    normalized = re.sub(r"\s+", " ", text).strip().casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _is_mostly_url(text: str) -> bool:
    """Return whether the message has almost no content after links are removed."""
    stripped = _URL_RE.sub("", text)
    stripped = _TG_LINK_RE.sub("", stripped)
    return len(stripped.strip()) < 15


def _is_emoji_only(text: str) -> bool:
    return bool(_EMOJI_ONLY_RE.fullmatch(text.strip()))


def _is_hashtag_only(text: str) -> bool:
    """Reject messages containing only hashtag and mention lines."""
    for line in text.split("\n"):
        line = line.strip()
        if not line or _HASHTAG_ONLY_LINE.fullmatch(line):
            continue
        if not _MENTION_RE.sub("", line).strip():
            continue
        return False
    return True


def _looks_like_poem(text: str) -> tuple[bool, str | None]:
    """Apply inexpensive candidate filters; AI performs actual poem analysis."""
    if len(text) < _MIN_POEM_CHARS:
        return False, "too_short"
    if _is_mostly_url(text):
        return False, "url_only"
    if _is_emoji_only(text):
        return False, "emoji_only"
    if _is_hashtag_only(text):
        return False, "hashtag_only"
    if sum(bool(line.strip()) for line in text.split("\n")) < _MIN_LINES:
        return False, "single_line"
    return True, None


class Collector:
    """Stateless scanning interface with an in-memory content-hash cache."""

    def __init__(
        self,
        user_client: UserClient,
        *,
        batch_size: int = 100,
        per_channel_delay: float = 1.0,
        seen_hashes: Sequence[str] = (),
    ) -> None:
        if not 1 <= batch_size <= _MAX_BATCH_SIZE:
            raise ValueError(f"batch_size must be 1-{_MAX_BATCH_SIZE}")
        if per_channel_delay < 0:
            raise ValueError("per_channel_delay cannot be negative")
        self._user = user_client
        self._batch_size = batch_size
        self._delay = per_channel_delay
        self._seen_hashes: set[str] = set(seen_hashes)

    async def scan_all(
        self,
        *,
        channels: Sequence[str],
        states: Mapping[str, int] | None = None,
        limit_per_channel: int | None = None,
    ) -> CollectResult:
        """Scan configured channels and return candidates plus updated cursors."""
        states = states or {}
        per_limit = self._batch_size if limit_per_channel is None else limit_per_channel
        if not 1 <= per_limit <= _MAX_BATCH_SIZE:
            raise ValueError(f"limit_per_channel must be 1-{_MAX_BATCH_SIZE}")
        result = CollectResult()

        for channel in channels:
            state = states.get(channel, 0)
            if state < 0:
                raise ValueError(f"State for {channel!r} cannot be negative")
            try:
                messages = await self._user.read_channel(
                    channel=channel,
                    min_id=state,
                    limit=per_limit,
                )
            except asyncio.CancelledError:
                raise
            except (TelegramToolError, ValueError) as exc:
                logger.warning("Scan failed for %s: %s", channel, exc)
                result.errors[channel] = str(exc)
                continue
            except Exception as exc:
                # Preserve a per-channel failure without hiding cancellation.
                logger.exception("Unexpected scan failure for %s", channel)
                result.errors[channel] = str(exc)
                continue

            self._process_channel(channel, messages, result)
            message_ids = [
                int(message["message_id"])
                for message in messages
                if message.get("message_id") is not None
            ]
            result.new_state[channel] = max(message_ids, default=state)
            if self._delay and channel != channels[-1]:
                await asyncio.sleep(self._delay)

        return result

    async def scan_one(
        self,
        *,
        channel: str,
        state: int = 0,
        limit: int | None = None,
    ) -> CollectResult:
        """Scan one channel."""
        return await self.scan_all(
            channels=[channel],
            states={channel: state},
            limit_per_channel=limit,
        )

    def _process_channel(
        self,
        channel: str,
        messages: list[dict[str, Any]],
        result: CollectResult,
    ) -> None:
        for message in messages:
            raw = message.get("text", "")
            if not isinstance(raw, str):
                result.skipped_other += 1
                continue
            text = normalize_text(raw)
            is_candidate, reason = _looks_like_poem(text)
            if not is_candidate:
                if reason == "too_short":
                    result.skipped_short += 1
                elif reason == "url_only":
                    result.skipped_url += 1
                elif reason == "hashtag_only":
                    result.skipped_hashtag += 1
                else:
                    result.skipped_other += 1
                continue

            if len(text) > _MAX_POEM_CHARS:
                text = text[:_MAX_POEM_CHARS].rstrip()
            content_hash = hash_poem(text)
            if content_hash in self._seen_hashes:
                result.skipped_duplicate += 1
                continue

            try:
                message_id = int(message["message_id"])
            except (KeyError, TypeError, ValueError):
                result.skipped_other += 1
                continue
            self._seen_hashes.add(content_hash)
            result.candidates.append(
                PoemCandidate(
                    channel=channel,
                    message_id=message_id,
                    text=text,
                    content_hash=content_hash,
                    line_count=sum(bool(line.strip()) for line in text.split("\n")),
                    date_iso=message.get("date"),
                )
            )

    def seed_hashes(self, hashes: Sequence[str]) -> None:
        """Seed known hashes, for example from persisted database records."""
        self._seen_hashes.update(hashes)

    def clear_hashes(self) -> None:
        """Clear the in-memory hash cache, primarily for tests."""
        self._seen_hashes.clear()

    @property
    def known_hash_count(self) -> int:
        return len(self._seen_hashes)
