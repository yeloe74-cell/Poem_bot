from __future__ import annotations


class CreditManager:
    """Keeps source attribution and author credit information for poem publication."""

    def __init__(self) -> None:
        self.credits: dict[str, str] = {}

    def set_credit(self, poem_id: str, source: str, author: str | None = None) -> None:
        label = f"Author: {author}" if author else "Unknown author"
        self.credits[poem_id] = f"{source} — {label}"

    def get_credit(self, poem_id: str) -> str:
        return self.credits.get(poem_id, "Unknown source")
