from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PoemCandidate:
    channel: str
    message_id: int
    text: str
    date: str | None = None


class PoemCollector:
    """Collects likely poem messages from a source channel and filters obvious noise."""

    def __init__(self) -> None:
        self.seen_hashes: set[str] = set()

    @staticmethod
    def normalize(text: str) -> str:
        text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        return "\n".join(line.rstrip() for line in text.split("\n"))

    @staticmethod
    def looks_like_poem(text: str) -> bool:
        cleaned = text.strip()
        if len(cleaned) < 20:
            return False
        lines = [line for line in cleaned.split("\n") if line.strip()]
        if len(lines) < 2:
            return False
        return True

    def collect(self, channel: str, messages: list[dict[str, Any]]) -> list[PoemCandidate]:
        result: list[PoemCandidate] = []
        for raw in messages:
            text = raw.get("text", "")
            if not isinstance(text, str):
                continue
            cleaned = self.normalize(text)
            if not self.looks_like_poem(cleaned):
                continue
            key = cleaned.casefold()
            if key in self.seen_hashes:
                continue
            self.seen_hashes.add(key)
            result.append(PoemCandidate(channel=channel, message_id=int(raw.get("message_id", 0)), text=cleaned, date=raw.get("date")))
        return result
