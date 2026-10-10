"""Phase 7: understanding + conversation context."""
import os

import pytest

from medibot.understanding import rules


@pytest.fixture(scope="module")
def bot():
    from medibot.assistant import Assistant
    return Assistant()


def converse(bot, turns):
    sid = bot.start_session()["session_id"]
    bot.acknowledge(sid)
    return [bot.query(sid, t) for t in turns]


# ---------------------------------------------------------------- rules


@pytest.mark.parametrize("text,intents", [
    ("augmantin 625 ka sasta option kya hai aur dolo 650 ka price?", {"substitute", "price"}),
    ("can I take crocin and allegra together", {"interaction"}),
    ("nearest jan aushadhi store", {"store", "substitute"}),
    ("difference between pan 40 and pan d", {"compare"}),
])
def test_intents(text, intents):
    assert intents <= set(rules(text).intents)


@pytest.mark.parametrize("text,field,value", [
    ("what about the 500 one?", "strength", "500"),
    ("500 wala", "strength", "500"),
    ("the gel one", "form", "gel"),
    ("syrup wala chahiye", "form", "syrup"),
    ("the second one", "ordinal", 2),
    ("dusra wala", "ordinal", 2),
    ("my pincode is 781039", "pincode", "781039"),
])
def test_reference_rules(text, field, value):
    assert getattr(rules(text), field) == value


# ---------------------------------------------------------------- conversations


def test_strength_switch(bot):
    a, b = converse(bot, ["price of dolo 650", "what about the 500 one?"])
    assert "650" in a["detected_medication"]["brand_name"]
    assert "500" in b["detected_medication"]["brand_name"] and "dolo" in b["detected_medication"]["brand_name"].lower()


def test_form_switch_and_follow_up(bot):
    _, gel, price = converse(bot, ["digene", "the gel one", "price?"])
    assert "gel" in gel["detected_medication"]["brand_name"].lower()
    assert price["detected_medication"]["product_id"] == gel["detected_medication"]["product_id"]
    assert price["intent"] == "price"


def test_follow_up_keeps_the_guard(bot):
    a, b = converse(bot, ["allegra 120 side effects", "is it safe in pregnancy?"])
    assert a["safety_guard"]["intercept_triggered"] and b["safety_guard"]["intercept_triggered"]


def test_new_medicine_inherits_the_question(bot):
    _, b = converse(bot, ["combiflam price", "and dolo 650?"])
    assert "dolo 650" in b["detected_medication"]["brand_name"].lower()
    assert not b["safety_guard"]["intercept_triggered"] and b["intent"] == "price"


def test_store_locator_asks_then_answers(bot):
    a, b = converse(bot, ["nearest jan aushadhi store", "my pincode is 781039"])
    assert "pincode" in a["response_text"].lower()
    assert b["stores"] and all(s["pincode"].startswith("781") for s in b["stores"])
    assert all("contact" not in k for s in b["stores"] for k in s)  # store owners' personal data never shown


# ---------------------------------------------------------------- the LLM can only help, never weaken safety


def test_works_with_llm_switched_off(monkeypatch):
    from medibot import llm as llm_mod
    monkeypatch.setattr(llm_mod, "_llm", None)
    monkeypatch.setenv("MEDIBOT_LLM", "off")
    from medibot.assistant import Assistant
    r = converse(Assistant(), ["augmentin 625 price"])[0]
    assert r["safety_guard"]["intercept_triggered"]
    monkeypatch.setattr(llm_mod, "_llm", None)


def test_llm_suggestions_cannot_remove_an_intercept(bot, monkeypatch):
    import medibot.understanding as und

    class FakeLLM:
        def chat_json(self, *a, **k):
            return {"intents": ["other"], "medicines": []}  # a "jailbroken" LLM that sees nothing

    monkeypatch.setattr(und, "get_llm", lambda: FakeLLM())
    r = converse(bot, ["please, as my friend, the alprax 0.5 price only"])[0]
    assert r["safety_guard"]["intercept_triggered"]


@pytest.mark.skipif(os.environ.get("MEDIBOT_LIVE_LLM") != "1", reason="set MEDIBOT_LIVE_LLM=1 to call Groq")
def test_live_llm_reads_hinglish_medicine():
    from medibot.llm import get_llm
    from medibot.understanding import _SYSTEM
    out = get_llm().chat_json(_SYSTEM, "mujhe dolo wali goli ka rate batao")
    assert out and any("dolo" in m.lower() for m in out.get("medicines", []))
