from __future__ import annotations

from typing import Any


class PoemSelector:
    """Selects the highest-quality poems while avoiding repetition."""

    def __init__(self) -> None:
        self.selected_ids: set[str] = set()

    def choose(self, candidates: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
        ranked = sorted(candidates, key=lambda item: item.get("quality_score", 0), reverse=True)
        chosen: list[dict[str, Any]] = []
        for candidate in ranked:
            key = str(candidate.get("poem_id") or candidate.get("text", "")).casefold()
            if key in self.selected_ids:
                continue
            self.selected_ids.add(key)
            chosen.append(candidate)
            if len(chosen) >= limit:
                break
        return chosen
