from __future__ import annotations

from typing import Any


class PoemAnalyzer:
    """Analyzes poem content for theme, emotion, language, and quality hints."""

    @staticmethod
    def analyze(poem_text: str) -> dict[str, Any]:
        text = poem_text.strip()
        lowered = text.lower()
        category = "general"
        if any(word in lowered for word in ("ချစ်", "love", "အချစ်")):
            category = "love"
        elif any(word in lowered for word in ("တောင်", "သစ်ပင်", "ပန်း", "nature", "tree")):
            category = "nature"
        elif any(word in lowered for word in ("အား", "မိုး", "hope", "မင်္ဂလာ")):
            category = "motivation"

        emotion = "neutral"
        if any(word in lowered for word in ("မေတ္တာ", "joy", "ပျော်", "မင်္ဂလာ")):
            emotion = "joy"
        elif any(word in lowered for word in ("စိတ်မကောင်း", "sad", "ဝမ်းနည်း", "ဆင်းရဲ")):
            emotion = "sorrow"
        elif any(word in lowered for word in ("လွမ်း", "longing", "အိပ်မက်")):
            emotion = "longing"

        themes = []
        for token in ["love", "nature", "hope", "loneliness", "peace", "memory", "အချစ်", "လွမ်း"]:
            if token in lowered:
                themes.append(token)
        if not themes:
            themes.append("general")

        quality_score = 75
        if len(text.split()) > 20:
            quality_score += 10
        if len(text.split()) < 8:
            quality_score -= 10

        return {
            "category": category,
            "emotion": emotion,
            "themes": themes[:4],
            "quality_score": max(0, min(100, quality_score)),
            "language": "my" if any(ch in "အကရစသဟမင်း" for ch in text) else "en",
            "reasoning": "Heuristic analysis based on visible mood and recurring word patterns.",
        }
