"""Find medicine mentions (brands and generic ingredient names) inside a free-text message.

"can I take crocin and allegra together?" -> [Crocin..., Allegra...]
"I have a cold"                            -> []   ("cold" is an English word, no strength/form support)
"pan 40 price"                             -> [PAN 40 Tablet]

Strategy: look at word spans (longest first). A span is tried only if its first word could be a brand
(not a stop/Hinglish filler word; common English words need a strength number or form word next to them).
Resolution uses the tested MedicineIndex (98% top-1 with typos) and keeps only confident hits.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from rapidfuzz import fuzz
from wordfreq import zipf_frequency

from medibot.catalog import Catalog

HINGLISH = set("""hai hain ka ki ke ko se me mein mujhe mera meri mere kya koi kaun kaunsi kaunsa kitne kitna kitni
liye lu lo le lena sasta saste sasti option dawai dawa davai goli parchi bina milega milegi milta kaha kahan kab
aur ya bhi nahi nhi na toh to bata batao chahiye wala wali wale iska iski uska uski ye yeh wo woh rate kaam aati
aata karta karti hota hoti bukhar khansi dard pet sir saans""".split())
STOP = set("""pincode pin zipcode postal i me my we you your it its is are was be been do does did can could should would will shall may might
the a an and or of for to in on at with without from by about what which who whom how when where why whether
please tell give get buy price cost cheap cheaper cheapest alternative alternatives generic substitute same as
any some there this that these those safe take taking taken use used using side effects effect dose dosage
much many day daily days help need want know about versus vs than more less near nearest store online available
yes no not dont doesnt didnt cant cannot wont isnt arent im ive its ok okay thanks thank hi hello medicine medicines tablet tablets capsule capsules syrup drug drugs
pregnancy pregnant child children kids baby alcohol food milk together also again other one since ago after before
while during per like just only very really then so if but because still""".split())
FORM_WORDS = re.compile(r"^(tablets?|tab|capsules?|cap|syrup|suspension|drops?|cream|gel|ointment|injection|inj|"
                        r"spray|lotion|solution|powder|sachet|lozenges?|inhaler|dt|sr|er|xr|xl|pr|cr|cd|mr|od|dr|ec|la|"
                        r"cv|plus|forte|ds)$")
RELEASE_OR_FORM = re.compile(r"^(tablets?|tab|capsules?|cap|syrup|suspension|drops?|cream|gel|ointment|injection|"
                             r"sr|er|xr|xl|pr|cr|cd|mr|od|dr|ec|dt|md)$")
NUMBER = re.compile(r"^\d+(\.\d+)?(mg|mcg|g|gm|ml|iu|k|%)?$")
DESCRIPTOR = re.compile(r"^(oral|eye|ear|nasal|skin|flavour|flavor|orange|mango|mint|lemon|strawberry|sugar|free|"
                        r"paediatric|pediatric|kid|kids|junior|adult|new|advance|advanced|plus|forte|ds|soft|gelatin|"
                        r"dispersible|chewable|sachet|bottle|strip|pack|of|ml|gm|bc)$")
MEDICAL_TERMS = set("""fever pain ache cough cold flu diarrhoea diarrhea dysentery vomiting nausea acidity gas bloating
constipation headache migraine rash itch itching allergy infection wound burn skin hair eye ear nose throat stomach
tooth teeth knee back joint muscle period periods pregnancy sugar diabetes pressure bp thyroid asthma anxiety stress
sleep insomnia weight acne pimple dandruff piles ulcer sore swelling bleeding wound cuts""".split())
GENERIC_TERMS = {"ors", "antacid", "antacids", "antibiotic", "antibiotics", "painkiller", "painkillers", "vitamin",
                 "vitamins", "multivitamin", "probiotic", "laxative", "sanitiser", "sanitizer", "bandage"}
COMMON_ENGLISH = 3.5  # zipf frequency above which a word is "common English" (cold 5.0, pan 4.4; crocin 0.0)


@dataclass(frozen=True)
class Mention:
    kind: str            # product | ingredient
    ref: str             # product_id or ingredient name
    name: str            # display name
    span: tuple[int, int]
    text: str            # the words the user typed
    confidence: float
    confident: bool = True                      # False -> the bot must also ask "Did you mean ...?"
    brand_only: bool = False                    # only the brand word was typed (no strength / form / suffix)
    alternatives: tuple[str, ...] = ()          # other plausible product ids (for the clarification)


UNSURE_MIN = 75.0  # an unsure match still counts for SAFETY (never "unsure" -> "no medicine")


@lru_cache(maxsize=50_000)
def _common(word: str) -> bool:
    return zipf_frequency(word, "en") >= COMMON_ENGLISH


def tokenize(message: str) -> list[str]:
    t = message.lower().replace("’", "'")
    t = re.sub(r"\b(\w+)'(t|s|re|ve|ll|d|m)\b", r"\1\2", t)  # "don't" -> "dont" (never the brand "Don")
    t = re.sub(r"([a-z])(\d)", r"\1 \2", t)
    t = re.sub(r"(\d)\s*(mg|mcg|ml|iu)\b", r"\1\2", t)
    t = re.sub(r"[^a-z0-9.+% ]", " ", t)
    return [w.strip(".") for w in t.split() if w.strip(".")]


TIME_WORDS = {"days", "day", "din", "hours", "hrs", "years", "yrs", "saal", "weeks", "months", "times", "baar", "minutes"}


def _supported(words: list[str], i: int, j: int | None = None) -> bool:
    """A common English word counts as a brand only if a strength or form word follows it inside the span
    ("pan 40", "cold tablet", "go pain gel") - and a number is not a duration ("pain since 3 days")."""
    if i + 1 >= len(words):
        return False
    for k in range(i + 1, (j if j is not None else i + 1) + 1):
        if k < len(words) and (FORM_WORDS.match(words[k]) or (NUMBER.match(words[k]) and
                                                             (k + 1 >= len(words) or words[k + 1] not in TIME_WORDS))):
            return True
    nxt = words[i + 1]
    if FORM_WORDS.match(nxt):
        return True
    if re.fullmatch(r"[a-z]{1,3}", nxt) and nxt not in STOP and nxt not in HINGLISH:  # brand suffix: "pan d", "teczine m"
        return True
    return bool(NUMBER.match(nxt)) and (i + 2 >= len(words) or words[i + 2] not in TIME_WORDS)


def _can_start(words: list[str], i: int, j: int, ingredient_starts: set[str]) -> bool:
    w = words[i]
    if w in STOP or w in HINGLISH or w in GENERIC_TERMS or NUMBER.match(w) or FORM_WORDS.match(w) or DESCRIPTOR.match(w):
        return False
    if len(w) < 3:  # "n", "sl", "p" start a medicine only as a real phrase: "N Care", "SL B12" (2+ non-number words)
        if sum(1 for x in words[i:j + 1] if not NUMBER.match(x)) < 2:
            return False
    # brand names never contain filler words: "crocin and allegra" is two medicines, not one
    # (form words like "syrup"/"capsule" are NOT filler: "calpol syrup", "m nerve gm capsule")
    if any((x in STOP or x in HINGLISH) and not FORM_WORDS.match(x) for x in words[i + 1:j + 1]):
        return False
    if w in ingredient_starts and not _common(w):
        return True  # "paracetamol", "clavulanic acid" — but NOT "water", "yellow", "sugar" (common English)
    if _common(w) or w in MEDICAL_TERMS:
        # "nam cold tablet": if the word before is an unrecognised word, "cold tablet" is not a brand on its own
        if i > 0 and words[i - 1] not in STOP and words[i - 1] not in HINGLISH and not NUMBER.match(words[i - 1]):
            return False
        return _supported(words, i, j)
    return True


def _covers(span_words: list[str], product_text: str) -> bool:
    """Every typed word (except strengths/forms) must appear (allowing typos) in the matched name,
    so "cetirizine habit forming" cannot become one product."""
    names = product_text.split()
    for w in span_words:
        if NUMBER.match(w) or FORM_WORDS.match(w) or DESCRIPTOR.match(w):
            continue
        if not any(fuzz.ratio(w, n) >= 80 for n in names):
            return False
    return True


def _match_span(words: list[str], i: int, j: int, size: int, full_name_only: bool, catalog: Catalog) -> Mention | None:
    """Resolve words[i..j] to one medicine, or None. All acceptance checks live here."""
    span_words = words[i:j + 1]
    # a span must not END on a filler word ("crocin and")
    if (span_words[-1] in STOP or span_words[-1] in HINGLISH) and not FORM_WORDS.match(span_words[-1]):
        return None
    text = " ".join(span_words)
    core = " ".join(w for w in span_words if not (NUMBER.match(w) or FORM_WORDS.match(w)))
    if core in catalog.ingredients:  # generic name typed ("paracetamol", "aspirin 75", "clavulanic acid")
        return Mention("ingredient", core, core, (i, j), text, 100.0)
    hits = catalog.index.resolve(text, 3)
    top = hits[0] if hits else None
    if not top:
        return None
    if full_name_only:
        names = set(tokenize(top.name))
        if not top.confident or not all(w in names for w in span_words if not FORM_WORDS.match(w)):
            return None
    if not top.confident:
        # keep unsure matches for the guard, but only with real evidence
        if top.confidence < UNSURE_MIN or (size == 1 and len(words[i]) < 5) or top.kind != "product":
            return None
    if top.kind != "product":
        return Mention("ingredient", top.name, top.name, (i, j), text, top.confidence)
    rows = catalog.index.df.loc[catalog.index.df["canonical_id"] == top.product_id, ["search_text", "name"]]
    ptext = " ".join(rows["search_text"].iloc[:3]) + " " + " ".join(tokenize(" ".join(rows["name"].iloc[:3])))
    if len(rows) and not _covers(span_words, ptext):
        return None
    alts = tuple(h.product_id for h in hits[1:3] if h.kind == "product")
    return Mention("product", top.product_id, top.name, (i, j), text, top.confidence,
                   confident=top.confident, alternatives=alts, brand_only=(j == i))


def find_mentions(message: str, catalog: Catalog, max_span: int = 4) -> list[Mention]:
    words = tokenize(message)
    ingredient_starts = {n.split()[0] for n in catalog.ingredients}
    taken = [False] * len(words)
    found: list[Mention] = []
    for size in range(min(max_span, len(words)), 0, -1):
        for i in range(0, len(words) - size + 1):
            j = i + size - 1
            if any(taken[i:j + 1]):
                continue
            full_name_only = False
            if not _can_start(words, i, j, ingredient_starts):
                # a full multi-word brand name made of English words ("Refresh Tears") is its own support
                w0 = words[i]
                if not (size >= 2 and (_common(w0) or w0 in MEDICAL_TERMS) and w0 not in STOP and w0 not in HINGLISH
                        and not NUMBER.match(w0) and not FORM_WORDS.match(w0) and not DESCRIPTOR.match(w0)
                        and not any((x in STOP or x in HINGLISH) and not FORM_WORDS.match(x) for x in words[i:j + 1])):
                    continue
                full_name_only = True
            # try the phrase WITH the form/release words right after it ("tazloc beta 50 tablet" + "pr"),
            # then without them if that fails ("daliyshine" + "md" -> no product contains "md")
            j_ext = j
            while j_ext + 1 < len(words) and RELEASE_OR_FORM.match(words[j_ext + 1]) and not taken[j_ext + 1]:
                j_ext += 1
            m = _match_span(words, i, j_ext, size, full_name_only, catalog)
            if m is None and j_ext != j:
                m = _match_span(words, i, j, size, full_name_only, catalog)
            if m is None:
                continue
            found.append(m)
            taken[m.span[0]:m.span[1] + 1] = [True] * (m.span[1] - m.span[0] + 1)
    if any(m.confident for m in found):
        found = [m for m in found if m.confident]
    return sorted(found, key=lambda m: m.span)
