"""Phase 15.4 Hindi display: fixed safety texts are hand-written (never a model), the mandated prompt stays in
English verbatim, and a model translation that changes any number is thrown away."""
import os

os.environ["MEDIBOT_LLM"] = "off"

from medibot import translate as tr  # noqa: E402
from medibot.safety import messages as en  # noqa: E402
from medibot.safety import messages_hi as hi  # noqa: E402


class FakeLLM:
    def __init__(self, fn):
        self.fn, self.calls = fn, 0

    def chat_json(self, system, user, **kw):
        import json
        self.calls += 1
        return {"lines": [self.fn(x) for x in json.loads(user)["lines"]]}


def test_every_fixed_safety_text_has_hindi():
    for e in [en.MANDATED_PROMPT, en.DISCLAIMER, en.SHORT_DISCLAIMER, en.EMERGENCY, en.SELF_HARM, en.DIAGNOSIS_REFUSAL,
              en.PRESCRIBING_REFUSAL, en.DOSING_REFUSAL, en.RX_SEEKING_REFUSAL, en.MISUSE_REFUSAL, en.FALLBACK_ERROR,
              en.banned_notice("Section 26A, S.O. 578(E)")]:
        h = hi.fixed(e)
        assert h and h != e
        assert tr._numbers(e) == tr._numbers(h), e[:40]          # helplines and section numbers kept


def test_safety_cards_never_reach_the_model(monkeypatch):
    fake = FakeLLM(lambda x: "X")
    monkeypatch.setattr(tr, "get_llm", lambda: fake)
    cards = [{"type": "emergency", "text": en.EMERGENCY, "self_harm": False},
             {"type": "disclaimer", "text": en.DISCLAIMER, "full": True}]
    out, rec = tr.translate_cards(cards, "hi")
    assert fake.calls == 0 and out[0]["text"] == hi.EMERGENCY and out[1]["text"] == hi.DISCLAIMER


def test_mandated_prompt_stays_english_with_hindi_under_it(monkeypatch):
    monkeypatch.setattr(tr, "get_llm", lambda: FakeLLM(lambda x: x))
    out, _ = tr.translate_cards([{"type": "intercept_banner", "lines": [en.MANDATED_PROMPT], "intercept": True}], "hi")
    assert out[0]["lines"] == [en.MANDATED_PROMPT, hi.MANDATED_PROMPT]


def test_a_translation_that_changes_a_number_is_dropped(monkeypatch):
    def bad(x):
        return x.replace("650", "500")                          # a "translation" that alters the strength
    monkeypatch.setattr(tr, "get_llm", lambda: FakeLLM(bad))
    cards = [{"type": "medicine", "text": "Dolo 650 Tablet — contains Paracetamol 650 mg."},
             {"type": "fallback", "text": "I can help with medicine prices."}]
    out, rec = tr.translate_cards(cards, "hi")
    assert out[0]["text"] == cards[0]["text"]                     # kept in English
    assert rec["kept_english"] == 1


def test_llm_off_returns_english_unchanged():
    cards = [{"type": "fallback", "text": "I can help with medicine prices."}]
    out, rec = tr.translate_cards(cards, "hi")
    assert out == cards and rec["language"] == "en"
    assert tr.translate_cards(cards, "en") == (cards, {"language": "en"})
