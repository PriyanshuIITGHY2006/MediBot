"""Phase 11: cards. response_text is built from the cards; safety cards come first and are verbatim."""
import pytest

from medibot import cards as C
from medibot.safety import messages as msg


@pytest.fixture(scope="module")
def bot():
    import os
    os.environ["MEDIBOT_LLM"] = "off"
    from medibot import llm
    llm._llm = None
    from medibot.assistant import Assistant
    return Assistant()


def ask(bot, *turns):
    sid = bot.start_session()["session_id"]
    bot.acknowledge(sid)
    return [bot.query(sid, t) for t in turns]


def body(r):
    return [c for c in r["cards"] if c["type"] not in ("lead", "disclaimer", "quick_replies")]


def test_price_strip_renders_like_before():
    q = {"platform": "1mg", "price_inr": 30.5, "pack_label": "strip of 15", "price_per_unit_inr": 2.03,
         "freshness": "as of 2025-03", "in_stock": True,
         "above_nppa_ceiling": {"ceiling_per_unit_inr": 1.8, "source": "NPPA"}}
    assert C.PriceStrip("p", [q]).render() == ("• 1mg: ₹30.50 (strip of 15, ₹2.03/unit) — as of 2025-03 · in stock\n"
                                               "  ⚠ above the government ceiling price of ₹1.80/unit (NPPA)")
    assert C.PriceStrip("p", []).render() == "• No recent price on record for this pack."


def test_every_card_has_a_type_and_text():
    for card in [C.MedicineCard("Dolo 650 Tablet", composition="Paracetamol 650 mg"), C.StoreCard(None, asked_for_pincode=True),
                 C.Clarify(["A", "B"]), C.Fallback(), C.Disclaimer(msg.SHORT_DISCLAIMER)]:
        d = card.as_contract()
        assert d["type"] and d["text"] == card.render()


def test_intercept_banner_first_and_verbatim(bot):
    r = ask(bot, "augmentin 625 cheaper alternative")[0]
    b = body(r)
    assert b[0]["type"] == "intercept_banner" and b[0]["lines"][0] == msg.MANDATED_PROMPT
    assert r["response_text"].startswith(msg.MANDATED_PROMPT)
    assert any(c["type"] == "substitutes" for c in b)


def test_emergency_shows_only_the_emergency_card(bot):
    r = ask(bot, "I have severe chest pain and I am sweating a lot")[0]
    assert [c["type"] for c in body(r)] == ["emergency"]
    assert r["response_text"] == msg.EMERGENCY


def test_response_text_is_built_from_the_cards(bot):
    for text in ["Dolo 650 price", "what is Crocin used for?", "jan aushadhi kendra near 110001", "hello"]:
        r = ask(bot, text)[0]
        rendered = [c["text"] for c in body(r)]
        assert all(t in r["response_text"] for t in rendered if t), text


def test_disclaimer_card_full_first_then_short(bot):
    rs = ask(bot, "augmentin 625 price", "dolo 650 price")
    d0 = next(c for c in rs[0]["cards"] if c["type"] == "disclaimer")
    d1 = next(c for c in rs[1]["cards"] if c["type"] == "disclaimer")
    assert d0["full"] and d0["text"] == msg.DISCLAIMER          # first intercept of the session
    assert not d1["full"] and d1["text"] == msg.SHORT_DISCLAIMER
    assert rs[0]["disclaimer_acknowledged_at"]


def test_no_disclaimer_on_greeting(bot):
    assert ask(bot, "hello")[0]["disclaimer"] is None


def test_quick_replies_are_fixed_texts(bot):
    r = ask(bot, "Dolo 650 price")[0]
    qr = next(c for c in r["cards"] if c["type"] == "quick_replies")
    assert set(qr["options"]) <= {"Cheaper identical options", "Compare prices", "Side effects", "Nearest Jan Aushadhi"}
