from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class MemoryManager:
    """Persistent memory store for actions, events, and learning insights."""

    def __init__(self, storage_path: str | Path = "./data/memory.jsonl") -> None:
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

    def record_event(self, payload: dict[str, Any]) -> None:
        with self.storage_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def read_events(self) -> list[dict[str, Any]]:
        if not self.storage_path.exists():
            return []
        items: list[dict[str, Any]] = []
        with self.storage_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    try:
                        items.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return items
