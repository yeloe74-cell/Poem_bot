from __future__ import annotations

import math


class DuplicateChecker:
    """Checks whether two poems are likely duplicates or near-duplicates."""

    @staticmethod
    def normalize(text: str) -> str:
        return " ".join(text.lower().split())

    @staticmethod
    def similarity(a: str, b: str) -> float:
        ta = DuplicateChecker.normalize(a).split()
        tb = DuplicateChecker.normalize(b).split()
        if not ta or not tb:
            return 0.0
        overlap = len(set(ta) & set(tb))
        union = len(set(ta) | set(tb))
        if not union:
            return 0.0
        return overlap / union

    def is_duplicate(self, a: str, b: str, threshold: float = 0.75) -> bool:
        return self.similarity(a, b) >= threshold
