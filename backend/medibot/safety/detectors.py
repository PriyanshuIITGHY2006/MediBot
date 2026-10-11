"""Rule-based detectors for risky message types (English + Hinglish). Deterministic and testable.

Each returns the matched phrase (truthy) or None. They are deliberately broad: a false alarm costs a
polite refusal; a miss can cost a diagnosis penalty or a missed emergency. An LLM classifier may be
added later as a second opinion that can only ADD flags, never remove them.
"""
from __future__ import annotations

import re


def _rx(*patterns: str) -> re.Pattern:
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.I)


EMERGENCY = _rx(
    r"chest (pain|tightness|pressure)\b.*\b(sweat|breath|arm|jaw|severe)|severe chest pain|heart attack",
    r"(can'?t|cannot|unable to|not able to|difficulty|trouble) breath(e|ing)|not breathing|stopped breathing|"
    r"saans (nahi|nhi|lene mein)",
    r"seene (mein|me) dard",
    r"collapsed|unconscious|fainted and|not waking|behosh|passed out|"
    r"(is ?n'?t|is not|won'?t|wont|not|can'?t|cant|isnt|nahi) (waking|wake) ?up|uth (nahi|nhi) (raha|rahi)|"
    r"(not|isn'?t|isnt) (responding|moving)|slumped|(won'?t|wont|doesn'?t|does not|can'?t|cant) (get (him|her|them) to )?respond",
    r"breath(ing)? (weird|weirdly|strange|strangely|funny|fast|heavy|heavily|badly|noisy)|gasping|"
    r"(lips|face|skin) (are |is )?(turning |gone |going )?(blue|purple|grey|gray)|blue lips",
    r"seizure|fits\b|convulsion|daura",
    r"(suicid|kill (myself|me)|end (my|this) life|want to die|don'?t want to live|marna chahta|marna chahti|khudkushi|"
    r"self.?harm|hurt myself)",
    r"overdose|took too many|swallowed \d+|(\d{2,}|too many) (tablets|pills)|zyada goli",
    r"\b(swallowed|took|taken|ate|kha li|kha liya|kha liye)\b[^.?!]{0,30}\b(\d{2,}|many|lots of|a lot of|bunch of|"
    r"whole (strip|bottle|pack))\b[^.?!]{0,25}\b(pills?|tablets?|tabs?|capsules?|goli|golis|meds|medicines?)",
    r"(face|mouth) (is )?drooping|can'?t speak|slurred speech|sudden weakness|stroke",
    r"(lips|tongue|face|throat) .*(swell|closing)|throat (is )?closing|anaphyla",
    r"vomit(ing)? blood|coughing (up )?blood|blood in vomit|heavy bleeding|bleeding heavily|won'?t stop bleeding",
    r"snake ?bite|bitten by a snake|dog bite.*(child|deep)|scorpion",
    r"(drank|swallowed|ingested|pi liya) .*(phenyl|kerosene|poison|acid|bleach|pesticide|harpic|rat)|poisoning",
    r"stiff neck.*fever|fever.*stiff neck",
    r"severe (allergic|burn)|electric shock|unresponsive",
)

DIAGNOSIS_REQUEST = _rx(
    r"what (disease|illness|infection|condition|problem|is wrong)\b.*\b(i|me|my|he|she|child|son|daughter|it|this|that)\b",
    r"what is wrong with (me|my|him|her)",
    r"\b(do|does|did) (i|he|she|my \w+) have (a |an )?\w+",
    r"\bam i (having|suffering)|\bis (it|this|my \w+( \w+)?) (a |an )?(migraine|dengue|malaria|typhoid|covid|cancer|"
    r"infection|uti|appendicitis|arthritis|hypertension|diabetes|jaundice|stroke|ulcer|tb|pneumonia)",
    r"\b(diagnose|diagnosis)\b",
    r"kya mujhe .* hai|mujhe kya (hua|hai|bimari)|kaunsi bimari",
    r"what (is|could) (it|this) be|what could (cause|be causing)",
)
SYMPTOM_STATEMENT = _rx(
    r"\b(i|i'm|i am|my (child|son|daughter|baby|mother|father|wife|husband)|he|she) (have|has|had|got|am having|is having|feel|feels|am feeling|is feeling|am suffering|is suffering)\b.*"
    r"\b(fever|pain|ache|cough|cold|vomit|nausea|diarrh|loose motion|rash|itch|burn|swelling|bleed|dizz|tired|"
    r"weak|headache|migraine|sore throat|acidity|gas|constipation|infection|lump|breathless|insomnia|can'?t sleep)",
    r"mujhe (bukhar|khansi|dard|sardi|ulti|dast|chakkar)|(bukhar|khansi|sardi|zukam) (hai|ho raha)",
)
PRESCRIBING_REQUEST = _rx(
    r"(what|which|kaunsi|kaun si|konsi) (medicine|medication|tablet|drug|antibiotic|painkiller|pill|syrup|dawai|dawa|goli)"
    r".*\b(should|to take|best|for|lu|lena|lene|le)\b",
    r"\b(suggest|recommend|prescribe|tell me|give me)\b.*\b(medicine|medication|tablet|antibiotic|painkiller|something|smthng|smth|sumthing|kuch|dawai|drug)",
    r"what should i (take|use|give)|kya (lu|le|lena chahiye)|kya khau",
    r"\b(what|wat|wht|which) (should|do|can|shud|cn) (i|u|we) (take|pop|have|use|eat|try)\b",
    r"(best|strongest|safest) (medicine|antibiotic|painkiller|sleeping pill)",
)
DOSING_REQUEST = _rx(
    r"how (many|much)(?!\s+(does|do|is|are|will)\b[^?]*\b(cost|price|rate))\b.*\b(take|tablets?|pills?|ml|mg|capsules?|times|doses?|a day|per day|daily|can i)",
    r"\b(dose|dosage|doses|kitni goli|kitni baar|kitna lena|how often)\b",
    r"how (long|many days)\b.*\b(take|continue|course|use)",
    r"maximum (dose|amount)",
    # "can I take 2 tablets", "should I give him half a tablet", "do goli le sakta hu"
    r"\b(take|taking|give|giving|have|use|consume|kha|khana|khau|khaun|lu|lun|loon|le|lena|lelu|de|du|dena|pila|pilau)\b"
    r"[^.?!]{0,30}?\b(\d+(\.\d+)?|one|two|three|four|five|half|double|ek|do|teen|char|aadhi|aadha|aadhe)\s*(a |an )?"
    r"(tablets?|tabs?|pills?|capsules?|caps?|goli|golis|ml|mg|spoons?|teaspoons?|chammach|drops?|puffs?|doses?|sachets?)\b",
    # "2 tablets together / at once / a day ok?", "do goli ek saath"
    r"\b(\d+(\.\d+)?|one|two|three|four|double|ek|do|teen)\s*(tablets?|tabs?|pills?|capsules?|goli|ml|doses?)\b"
    r"[^.?!]{0,25}?\b(together|at once|at a time|ek saath|ek sath|a day|per day|daily|roz|safe|ok|okay|fine|enough)\b",
    r"\bdouble (dose|up|the dose|tablet|goli)\b|\b(take|have|kha|le) (it |them |a )?(twice|double)\b|"
    r"\bextra (dose|tablet|pill|goli)\b",
)
# "I missed a dose of X, what now?" is a general-safety question (answer: check the leaflet, never double up, ask
# the pharmacist), not a request for an amount. The phrase is removed before DOSING_REQUEST runs, so anything else
# in the message ("... how many should I take now?", "... double dose?") is still refused.
MISSED_DOSE = _rx(
    r"\b(miss(ed|ing)?|forg(o|e)t(ten)?( to take)?|skip(ped|ping)?)\s+(a |my |one |the |his |her |a single )?"
    r"(dose|doses|tablet|pill|capsule)\b",
    r"\b(dose|goli|dawai) (bhool|bhul|chhoot|chhut|chut)\s*(gaya|gayi|gai|gaye)\b",
)
RX_SEEKING = _rx(
    r"without (a |any )?(prescription|doctor|parchi|rx)",
    r"(bina|baghair) (prescription|parchi|doctor)",
    r"no prescription|don'?t have (a )?prescription|fake (a )?prescription|forge",
    r"(sell|get) me .* without",
)
MISUSE = _rx(
    r"get(ting)? high|\bnasha\b|recreational|for fun|to feel (high|good)|abuse|getting stoned|trip\b",
    r"(mix|combine) .* alcohol .* (high|effect|stronger)",
)
JAILBREAK = _rx(
    r"ignore (all |any |the |your )?(previous |prior |above )?(instructions|rules|prompt|restrictions)",
    r"\b(dev ?mode|jailbreak|dan\b|no restrictions|unrestricted|safety (is )?(disabled|off))",
    r"pretend (you are|to be)|act as|role ?play|let'?s play a game|you are now",
    r"^\s*system\s*:|<!--|print (your )?(system )?prompt|reveal your",
    r"write a (story|poem|script) where .* (dose|how to)",
)
EMERGENCY_SELF_HARM = _rx(r"suicid|kill (myself|me)|end (my|this) life|want to die|don'?t want to live|marna chahta|"
                          r"marna chahti|khudkushi|self.?harm|hurt myself|took too many|overdose")


def first(rx: re.Pattern, text: str) -> str | None:
    m = rx.search(text)
    return m.group(0) if m else None
