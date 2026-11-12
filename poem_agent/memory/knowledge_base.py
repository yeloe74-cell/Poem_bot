from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class KnowledgeEntry:
    key: str
    body: str
    source: str | None = None


class KnowledgeBase:
    """Knowledge base for research, policies, and reusable channel guidance."""

    def __init__(self, root: str | Path = "./data/knowledge") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.entries: dict[str, KnowledgeEntry] = {}

    def add(self, key: str, body: str, *, source: str | None = None) -> None:
        self.entries[key] = KnowledgeEntry(key=key, body=body, source=source)

    def search(self, query: str, limit: int = 5) -> list[KnowledgeEntry]:
        lowered = query.lower()
        filtered = []
        for entry in self.entries.values():
            if lowered in entry.body.lower():
                filtered.append(entry)
        return filtered[:limit]
