"""Model-first reader: the model only READS; our code checks every word and the kernel still decides."""
import pytest

from medibot import reader
from medibot.catalog import load_catalog
from medibot.safety import messages as msg
from medibot.safety.kernel import apply_reading, decide


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


def test_typed_guard_rejects_invented_names():
    assert reader.typed("augmntin 625", "omg augmntin 625 sooo expensive")
    assert not reader.typed("Remo Tablet", "varemo 5% Eye sasta")        # "remo" is inside "varemo", not typed
    assert not reader.typed("augmentin", "omg augmntin 625")              # the model may not "fix" spellings


class FakeLLM:
    enabled = True

    def __init__(self, answer):
        self.answer = answer

    def allow(self, *a):
        return True, ""

    def chat_json(self, *a, **k):
        return self.answer


@pytest.fixture
def bot(monkeypatch):
    from medibot import llm
    monkeypatch.setenv("MEDIBOT_LLM", "off")                 # narrator / second opinion / old fallback stay off
    monkeypatch.setattr(llm, "_llm", None)
    from medibot.assistant import Assistant
    return Assistant()


def ask(bot, monkeypatch, text, answer):
    monkeypatch.setattr(reader, "get_llm", lambda: FakeLLM(answer))
    return bot.query(bot.start_session()["session_id"], text)


BASE = {"medicines": [], "intents": [], "emergency": False, "self_harm": False, "misuse": False,
        "asks_what_to_take": False, "asks_dose": False, "asks_diagnosis": False, "off_topic": False,
        "greeting": False, "refers_back": False}


def test_slang_rule_matches_are_dropped_when_the_model_reads_none(bot, monkeypatch):
    r = ask(bot, monkeypatch, "bro my head is killin me lol wat do i pop", dict(BASE, asks_what_to_take=True))
    assert r["detected_medication"] is None and not r["safety_guard"]["intercept_triggered"]
    assert msg.PRESCRIBING_REFUSAL in r["response_text"]


def test_model_medicine_goes_through_our_resolver(bot, monkeypatch):
    r = ask(bot, monkeypatch, "omg augmntin 625 sooo expensive any cheapr thing??",
            dict(BASE, medicines=["augmntin 625"], intents=["substitute"]))
    assert r["detected_medication"]["brand_name"].startswith("Augmentin 625")
    assert r["safety_guard"]["intercept_triggered"] and r["response_text"].startswith(msg.MANDATED_PROMPT)
    assert r["substitutes"]


def test_invented_medicine_is_ignored(bot, monkeypatch):
    r = ask(bot, monkeypatch, "varemo 5% Eye sasta", dict(BASE, medicines=["Remo Tablet"], intents=["substitute"]))
    assert r["reader"]["dropped"] == ["Remo Tablet"]
    assert not r["detected_medication"] or "Remo" not in r["detected_medication"]["brand_name"]


def test_emergency_flag_wins_even_over_an_intercept(bot, monkeypatch):
    r = ask(bot, monkeypatch, "he took augmentin 625 and now his lips look odd and he is not okay",
            dict(BASE, medicines=["augmentin 625"], emergency=True))
    assert r["safety_guard"]["is_emergency"]


def test_model_cannot_remove_an_intercept(bot, monkeypatch):
    # the model "forgets" a real restricted brand: the exact rule match is kept, so the mandated prompt stays
    r = ask(bot, monkeypatch, "alprax 0.5 price", dict(BASE, intents=["price"]))
    assert r["safety_guard"]["intercept_triggered"] and r["response_text"].startswith(msg.MANDATED_PROMPT)


def test_off_topic_gets_the_help_text(bot, monkeypatch):
    r = ask(bot, monkeypatch, "who won the cricket match yesterday", dict(BASE, off_topic=True))
    assert r["detected_medication"] is None and not r["safety_guard"]["intercept_triggered"]
    assert "medicine" in r["response_text"].lower()


def test_bad_answer_falls_back_to_rules(bot, monkeypatch):
    r = ask(bot, monkeypatch, "my dad isnt waking up and hes breathing weird", "not json")
    assert r["reader"]["status"] == "error" and r["safety_guard"]["is_emergency"]   # the rules catch it alone


@pytest.mark.parametrize("flags,named,want", [
    ({"asks_dose": True}, True, "refuse_dosing"),
    ({"asks_what_to_take": True}, True, "allow"),     # asking about a NAMED medicine is not prescribing
    ({"asks_what_to_take": True}, False, "refuse_prescribing"),
    ({"asks_diagnosis": True}, False, "refuse_diagnosis"),
    ({"misuse": True}, False, "refuse_misuse"),
    ({"emergency": True}, True, "emergency"),
])
def test_apply_reading_only_adds(cat, flags, named, want):
    d = decide("dolo 650 price" if named else "hello there", cat)
    assert d.action == "allow"
    apply_reading(d, flags)
    assert d.action == want


def test_model_spelling_fix_is_checked_by_our_catalog(bot, monkeypatch):
    # "naxodam" -> the model suggests "Naxdom"; our catalog confirms it and the user is asked to confirm
    r = ask(bot, monkeypatch, "naxodam ka cheapest price bata vai",
            dict(BASE, medicines=["naxodam"], spelling={"naxodam": "Naxdom"}, intents=["price"]))
    assert r["detected_medication"]["brand_name"].startswith("Naxdom")
    assert r["clarification_options"]                         # "Did you mean …?"
    assert r["safety_guard"]["intercept_triggered"]           # naproxen: still a prescription medicine


def test_model_cannot_swap_in_a_different_medicine(bot, monkeypatch):
    r = ask(bot, monkeypatch, "naxodam price", dict(BASE, medicines=["naxodam"], spelling={"naxodam": "Augmentin"},
                                                    intents=["price"]))
    assert not r["detected_medication"] or not r["detected_medication"]["brand_name"].startswith("Augmentin")
