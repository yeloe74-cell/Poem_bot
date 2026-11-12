from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from poem_agent.config.prompts import CAPTION_PROMPT, INTENT_PARSE_PROMPT, POEM_ANALYSIS_PROMPT
from poem_agent.core.model_router import ModelRouter


@dataclass
class AIResponse:
    success: bool
    data: dict[str, Any]
    raw_text: str = ""


class AIBrain:
    """Wrapper around model selection and local fallback logic."""

    def __init__(self, model_router: ModelRouter | None = None) -> None:
        self.model_router = model_router or ModelRouter()

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any]:
        payload = text.strip()
        if payload.startswith("```"):
            payload = re.sub(r"^```(?:json)?\s*", "", payload)
            payload = re.sub(r"\s*```$", "", payload)
        start = payload.find("{")
        end = payload.rfind("}")
        if start == -1 or end < start:
            return {"result": payload}
        try:
            return json.loads(payload[start : end + 1])
        except json.JSONDecodeError:
            return {"result": payload}

    def analyze_poem(self, poem_text: str) -> AIResponse:
        route = self.model_router.route("poetry-analysis")
        text = poem_text.strip()
        if not text:
            return AIResponse(False, {"error": "Empty poem"}, "")

        result = {
            "category": "general",
            "emotion": "neutral",
            "themes": ["poetry"],
            "quality_score": 75,
            "language": "my" if any(ch in "အကရစသဟ" for ch in text) else "en",
            "reasoning": "Fallback heuristic analysis used because no external model was configured.",
        }
        if "ချစ်" in text or "love" in text.lower():
            result["category"] = "love"
        if "တောင်" in text or "tree" in text.lower() or "ပန်း" in text.lower():
            result["category"] = "nature"
        if "မုန်း" in text or "angry" in text.lower():
            result["emotion"] = "anger"
        elif "ဆိုး" in text or "sad" in text.lower() or "စိတ်ပျက်" in text.lower():
            result["emotion"] = "sorrow"
        elif "မေတ္တာ" in text or "hope" in text.lower() or "ခေါင်း" in text.lower():
            result["emotion"] = "hope"
        return AIResponse(True, result, POEM_ANALYSIS_PROMPT)

    def parse_intent(self, message: str) -> AIResponse:
        payload = {
            "action": "unknown",
            "poem_text": message.strip() if message.strip() else None,
            "author": None,
            "target_id": None,
            "parameters": {},
            "confidence": 0.6,
        }
        lower = message.lower()
        if "တင်" in message or "post" in lower:
            payload["action"] = "post_poem"
        elif "ဖျက်" in message or "reject" in lower or "မတင်" in message:
            payload["action"] = "reject_poem"
        elif "ပြင်" in message or "edit" in lower or "improve" in lower:
            payload["action"] = "edit_poem"
        elif "နောက်မှ" in message or "schedule" in lower:
            payload["action"] = "schedule_poem"
        elif "approve" in lower or "အတည်ပြု" in message:
            payload["action"] = "approve_draft"
        return AIResponse(True, payload, INTENT_PARSE_PROMPT)

    def generate_caption(self, poem_text: str, author: str | None = None) -> AIResponse:
        caption = poem_text.strip()
        if author:
            caption = f"{caption}\n\n#{author.strip() or 'Unknown'}"
        return AIResponse(True, {"caption": caption}, CAPTION_PROMPT)
