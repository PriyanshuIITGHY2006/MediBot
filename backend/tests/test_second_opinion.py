"""Phase 11 / plan 6.6: the LLM second opinion is ADD-ONLY and never breaks a reply."""
import time

import pytest

from medibot.safety import messages as msg
from medibot.safety import second_opinion as so
from medibot.safety.kernel import apply_second_opinion, decide, safety_lines


@pytest.fixture(scope="module")
def cat():
    from medibot.catalog import load_catalog
    return load_catalog()


ALL_FALSE = {"emergency": False, "self_harm": False, "misuse": False}
FIELDS = ("action", "intercept", "banned", "emergency", "self_harm", "diagnosis_request", "prescribing_request",
          "dosing_request", "rx_seeking", "misuse")


def state(d):
    return {f: getattr(d, f) for f in FIELDS}


def test_all_false_changes_nothing(cat):
    for text in ["Dolo 650 price", "augmentin 625 price", "I have a cold"]:
        d = decide(text, cat)
        before = state(d)
        assert apply_second_opinion(d, ALL_FALSE) == []
        assert state(d) == before


@pytest.mark.parametrize("flag,changed", [
    ("emergency", {"action": "emergency", "emergency": True}),
    ("self_harm", {"action": "emergency", "emergency": True, "self_harm": True}),
    ("misuse", {"action": "refuse_misuse", "misuse": True, "intercept": True}),
])
def test_each_flag_sets_only_its_own_fields(cat, flag, changed):
    d = decide("Dolo 650 price", cat)
    before = state(d)
    assert apply_second_opinion(d, dict(ALL_FALSE, **{flag: True})) == [flag]
    after = state(d)
    assert {k: v for k, v in after.items() if before[k] != v} == changed


@pytest.mark.parametrize("dropped", ["diagnosis", "prescribing", "dosing", "rx_seeking", "medicines"])
def test_dropped_flags_are_ignored(cat, dropped):
    """The narrowed second opinion: these keys (and medicine suggestions) can no longer change anything."""
    d = decide("Dolo 650 price", cat)
    before = state(d)
    assert apply_second_opinion(d, {dropped: True if dropped != "medicines" else ["Remo Tablet"]}) == []
    assert state(d) == before


def test_the_model_cannot_add_medicines(cat):
    """Regression: the old prompt turned 'varemo 5% Eye sasta' into an invented 'Remo Tablet' -> false intercept."""
    import inspect
    assert "medicines" not in so.SYSTEM and "extra_medicines" not in inspect.signature(apply_second_opinion).parameters


def test_cannot_remove_an_intercept(cat):
    d = decide("alprax 0.5 price", cat)
    assert d.intercept
    apply_second_opinion(d, ALL_FALSE)                                  # "nothing to see here"
    apply_second_opinion(d, {"intercept": False, "restricted": False})  # unknown keys are ignored
    assert d.intercept and safety_lines(d)[0] == msg.MANDATED_PROMPT


def test_paraphrased_emergency_becomes_emergency(cat):
    """Regression (the reason 6.6 exists): the rule detectors miss this paraphrase; the model must catch it.
    ("lips are turning blue" is now in the rules too - see test_rules_catch_blue_lips.)"""
    d = decide("my father has gone all grey and quiet, something is badly off with him", cat)
    assert d.action == "allow"   # the rules alone miss it
    assert apply_second_opinion(d, dict(ALL_FALSE, emergency=True)) == ["emergency"]
    assert d.action == "emergency" and safety_lines(d) == [msg.EMERGENCY]


def test_assistant_turns_paraphrased_emergency_into_emergency_card(monkeypatch):
    """End to end with a stub model that answers like the real one did live (2026-10-11)."""
    class Stub:
        enabled = True

        def allow(self, *a):
            return True, ""

        def chat_json(self, system, text, **k):
            return {"emergency": "gone all grey" in text, "self_harm": False, "misuse": False}
    from medibot import llm
    monkeypatch.setenv("MEDIBOT_LLM", "off")          # understanding + narrator: no real API call in tests
    monkeypatch.setattr(llm, "_llm", None)
    monkeypatch.setattr(so, "get_llm", lambda: Stub())  # only the second opinion answers, from the stub
    from medibot.assistant import Assistant
    bot = Assistant()
    sid = bot.start_session()["session_id"]
    r = bot.query(sid, "my father has gone all grey and quiet, something is badly off with him")
    assert r["safety_guard"]["is_emergency"] and r["response_text"] == msg.EMERGENCY
    assert r["second_opinion"]["added"] == ["emergency"]
    r2 = bot.query(bot.start_session()["session_id"], "Dolo 650 price")
    assert not r2["second_opinion"]["added"] and not r2["safety_guard"]["intercept_triggered"]


def test_skipped_unless_plain_allow():
    fut, op = so.start("augmentin price", "intercept")
    assert fut is None and op.status == "skipped"


def test_kill_switch_and_quota_skip(monkeypatch):
    class Fake:
        enabled = True

        def allow(self, feature, model):
            return False, "MEDIBOT_SECOND_OPINION=off"
    monkeypatch.setattr(so, "get_llm", lambda: Fake())
    fut, op = so.start("dolo price", "allow")
    assert fut is None and op.status == "skipped" and "off" in op.reason


def test_timeout_keeps_the_kernel_decision(monkeypatch):
    class Slow:
        enabled = True

        def allow(self, *a):
            return True, ""

        def chat_json(self, *a, **k):
            time.sleep(0.6)
            return {"emergency": True, "self_harm": False, "misuse": False}
    monkeypatch.setattr(so, "get_llm", lambda: Slow())
    monkeypatch.setattr(so, "BUDGET", 0.2)
    t0 = time.time()
    fut, early = so.start("dolo price", "allow")
    op = so.collect(fut, early, t0)
    assert op.status == "timeout" and time.time() - t0 < 0.5


def test_bad_json_is_ignored(monkeypatch):
    class Junk:
        enabled = True

        def allow(self, *a):
            return True, ""

        def chat_json(self, *a, **k):
            return None
    monkeypatch.setattr(so, "get_llm", lambda: Junk())
    t0 = time.time()
    fut, early = so.start("dolo price", "allow")
    assert so.collect(fut, early, t0).status == "error"


def test_assistant_with_llm_off_has_no_second_opinion_effect(monkeypatch):
    monkeypatch.setenv("MEDIBOT_LLM", "off")
    from medibot import llm
    monkeypatch.setattr(llm, "_llm", None)
    from medibot.assistant import Assistant
    bot = Assistant()
    sid = bot.start_session()["session_id"]
    r = bot.query(sid, "Dolo 650 price")
    assert r["second_opinion"]["status"] == "skipped" and not r["second_opinion"]["added"]
    monkeypatch.setattr(llm, "_llm", None)


def test_rules_catch_blue_lips(cat):
    assert decide("my father's lips are turning blue, what to do", cat).action == "emergency"
