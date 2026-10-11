"""Last line of defence on every reply: no diagnosis, no personal dosing, no "you don't need a prescription".

Broader than the eval's own checks on purpose. If a draft fails, the caller replaces the offending CARD with the
fixed refusal (check_cards) — it is never "fixed up" by rewording, and the other cards survive.
Phase 11 added English + Hinglish patterns for the narrator's free text ("aapko dengue hai", "ye le lo",
"you can safely take", "no prescription needed"). Every pattern is tested against the red-team corpus AND all
current eval replies (backend/tests/test_output_check.py) so it never flags the cited health text we ship.
"""
from __future__ import annotations

import re

_COND = (r"infection|disease|fever|flu|dengue|malaria|typhoid|covid|diabetes|migraine|cancer|uti|jaundice|ulcer|"
         r"arthritis|hypertension|asthma|allergy|gastritis|pneumonia|tb|tuberculosis|appendicitis|thyroid|"
         r"bukhar|sugar|bp|piles|anemia|anaemia")

_PATTERNS = {
    "diagnosis": re.compile(
        # "If you have diabetes, tell your doctor" is a condition, not a diagnosis
        r"(?<!\bif )(?<!\bwhen )(?<!\bwhether )(?<!\bunless )(?<!\bin case )"
        r"\byou (have|are suffering from|might have|may have|probably have|likely have|seem to have|could have)\s+"
        rf"(a |an )?(\w+ ){{0,2}}({_COND})\b"
        r"|\bit (is|sounds like|looks like|seems like) (a |an )?(\w+ )?(infection|dengue|malaria|typhoid|covid|migraine|"
        r"viral|bacterial|flu|uti|allergy)\b|\byour diagnosis\b|\bthis is (definitely|probably|likely) \w+"
        rf"|\b(aapko|apko|tumhe|tumko|aap ko) (\w+ ){{0,2}}({_COND})\s+(hai|ho gaya|hua|lagta)\b"
        r"|\b(sounds|looks) like you (have|got)\b", re.I),
    "dosing": re.compile(
        r"\b(take|give|use|consume)\s+(\d+|one|two|three|half|1/2)\s*(tablets?|tabs?|capsules?|caps?|ml|spoons?|"
        r"teaspoons?|drops?|mg|puffs?)\b"
        r"|\b\d+\s*(tablets?|tabs?|capsules?|ml|mg)\s+(daily|a day|per day|twice|thrice|once|every \d+ hours?)\b"
        r"|\b(once|twice|thrice|three times) (a|per) day\b.*\b(for|x)\s*\d+\s*days\b"
        r"|\b(ek|do|teen|aadhi|1|2|3)\s+(goli|tablet|chammach|spoon)\s+(lo|le lo|lijiye|khao|kha lo)\b"
        r"|\b(din mein|roz) (ek|do|teen|1|2|3) (baar|bar|goli)\b", re.I),
    "prescribing": re.compile(
        r"\byou should (take|start|use|try)\s+\w+|\bi (recommend|suggest|prescribe) (you )?(take|taking|using)\b"
        r"|\b(take|try) (paracetamol|ibuprofen|dolo|crocin|antibiotics?|azithromycin|amoxicillin|cetirizine)\b"
        # a safety CLAIM, not timing advice from a cited monograph ("You can take it at any time of the day")
        r"|\byou can safely (take|use|give)\b|\bit('?s| is) safe for you to (take|use|give)\b"
        r"|\byou can (take|use|give) (it|this|them|these) (safely|without (a |any )?(prescription|doctor|worry))\b"
        r"|\b(ye|yeh|isko|ise) (le lo|le lijiye|kha lo|lena chahiye|le sakte ho|le sakti ho|le sakte hain)\b"
        r"|\bbest (medicine|tablet|option) for you\b", re.I),
    "rx_bypass": re.compile(r"\b(does not|doesn'?t|do not|don'?t|no) need (a )?prescription\b"
                            r"|\bwithout (a )?prescription (is|it'?s) (fine|ok|okay|safe)\b"
                            r"|\bno prescription (is )?(needed|required)\b"
                            r"|\b(bina|baghair) (prescription|parchi) (le sakte|mil jayegi|mil jaegi|chalega)\b", re.I),
}


def violations(text: str) -> list[str]:
    return [name for name, rx in _PATTERNS.items() if rx.search(text or "")]


SAFE_TYPES = ("intercept_banner", "emergency", "refusal")   # fixed texts from messages.py: never checked away


def check_cards(cards: list, refusal_factory) -> tuple[list, list[tuple[str, list[str]]]]:
    """Replace each fact card whose text fails the check with refusal_factory(card_type); keep all other cards.
    Returns (cards, [(card_type, reasons)])."""
    out, replaced = [], []
    for c in cards:
        bad = [] if getattr(c, "type", "") in SAFE_TYPES else violations(c.render())
        if bad:
            replaced.append((c.type, bad))
            out.append(refusal_factory(c.type))
        else:
            out.append(c)
    return out, replaced
