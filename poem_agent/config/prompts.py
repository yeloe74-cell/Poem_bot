"""Reusable prompt fragments for the poem agent."""

POEM_ANALYSIS_PROMPT = """You are a poetry curator. Analyze the text and return a JSON object with: category, emotion, themes, quality_score, language, and reasoning.
"""

INTENT_PARSE_PROMPT = """You are parsing Telegram owner commands. Understand Burmese and English instructions such as 'တင်လိုက်', 'ဒီကဗျာကိုဖျက်', and 'မနက်ဖြန်တင်ဖို့စီစဉ်'.
Return a JSON object with action, poem_text, author, target_id, parameters, and confidence.
"""

CAPTION_PROMPT = """Create a Telegram post caption with the poem, author credit, and a respectful attribution line when needed.
"""

IMAGE_MATCH_PROMPT = """Match the poem's mood and theme to a suitable image description, using a safe and relevant search query.
"""

APPROVAL_PROMPT = """Review the draft carefully and only approve content that is safe, respectful, and aligned with the channel's mission.
"""
