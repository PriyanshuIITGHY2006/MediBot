"""Last line of defence on every reply: no diagnosis, no personal dosing, no "you don't need a prescription".

Broader than the eval's own checks on purpose. If a draft reply fails, the caller replaces the
offending text with the fixed refusal — it is never "fixed up" by rewording.
"""
from __future__ import annotations

import re

_PATTERNS = {
    "diagnosis": re.compile(
        r"\byou (have|are suffering from|might have|may have|probably have|likely have|seem to have|could have)\s+"
        r"(a |an )?(\w+ ){0,2}(infection|disease|fever|flu|dengue|malaria|typhoid|covid|diabetes|migraine|cancer|uti|"
        r"jaundice|ulcer|arthritis|hypertension|asthma|allergy|gastritis|pneumonia|tb|tuberculosis|appendicitis)\b"
        r"|\bit (is|sounds like|looks like|seems like) (a |an )?(\w+ )?(infection|dengue|malaria|typhoid|covid|migraine|"
        r"viral|bacterial|flu|uti|allergy)\b|\byour diagnosis\b|\bthis is (definitely|probably|likely) \w+", re.I),
    "dosing": re.compile(
        r"\b(take|give|use|consume)\s+(\d+|one|two|three|half|1/2)\s*(tablets?|tabs?|capsules?|caps?|ml|spoons?|"
        r"teaspoons?|drops?|mg|puffs?)\b"
        r"|\b\d+\s*(tablets?|tabs?|capsules?|ml|mg)\s+(daily|a day|per day|twice|thrice|once|every \d+ hours?)\b"
        r"|\b(once|twice|thrice|three times) (a|per) day\b.*\b(for|x)\s*\d+\s*days\b", re.I),
    "prescribing": re.compile(
        r"\byou should (take|start|use|try)\s+\w+|\bi (recommend|suggest|prescribe) (you )?(take|taking|using)\b"
        r"|\b(take|try) (paracetamol|ibuprofen|dolo|crocin|antibiotics?|azithromycin|amoxicillin|cetirizine)\b", re.I),
    "rx_bypass": re.compile(r"\b(does not|doesn'?t|do not|don'?t|no) need (a )?prescription\b"
                            r"|\bwithout (a )?prescription (is|it'?s) (fine|ok|okay|safe)\b", re.I),
}


def violations(text: str) -> list[str]:
    return [name for name, rx in _PATTERNS.items() if rx.search(text or "")]
