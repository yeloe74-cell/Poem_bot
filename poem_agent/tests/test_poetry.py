from poem_agent.poetry.poem_analyzer import analyze_poem, content_hash


def test_analyzer_handles_burmese_poem():
    result = analyze_poem("ပန်းကလေးတွေ ပွင့်လန်းနေတယ်\nမိုးအောက်မှာ အချစ်တွေ ရှင်သန်တယ်")
    assert result["language"] == "my"
    assert result["category"] == "love"
    assert 0 <= result["quality_score"] <= 100


def test_hash_ignores_whitespace_and_case():
    assert content_hash("Hello   WORLD") == content_hash("hello world")
