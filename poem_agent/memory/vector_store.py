from __future__ import annotations

import math
from typing import Iterable


class VectorStore:
    """Simple vector store for semantic retrieval using bag-of-words embeddings."""

    def __init__(self) -> None:
        self.documents: dict[str, dict[str, float]] = {}

    def add_document(self, doc_id: str, text: str) -> None:
        tokens = self._tokenize(text)
        vector = {token: float(count) for token, count in tokens.items()}
        self.documents[doc_id] = vector

    @staticmethod
    def _tokenize(text: str) -> dict[str, int]:
        words = [word.lower() for word in text.replace("\n", " ").split() if word.isalnum()]
        counts: dict[str, int] = {}
        for word in words:
            counts[word] = counts.get(word, 0) + 1
        return counts

    @staticmethod
    def _dot(a: dict[str, float], b: dict[str, float]) -> float:
        return sum(a.get(key, 0.0) * b.get(key, 0.0) for key in set(a) | set(b))

    def similarity(self, a: str, b: str) -> float:
        va = self._tokenize(a)
        vb = self._tokenize(b)
        dot = self._dot({k: float(v) for k, v in va.items()}, {k: float(v) for k, v in vb.items()})
        mag_a = math.sqrt(sum(v * v for v in va.values()))
        mag_b = math.sqrt(sum(v * v for v in vb.values()))
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot / (mag_a * mag_b)

    def search(self, query: str, limit: int = 5) -> list[tuple[str, float]]:
        scores: list[tuple[str, float]] = []
        for doc_id, vector in self.documents.items():
            scores.append((doc_id, self.similarity(query, doc_id)))
        scores.sort(key=lambda item: item[1], reverse=True)
        return scores[:limit]
