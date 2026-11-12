"""Small, dependency-free poem analysis and duplicate helpers."""

from __future__ import annotations

import hashlib
import re
from typing import Any


def content_hash(text: str) -> str:
    normalized = " ".join(text.casefold().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def analyze_poem(text: str) -> dict[str, Any]:
    body = text.strip()
    if not body:
        raise ValueError("Poem cannot be empty")
    lowered = body.casefold()
    category, emotion = "general", "neutral"
    signals = {
        "love": ("အချစ်", "ချစ်", "love", "နှလုံးသား"),
        "nature": ("ပန်း", "တောင်", "သစ်ပင်", "မိုး", "nature"),
        "hope": ("မျှော်လင့်", "အနာဂတ်", "hope", "အောင်မြင်"),
        "sadness": ("ဝမ်းနည်း", "လွမ်း", "အထီးကျန်", "sad", "sorrow"),
    }
    for label, words in signals.items():
        if any(word in lowered for word in words):
            category = label
            break
    if any(word in lowered for word in ("ပျော်", "ရယ်မော", "joy", "ပျော်ရွှင်")):
        emotion = "joy"
    elif any(word in lowered for word in ("ဝမ်းနည်း", "လွမ်း", "sad", "ငို")):
        emotion = "sorrow"
    elif any(word in lowered for word in ("မျှော်လင့်", "မျှော်လင့်", "hope")):
        emotion = "hope"
    elif any(word in lowered for word in ("ငြိမ်းချမ်း", "အေးချမ်း", "peace")):
        emotion = "peace"
    has_myanmar = bool(re.search(r"[\u1000-\u109f]", body))
    has_latin = bool(re.search(r"[A-Za-z]", body))
    language = "mixed" if has_myanmar and has_latin else "my" if has_myanmar else "en"
    lines = [line for line in body.splitlines() if line.strip()]
    score = min(100, max(35, 55 + min(len(lines), 8) * 4))
    return {"category": category, "emotion": emotion, "language": language,
            "themes": [category], "quality_score": score,
            "note": "Heuristic estimate; owner should review."}
