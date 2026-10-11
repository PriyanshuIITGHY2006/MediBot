"""Phase 11: the narrator's LLM lead. A misbehaving model must always fall back to the template (no lead)."""
import pytest

from medibot import cards as C
from medibot import narrator as N

QUOTES = [{"platform": "netmeds", "price_inr": 30.5, "price_per_unit_inr": 2.03, "pack_label": "strip of 15",
           "freshness": "checked 2 h ago", "in_stock": True}]
CARDS = [C.MedicineCard("Dolo 650 Tablet", "p1", "Paracetamol 650 mg", "otc"), C.PriceStrip("p1", QUOTES)]


class FakeLLM:
    enabled = True

    def __init__(self, lead, allowed=(True, "")):
        self.lead, self.allowed, self.calls = lead, allowed, 0

    def allow(self, feature, model):
        return self.allowed

    def chat_json(self, *a, **k):
        self.calls += 1
        return self.lead if isinstance(self.lead, dict) or self.lead is None else {"lead": self.lead}


@pytest.fixture(scope="module")
def catalog():
    from medibot.catalog import load_catalog
    return load_catalog()


def run(monkeypatch, lead, catalog=None, allowed=(True, ""), intents=("price",), safety=False):
    fake = FakeLLM(lead, allowed)
    monkeypatch.setattr(N, "get_llm", lambda: fake)
    return N.narrate(CARDS, list(intents), "dolo 650 price", safety_turn=safety, catalog=catalog), fake


@pytest.mark.parametrize("lead", [
    "Dolo 650 Tablet is ₹30.5 on Netmeds right now.",
    "The cheapest option for Dolo 650 Tablet is netmeds at ₹30.5 total (₹2.03 per tablet).",   # real model wording
    "Dolo 650 Tablet sabse sasta Netmeds par ₹30.5 hai.",
])
def test_good_lead_is_used(monkeypatch, catalog, lead):
    n, _ = run(monkeypatch, lead, catalog)
    assert n.source == "llm" and n.lead.text == lead, n.reason


@pytest.mark.parametrize("lead,why", [
    ("Dolo 650 Tablet is just ₹19 on Netmeds!", "number not in facts"),                       # invented price
    ("Crocin is ₹30.5 on Netmeds, a better pick.", "medicine not in facts"),                  # invented medicine
    ("Take 2 tablets daily, it's ₹30.5 on Netmeds.", "output check"),                         # dosing
    ("Din mein do baar lo, ₹30.5 hai Netmeds par.", "output check"),                           # Hinglish dosing
    ("This medication requires a valid prescription. Netmeds has it for ₹30.5.", "prescription"),  # retyped prompt
    ("No prescription needed, ₹30.5 on Netmeds.", "output check"),
    ("You have a fever, so Dolo 650 Tablet at ₹30.5 is fine.", "output check"),
    (" ".join(["word"] * 60), "too long"),
    ("", "empty"),
])
def test_bad_leads_fall_back_to_template(monkeypatch, catalog, lead, why):
    n, _ = run(monkeypatch, lead, catalog)
    assert n.lead is None and n.source == "template" and why in n.reason, n.reason


@pytest.mark.parametrize("lead", [
    "Dolo 650 Tablet Netmeds par ₹30.5 tak mil jayega.",                 # "tak" (measured rejection)
    "Netmeds par order kar sakte ho, Dolo 650 Tablet ₹30.5 hai.",      # "kar" (measured rejection) + "sakte"
    "Dolo 650 Tablet ₹30.5 mein mil jaegi, Netmeds par dekhiye.",
    "We couldnt find a lower price than ₹30.5 for Dolo 650 Tablet.",    # "couldnt" (measured rejection)
])
def test_filler_words_are_not_medicine_names(monkeypatch, catalog, lead):
    n, _ = run(monkeypatch, lead, catalog)
    assert "medicine not in facts" not in n.reason, n.reason


def test_invented_medicine_still_caught_among_fillers(catalog):
    facts = N.facts_json(CARDS, ["price"], "dolo 650 price")
    assert N.invented_medicine("Crocin bhi Netmeds par ₹30.5 tak mil jayega.", facts, catalog)


def test_junk_answer_falls_back(monkeypatch):
    n, _ = run(monkeypatch, {"text": 5})
    assert n.lead is None and n.reason == "no LLM answer"


def test_no_llm_call_on_safety_turns_or_without_facts(monkeypatch):
    n, fake = run(monkeypatch, "x", safety=True)
    assert n.lead is None and fake.calls == 0
    n, fake = run(monkeypatch, "x", intents=("info",))
    assert n.lead is None and fake.calls == 0


def test_quota_guard_and_kill_switch_stop_the_call(monkeypatch):
    n, fake = run(monkeypatch, "x", allowed=(False, "daily quota guard: 700/1000 used (cap 700)"))
    assert n.lead is None and fake.calls == 0 and "quota" in n.reason
    n, fake = run(monkeypatch, "x", allowed=(False, "MEDIBOT_NARRATOR=off"))
    assert n.lead is None and fake.calls == 0
