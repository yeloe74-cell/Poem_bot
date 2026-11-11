"""ai_brain.py — Complete AI Brain for Poem Bot.

Supports automatic collection and owner-managed poem workflows.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

import httpx

from config import AIConfig

logger = logging.getLogger(__name__)


class PoemCategory(str, Enum):
    LOVE = "love"
    NATURE = "nature"
    MOTIVATION = "motivation"
    SADNESS = "sadness"
    PATRIOTIC = "patriotic"
    SPIRITUAL = "spiritual"
    GENERAL = "general"


class PoemEmotion(str, Enum):
    JOY = "joy"
    SORROW = "sorrow"
    LONGING = "longing"
    ANGER = "anger"
    PEACE = "peace"
    HOPE = "hope"
    NEUTRAL = "neutral"


class Language(str, Enum):
    MYANMAR = "my"
    ENGLISH = "en"
    MIXED = "mixed"


@dataclass(frozen=True, slots=True)
class PoemAnalysis:
    category: PoemCategory
    emotion: PoemEmotion
    quality_score: int
    language: Language
    themes: tuple[str, ...]
    reasoning: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category.value,
            "emotion": self.emotion.value,
            "quality_score": self.quality_score,
            "language": self.language.value,
            "themes": list(self.themes),
            "reasoning": self.reasoning,
        }


@dataclass(frozen=True, slots=True)
class OwnerIntent:
    """Parsed owner command supporting both bot workflows."""
    action: str
    poem_text: str | None = None
    author: str | None = None
    target_id: str | None = None
    parameters: Mapping[str, Any] = field(default_factory=dict)
    confidence: float = 0.0


@dataclass(frozen=True, slots=True)
class EngagementScore:
    score: int
    factors: Mapping[str, str]
    suggestion: str

    def to_dict(self) -> dict[str, Any]:
        return {"score": self.score, "factors": dict(self.factors),
                "suggestion": self.suggestion}


@dataclass(frozen=True, slots=True)
class EditResult:
    """Result returned by edit_poem()."""
    original: str
    edited: str
    changes: tuple[str, ...]
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return {"original": self.original, "edited": self.edited,
                "changes": list(self.changes), "explanation": self.explanation}


class AIError(RuntimeError):
    """Base error for AI service failures."""


class AIResponseError(AIError):
    """Raised when the AI service returns an unusable response."""


_ANALYSIS_SYSTEM = """You are a Myanmar poetry expert AI.

Analyze the poem. Return ONLY valid JSON:
{
  "category": "love|nature|motivation|sadness|patriotic|spiritual|general",
  "emotion": "joy|sorrow|longing|anger|peace|hope|neutral",
  "quality_score": 0-100,
  "language": "my|en|mixed",
  "themes": ["theme1", "theme2"],
  "reasoning": "brief English explanation"
}
No markdown. JSON only."""

_CAPTION_SYSTEM = """You format Telegram posts for Myanmar poetry.

Output EXACTLY this format:

<poem text>

#<author name>

Rules:
- NO category hashtags like #အချစ်ကဗျာ
- NO "Source:" lines
- NO emojis
- NO commentary
- Preserve poem line breaks
- If no author, use #Unknown
- Return ONLY the formatted text. No JSON. No fences."""

_INTENT_SYSTEM = """Parse owner command for a Telegram poetry bot.

The bot has TWO flows:

FLOW A — AUTO COLLECT (channels → preview → owner approves):
  - approve_draft: approve pending draft
  - reject_draft: reject pending draft
  - list_pending: list pending drafts
  - status: show bot status
  - add_channel: add source channel
  - remove_channel: disable source channel

FLOW B — OWNER MANUAL (owner writes own poem):
  - post_poem: post owner's poem now
  - reject_poem: discard owner's poem
  - edit_poem: AI improves the poem
  - review_poem: AI gives feedback (no change)
  - schedule_poem: schedule for later

Return ONLY valid JSON:
{
  "action": "...",
  "poem_text": "extracted poem if present, else null",
  "author": "author name if present, else null",
  "target_id": "optional draft/channel id",
  "parameters": {},
  "confidence": 0.0-1.0
}

Rules:
- Myanmar and English both supported
- "တင်ပေး" / "post this" / "တင်လိုက်" → post_poem
- "ပယ်" / "reject this" / "မတင်ဘူး" → reject_poem
- "ပြင်" / "edit" / "improve" → edit_poem
- "ဘယ်လိုလဲ" / "review" / "သုံးသပ်" → review_poem
- "နောက်မှတင်" / "schedule" → schedule_poem
- If a full poem is present + clear command → extract poem_text
- If ONLY a full poem (no command) → post_poem
- Confidence < 0.5 → use "unknown"
- No markdown. JSON only."""

_IMAGE_RELEVANCE_SYSTEM = """Judge whether an image fits a poem.

Return ONLY valid JSON:
{
  "relevant": true|false,
  "score": 0-100,
  "reason": "brief English explanation",
  "suggested_keywords": ["kw1", "kw2"]
}
Score 80+: perfect. 50-79: acceptable. <50: mismatch.
No markdown. JSON only."""

_KEYWORD_SYSTEM = """Generate English image search keywords for poetry.

Return ONLY valid JSON:
{"keywords": ["keyword1", "keyword2", ...]}

Rules:
- English only, 2-4 words each
- Visual, mood, or object based
- Suitable for Unsplash/Pexels/Wikimedia
- No markdown. JSON only."""

_LANGUAGE_SYSTEM = """Detect language of the given text.

Return ONLY valid JSON:
{"language": "my|en|mixed"}

Rules:
- "my" if mostly Myanmar
- "en" if mostly English
- "mixed" if both significant
- No markdown. JSON only."""

_DEDUP_SYSTEM = """Compare two poems for semantic similarity.

Return ONLY valid JSON:
{"similarity": 0.0-1.0, "reason": "brief"}

Rules:
- 1.0 = identical meaning
- 0.9+ = near duplicate
- 0.7-0.89 = similar theme, different wording
- <0.7 = different poems
- No markdown. JSON only."""

_TRANSLATE_SYSTEM = """Translate Myanmar poetry to English or vice versa.

Return ONLY valid JSON:
{"translation": "translated text", "source_language": "my|en"}

Rules:
- Preserve poetic tone and emotion
- Keep line structure
- Do NOT transliterate
- No markdown. JSON only."""

_ENGAGEMENT_SYSTEM = """Score a poem's engagement potential for Telegram.

Return ONLY valid JSON:
{
  "score": 0-100,
  "factors": {
    "emotional_peak": "low|medium|high",
    "opening_hook": "weak|ok|strong",
    "shareability": "low|medium|high",
    "length": "short|optimal|long"
  },
  "suggestion": "best posting time or channel type"
}
No markdown. JSON only."""

_EDIT_SYSTEM = """You are a Myanmar poetry editor.

Improve the poem while preserving the author's voice and theme.

Return ONLY valid JSON:
{
  "edited": "the improved poem text with original line breaks",
  "changes": ["change1", "change2"],
  "explanation": "brief English explanation of what changed and why"
}

Rules:
- Preserve original meaning and emotion
- Keep the author's style
- Improve rhythm, imagery, word choice
- Do NOT add new stanzas
- Do NOT change the theme
- Keep line count similar (±1 line)
- No markdown. JSON only."""

_REVIEW_SYSTEM = """You are a Myanmar poetry critic.

Give honest, constructive feedback. Do NOT rewrite the poem.

Return ONLY valid JSON:
{
  "strengths": ["strength1", "strength2"],
  "weaknesses": ["weak1", "weak2"],
  "suggestions": ["sug1", "sug2"],
  "overall": "brief English summary"
}

Rules:
- Focus on imagery, rhythm, emotion, originality
- Be specific, not generic
- Myanmar and English feedback both OK
- No markdown. JSON only."""


class AIBrain:
    """Async AI client for the Poem Bot's automatic and owner workflows."""

    def __init__(self, config: AIConfig) -> None:
        config.validate()
        self.config = config
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> "AIBrain":
        await self._ensure_client()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    async def _ensure_client(self) -> httpx.AsyncClient:
        async with self._lock:
            if self._client is None or self._client.is_closed:
                self._client = httpx.AsyncClient(
                    base_url=self.config.base_url or "https://openrouter.ai/api/v1",
                    headers={
                        "Authorization": f"Bearer {self.config.api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://github.com/poem-bot",
                        "X-Title": "Poem Bot",
                    },
                    timeout=httpx.Timeout(self.config.timeout),
                )
            return self._client

    async def close(self) -> None:
        async with self._lock:
            if self._client and not self._client.is_closed:
                await self._client.aclose()
            self._client = None

    async def _chat(
        self,
        *,
        system: str,
        user: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Send a chat completion request with bounded retries."""
        client = await self._ensure_client()
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature if temperature is not None else self.config.temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.config.max_tokens,
        }
        last_error: Exception | None = None
        for attempt in range(self.config.retries + 1):
            try:
                response = await client.post("/chat/completions", json=payload)
                if response.status_code == 429:
                    last_error = AIError("AI service rate limited the request")
                    if attempt < self.config.retries:
                        await asyncio.sleep(2 ** attempt)
                    continue
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                if not isinstance(content, str) or not content.strip():
                    raise AIResponseError("Empty AI response")
                return content.strip()
            except httpx.TimeoutException as exc:
                last_error = exc
                if attempt < self.config.retries:
                    await asyncio.sleep(2 ** attempt)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code >= 500:
                    last_error = exc
                    if attempt < self.config.retries:
                        await asyncio.sleep(2 ** attempt)
                    continue
                raise AIError(f"HTTP {exc.response.status_code}") from exc
            except (KeyError, IndexError, TypeError) as exc:
                raise AIResponseError("Malformed AI response") from exc
            except httpx.RequestError as exc:
                last_error = exc
                if attempt < self.config.retries:
                    await asyncio.sleep(2 ** attempt)
        raise AIError("AI failed after retries") from last_error

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any]:
        """Extract a JSON object from plain or fenced model output."""
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise AIResponseError("No JSON object found")
        try:
            data = json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError as exc:
            raise AIResponseError(f"Invalid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise AIResponseError("JSON root is not an object")
        return data

    async def analyze_poem(self, poem_text: str) -> PoemAnalysis:
        text = poem_text.strip()
        if not text:
            raise ValueError("Poem text empty")
        raw = await self._chat(system=_ANALYSIS_SYSTEM,
                               user=f"Analyze:\n\n{text[:8000]}",
                               temperature=0.2, max_tokens=500)
        data = self._extract_json(raw)
        try:
            category = PoemCategory(data.get("category", "general"))
        except ValueError:
            category = PoemCategory.GENERAL
        try:
            emotion = PoemEmotion(data.get("emotion", "neutral"))
        except ValueError:
            emotion = PoemEmotion.NEUTRAL
        try:
            score = max(0, min(100, int(data.get("quality_score", 50))))
        except (TypeError, ValueError):
            score = 50
        try:
            language = Language(data.get("language", "my"))
        except ValueError:
            language = Language.MYANMAR
        themes_raw = data.get("themes", [])
        themes = (tuple(str(item).strip() for item in themes_raw[:4] if str(item).strip())
                  if isinstance(themes_raw, list) else ())
        return PoemAnalysis(category, emotion, score, language, themes,
                            str(data.get("reasoning", ""))[:500])

    async def generate_caption(self, poem_text: str, *, author: str | None = None) -> str:
        """Format a post as the poem followed by the author's hashtag."""
        text = poem_text.strip()
        if not text:
            raise ValueError("Poem empty")
        author_name = (author or "").strip() or "Unknown"
        raw = await self._chat(
            system=_CAPTION_SYSTEM,
            user=f"Poem:\n{text}\n\nAuthor: {author_name}",
            temperature=0.3,
            max_tokens=900,
        )
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```\w*\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        return cleaned.strip()

    async def parse_intent(self, message: str) -> OwnerIntent:
        """Parse an owner message into a validated structured intent."""
        text = message.strip()
        if not text:
            raise ValueError("Message empty")
        raw = await self._chat(system=_INTENT_SYSTEM,
                               user=f"Message:\n{text[:3000]}",
                               temperature=0.1, max_tokens=800)
        data = self._extract_json(raw)
        action = str(data.get("action", "unknown")).strip().lower()
        allowed = {
            "post_poem", "reject_poem", "edit_poem", "review_poem",
            "schedule_poem", "approve_draft", "reject_draft", "list_pending",
            "status", "add_channel", "remove_channel", "unknown",
        }
        if action not in allowed:
            action = "unknown"
        try:
            confidence = max(0.0, min(1.0, float(data.get("confidence", 0.0))))
        except (TypeError, ValueError):
            confidence = 0.0
        parameters = data.get("parameters", {})
        if not isinstance(parameters, dict):
            parameters = {}
        return OwnerIntent(
            action=action,
            poem_text=str(data.get("poem_text") or "").strip() or None,
            author=str(data.get("author") or "").strip() or None,
            target_id=str(data.get("target_id") or "").strip() or None,
            parameters=parameters,
            confidence=confidence,
        )

    async def check_image_relevance(
        self, poem_text: str, image_description: str, *, category: str = "general"
    ) -> dict[str, Any]:
        if not poem_text.strip() or not image_description.strip():
            raise ValueError("Poem and image description required")
        user = (f"Poem:\n{poem_text.strip()[:2000]}\n\n"
                f"Category: {category}\n\nImage: {image_description.strip()[:500]}")
        raw = await self._chat(system=_IMAGE_RELEVANCE_SYSTEM, user=user,
                               temperature=0.2, max_tokens=300)
        data = self._extract_json(raw)
        try:
            score = max(0, min(100, int(data.get("score", 0))))
        except (TypeError, ValueError):
            score = 0
        keywords_raw = data.get("suggested_keywords", [])
        keywords = ([str(item).strip() for item in keywords_raw[:4] if str(item).strip()]
                    if isinstance(keywords_raw, list) else [])
        return {"relevant": bool(data.get("relevant", score >= 50)),
                "score": score, "reason": str(data.get("reason", ""))[:300],
                "suggested_keywords": keywords}

    async def generate_image_keywords(
        self,
        poem_text: str,
        *,
        category: str = "general",
        emotion: str = "neutral",
        themes: Sequence[str] = (),
        count: int = 5,
    ) -> list[str]:
        if not poem_text.strip():
            raise ValueError("Poem empty")
        if not 1 <= count <= 10:
            raise ValueError("Count must be 1-10")
        theme_line = f"Themes: {', '.join(themes)}" if themes else ""
        user = (f"Poem:\n{poem_text.strip()[:2000]}\n\nCategory: {category}\n"
                f"Emotion: {emotion}\n{theme_line}\n\nGenerate {count} keywords.")
        raw = await self._chat(system=_KEYWORD_SYSTEM, user=user,
                               temperature=0.6, max_tokens=300)
        data = self._extract_json(raw)
        keywords = data.get("keywords", [])
        if not isinstance(keywords, list):
            return []
        result = []
        for item in keywords[:count]:
            keyword = str(item).strip().lower()
            if keyword and len(keyword) <= 60:
                result.append(keyword)
        return result

    async def detect_language(self, text: str) -> Language:
        if not text.strip():
            raise ValueError("Text empty")
        raw = await self._chat(system=_LANGUAGE_SYSTEM, user=f"Text:\n{text[:2000]}",
                               temperature=0.1, max_tokens=50)
        data = self._extract_json(raw)
        try:
            return Language(data.get("language", "my"))
        except ValueError:
            return Language.MYANMAR

    async def batch_analyze(
        self, poems: Sequence[str], *, concurrency: int = 5
    ) -> list[PoemAnalysis | None]:
        """Analyze poems concurrently; return None for individual failures."""
        if not poems:
            return []
        if not 1 <= concurrency <= 20:
            raise ValueError("Concurrency must be 1-20")
        semaphore = asyncio.Semaphore(concurrency)

        async def analyze_one(text: str) -> PoemAnalysis | None:
            async with semaphore:
                try:
                    return await self.analyze_poem(text)
                except (AIError, ValueError) as exc:
                    logger.warning("Batch item failed: %s", exc)
                    return None

        return await asyncio.gather(*(analyze_one(poem) for poem in poems))

    async def deduplicate_poems(
        self, poem_a: str, poem_b: str, *, threshold: float = 0.9
    ) -> dict[str, Any]:
        """Check whether two poems are near-duplicates."""
        if not poem_a.strip() or not poem_b.strip():
            raise ValueError("Both poems required")
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("Threshold must be 0-1")
        user = f"Poem A:\n{poem_a.strip()[:1500]}\n\nPoem B:\n{poem_b.strip()[:1500]}"
        raw = await self._chat(system=_DEDUP_SYSTEM, user=user,
                               temperature=0.1, max_tokens=150)
        data = self._extract_json(raw)
        try:
            similarity = max(0.0, min(1.0, float(data.get("similarity", 0.0))))
        except (TypeError, ValueError):
            similarity = 0.0
        return {"similarity": similarity, "is_duplicate": similarity >= threshold,
                "reason": str(data.get("reason", ""))[:200]}

    async def translate_poem(
        self, text: str, *, target: str | None = None
    ) -> dict[str, Any]:
        """Translate a poem between Myanmar and English."""
        if not text.strip():
            raise ValueError("Text empty")
        if target and target not in {"my", "en"}:
            raise ValueError("Target must be 'my' or 'en'")
        user = f"Translate:\n{text[:3000]}"
        if target:
            user += f"\n\nTarget language: {target}"
        raw = await self._chat(system=_TRANSLATE_SYSTEM, user=user,
                               temperature=0.3, max_tokens=1500)
        data = self._extract_json(raw)
        return {"translation": str(data.get("translation", "")).strip(),
                "source_language": str(data.get("source_language", "my"))[:5]}

    async def score_engagement_potential(self, poem_text: str) -> EngagementScore:
        if not poem_text.strip():
            raise ValueError("Poem empty")
        raw = await self._chat(system=_ENGAGEMENT_SYSTEM,
                               user=f"Score:\n{poem_text[:2000]}",
                               temperature=0.3, max_tokens=300)
        data = self._extract_json(raw)
        try:
            score = max(0, min(100, int(data.get("score", 0))))
        except (TypeError, ValueError):
            score = 0
        factors = data.get("factors", {})
        if not isinstance(factors, dict):
            factors = {}
        return EngagementScore(score=score,
                               factors={str(key): str(value)[:20]
                                        for key, value in factors.items()},
                               suggestion=str(data.get("suggestion", ""))[:200])

    async def edit_poem(
        self, poem_text: str, *, instruction: str | None = None
    ) -> EditResult:
        """Improve an owner's poem while preserving their voice."""
        text = poem_text.strip()
        if not text:
            raise ValueError("Poem empty")
        user = f"Poem:\n{text[:4000]}"
        if instruction:
            user += f"\n\nOwner's request: {instruction.strip()[:300]}"
        raw = await self._chat(system=_EDIT_SYSTEM, user=user,
                               temperature=0.5, max_tokens=1200)
        data = self._extract_json(raw)
        edited = str(data.get("edited", "")).strip() or text
        changes_raw = data.get("changes", [])
        changes = (tuple(str(item).strip() for item in changes_raw[:6] if str(item).strip())
                   if isinstance(changes_raw, list) else ())
        return EditResult(text, edited, changes,
                          str(data.get("explanation", ""))[:400])

    async def review_poem(self, poem_text: str) -> dict[str, Any]:
        """Give constructive feedback without rewriting the poem."""
        text = poem_text.strip()
        if not text:
            raise ValueError("Poem empty")
        raw = await self._chat(system=_REVIEW_SYSTEM,
                               user=f"Review:\n{text[:3000]}",
                               temperature=0.4, max_tokens=600)
        data = self._extract_json(raw)

        def string_list(key: str, limit: int = 5) -> list[str]:
            values = data.get(key, [])
            if not isinstance(values, list):
                return []
            return [str(value).strip() for value in values[:limit] if str(value).strip()]

        return {"strengths": string_list("strengths"),
                "weaknesses": string_list("weaknesses"),
                "suggestions": string_list("suggestions"),
                "overall": str(data.get("overall", ""))[:400]}

    async def health_check(self) -> bool:
        """Verify API reachability with a small request."""
        try:
            await self._chat(system="Reply exactly: OK", user="ping",
                             temperature=0, max_tokens=10)
            return True
        except AIError:
            return False
