"""Phase 10: grounded, cited health answers + interaction checker (needs the local Postgres evidence index)."""
import re

import pytest

from medibot.health.answer import DOSE, answer_medicine, answer_topic, safe_sentences
from medibot.health.evidence import available, question_sections
from medibot.health import interactions as ix
from medibot.safety.output_check import violations

needs_db = pytest.mark.skipif(not available(), reason="evidence index not reachable")


@pytest.mark.parametrize("q,sec", [
    ("Is it safe to take Crocin during pregnancy?", "pregnancy"),
    ("Can I drive after taking Allegra?", "driving"),
    ("Does Dolo 650 cause drowsiness?", "side_effects"),
    ("Is cetirizine habit forming?", "habit_forming"),
    ("Can I crush a Pan 40 tablet?", "how_to_use"),
    ("dolo ke saath daru pi sakte hai?", "alcohol"),
    ("Can I give Calpol syrup to a 2 year old?", "children"),
    ("How does amoxicillin work?", "how_it_works"),
])
def test_question_sections(q, sec):
    assert question_sections(q)[0] == sec


def test_dose_sentences_are_dropped():
    t = ("This medicine relieves pain. No more than four doses can be taken in 24 hours. "
         "Take 2 tablets daily. The maximum dose is 4 g. It may cause nausea.")
    out = safe_sentences(t, max_sents=5)
    assert out == "This medicine relieves pain. It may cause nausea."
    assert not DOSE.search(out)


@needs_db
@pytest.mark.parametrize("name,ings,q,must", [
    ("Dolo 650 Tablet", ("paracetamol",), "Is it safe in pregnancy?", r"pregnan"),
    ("Metformin", ("metformin",), "What are the side effects of metformin?", r"diarr|nause|stomach|lactic"),
    ("Allegra 120mg Tablet", ("fexofenadine",), "Can I drive after taking Allegra?", r"driv|sleep|drows"),
    ("Pan 40 Tablet", ("pantoprazole",), "Can I crush a Pan 40 tablet?", r"whole|crush|chew"),
])
def test_answers_are_grounded_cited_and_dose_free(name, ings, q, must):
    a = answer_medicine(name, None, ings, q)
    assert a.grounded and a.citations, a.text
    assert re.search(must, a.text, re.I), a.text
    assert re.findall(r"\[(\d+)\]", a.text), "every answer cites"
    assert not violations(a.text) and not DOSE.search(a.text.replace("[", " ").replace("]", " "))
    assert name.split()[0].lower() not in a.text.lower() or "written for" not in a.text  # brand neutralised


@needs_db
def test_unknown_section_says_no_reliable_info():
    a = answer_medicine("X", None, ("serratiopeptidase",), "is it safe while breastfeeding?")
    assert a.grounded or "don't have reliable information" in a.text


@needs_db
@pytest.mark.parametrize("q,topic", [
    ("What is Jan Aushadhi?", "Jan Aushadhi"),
    ("Are generic medicines as effective as branded ones?", "generic"),
    ("What does ORS do in diarrhoea?", "ORS"),
])
def test_topics(q, topic):
    a = answer_topic(q)
    assert a and a.citations and topic.lower() in a.text.lower()


@needs_db
def test_topic_does_not_answer_unrelated():
    assert answer_topic("Who won the cricket match yesterday?") is None


@needs_db
def test_duplicate_ingredient_and_graded_interaction():
    f = ix.check([ix.Item("Saridon", ("paracetamol", "propyphenazone", "caffeine")),
                  ix.Item("Combiflam", ("ibuprofen", "paracetamol"))])
    assert f[0].kind == "duplicate" and f[0].ingredient_a == "paracetamol"
    g = ix.check([ix.Item("Warfarin", ("warfarin",)), ix.Item("Aspirin", ("aspirin",))])
    assert g and g[0].severity in ("Major", "Moderate")
    txt, cites = ix.render([ix.Item("Warfarin", ("warfarin",)), ix.Item("Aspirin", ("aspirin",))], g)
    assert not violations(txt) and cites[0] == ix.DDINTER and "[1]" in txt


@needs_db
def test_label_passage_answers_children_for_strepsils():
    a = answer_medicine("Strepsils Original Lozenges", None, ("amylmetacresol", "dichlorobenzyl alcohol"),
                        "Is Strepsils safe for children?")
    assert a.grounded and "children" not in a.missing and re.search(r"under 6 years", a.text), a.text
    assert any("medicines.org.uk" in c.url for c in a.citations)


@needs_db
def test_warnings_are_a_fallback_when_specific_sections_are_missing():
    a = answer_medicine("Dettol Antiseptic Liquid", None, ("absolute alcohol", "chloroxylenol", "terpineol"),
                        "Is Dettol safe to apply on skin?")
    assert a.grounded and "warnings" in a.sections and re.search(r"external use|irritation", a.text, re.I), a.text


@needs_db
def test_missed_dose_topic_by_id():
    from medibot.health.answer import answer_topic_id
    a = answer_topic_id("missed_dose")
    assert a and a.citations and "two doses together" in a.text and not violations(a.text)


@needs_db
def test_antacid_milk_topic():
    a = answer_topic("Is it okay to take antacids with milk?")
    assert a and "2 to 4 hours" in a.text and a.citations[0].url.startswith("https://www.nhs.uk/")


@needs_db
def test_own_monograph_choice_is_deterministic():
    from medibot.health.evidence import product_passages, query
    pid = query("SELECT p.canonical_id FROM product_info i JOIN products p USING (product_id) WHERE i.source = 'mid' "
                "GROUP BY p.canonical_id HAVING count(*) > 1 ORDER BY p.canonical_id LIMIT 1")[0][0]
    names = {product_passages(pid)[0].meta["written_for"] for _ in range(5)}
    assert len(names) == 1, names


@needs_db
def test_known_partners():
    names = [n for n, _ in ix.known_partners("warfarin")]
    assert len(names) >= 3
