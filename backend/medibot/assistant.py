"""MediBot assistant: understanding -> context -> Safety Kernel -> facts -> reply. Implements the eval Bot contract.

The Safety Kernel is the only authority on what may be said; the LLM (understanding.py) only helps read
the message. Facts (prices, stores) come from the processed data, never from a model.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

import pandas as pd

from medibot import cards as C
from medibot import context as ctx
from medibot.catalog import load_catalog
from medibot import reader
from medibot.mentions import FORM_WORDS, NUMBER, Mention, _common, find_mentions, tokenize
from medibot.safety import messages as msg
from medibot.llm import get_llm
from medibot.narrator import narrate
from medibot.safety import second_opinion
from medibot.safety.kernel import Decision, apply_reading, apply_second_opinion, decide, safety_lines
from medibot.safety.output_check import check_cards, violations
from medibot.prices.engine import PriceEngine, freshness
from medibot.substitutes import find_substitutes, refresh_with_live
from medibot.substitutes import render as render_substitutes
from medibot.understanding import rules as _rules, understand
from medibot.health import interactions as ix
from medibot.health.answer import HealthAnswer, answer_medicine, answer_topic, answer_topic_id, render_sources
from medibot.health.evidence import query as db_query

ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def price_book() -> dict[str, list[dict]]:
    """Latest usable price per product and platform (pharmacy prices only; MRP references excluded)."""
    po = pd.read_parquet(ROOT / "data/processed/price_observations.parquet",
                         columns=["product_id", "source", "platform", "observed", "price_inr", "mrp_inr", "pack_label",
                                  "pack_unit", "price_per_unit_inr", "url"])
    # onemg_2025: "Selling_Price" is a per-unit price and "Pack_Size" holds the strength -> not a usable pack price
    po = po[po["platform"].isin(["1mg", "netmeds", "apollo", "pharmeasy"]) & (po["price_inr"] > 0)
            & (po["source"] != "onemg_2025")]
    # latest observation per platform, preferring ones with a pack size (so a price per unit exists)
    po = po.assign(_has_ppu=po["price_per_unit_inr"].notna())
    po = po.sort_values(["_has_ppu", "observed"]).drop_duplicates(["product_id", "platform"], keep="last")
    book: dict[str, list[dict]] = {}
    for r in po.itertuples(index=False):
        book.setdefault(r.product_id, []).append({
            "platform": r.platform, "price_inr": round(float(r.price_inr), 2),
            "mrp_inr": None if pd.isna(r.mrp_inr) else round(float(r.mrp_inr), 2),
            "price_per_unit_inr": None if pd.isna(r.price_per_unit_inr) else round(float(r.price_per_unit_inr), 2),
            "pack_label": r.pack_label if isinstance(r.pack_label, str) else None,
            "pack_unit": r.pack_unit if isinstance(r.pack_unit, str) else None,
            "observed": r.observed, "url": r.url if isinstance(r.url, str) else None,
            "delivery_eta": None})
    return book


@lru_cache(maxsize=1)
def kendras() -> pd.DataFrame:
    raw = json.loads((ROOT / "data/raw/jan_aushadhi/kendras.json").read_text())["responseBody"]["addKendraResponseList"]
    df = pd.DataFrame(raw)[["storeCode", "pinCode", "districtName", "stateName", "kendraAddress", "status"]]
    pin = pd.to_numeric(df["pinCode"], errors="coerce").fillna(0).astype(int).astype(str)
    return df.assign(pin=pin)[df["status"].eq(1)]  # owner name / phone never loaded


def nearest_kendras(pincode: str, n: int = 3) -> list[dict]:
    k = kendras()
    exact = k[k["pin"] == pincode]
    near = k[k["pin"].str[:3] == pincode[:3]] if len(exact) < n else exact.iloc[0:0]
    out = pd.concat([exact, near]).drop_duplicates("storeCode")
    if len(out) < n:  # nothing in the 3-digit area: numerically closest pincodes in the same 2-digit region
        region = k[k["pin"].str[:2] == pincode[:2]]
        region = region.assign(d=(region["pin"].astype(int) - int(pincode)).abs()).sort_values("d")
        out = pd.concat([out, region.drop(columns="d")]).drop_duplicates("storeCode")
    out = out.head(n)
    return [{"store_code": r.storeCode, "address": r.kendraAddress, "pincode": r.pin, "district": r.districtName,
             "state": r.stateName} for r in out.itertuples()]


class Assistant:
    def __init__(self):
        self.catalog = load_catalog()
        self.prices = PriceEngine(price_book())  # live product-page prices when MEDIBOT_LIVE_PRICES=on
        self.sessions: dict[str, ctx.Session] = {}

    # ------------------------------------------------ contract
    def start_session(self):
        sid = uuid.uuid4().hex
        self.sessions[sid] = ctx.Session()
        return {"session_id": sid, "disclaimer": msg.DISCLAIMER, "requires_acknowledgement": True}

    def acknowledge(self, session_id):
        s = self.sessions.setdefault(session_id, ctx.Session())
        s.acknowledged = True
        s.acknowledged_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        s.disclaimer_hash = DISCLAIMER_HASH   # which exact text was acknowledged (stored server-side in Phase 12)

    def query(self, session_id: str, text: str) -> dict:
        s = self.sessions.setdefault(session_id, ctx.Session())
        cat = self.catalog
        # model-first reader (reader.py) runs alongside the rule-based matching; it only READS the message
        t_r = time.time()
        r_fut, r_early = reader.start(text, ", ".join(m.name for m in s.focus[:2]) or None)
        now = find_mentions(text, cat)
        req = understand(text, have_mentions=bool(now), have_context=bool(s.focus), allow_llm=r_fut is None)
        reading = reader.collect(r_fut, r_early, t_r)
        if reading.ok:
            now = merge_reading(now, reading, cat, text)
            if reading.intents:
                req.intents = reading.intents
            elif reading.flags.get("off_topic") or reading.flags.get("greeting"):
                req.intents = ["greeting"]
            req.refers_back = req.refers_back or reading.flags.get("refers_back", False)
            req.used_llm = True
        for w in req.medicine_words:  # LLM-suggested words still pass the deterministic resolver
            for m in find_mentions(w, cat):
                if m.confident and all(m.ref != x.ref for x in now):
                    now.append(m)
        follow_up = bool(re.match(r"^\s*(and|aur|or|what about|how about|and what about|also)\b", text.lower())) \
            or len(text.split()) <= 3
        if s.last_intents and req.intents == ["info"] and (not now or follow_up):
            req.intents = s.last_intents  # "and dolo 650?" / "price?" keeps the previous question type
        used, notes = ctx.resolve(req, now, s, cat)
        # a store / pincode turn is about places, not the previous medicine: don't drag its card and stamp along
        bare_pin = bool(re.fullmatch(r"\s*(my )?(pin ?code( is)?)?\s*[1-9]\d{5}\s*", text.lower()))
        if not now and ("store" in rules_intents(text) or bare_pin):
            used, notes = [], notes + ["store question: previous medicine not carried over"]
        dec = decide(text, cat, mentions=used)
        dec.receipt = notes + dec.receipt
        if reading.ok:
            added = apply_reading(dec, reading.flags)
            if added:
                dec.receipt.append(f"reader added: {', '.join(added)} -> {dec.action}")
        elif reading.status != "skipped" or reading.reason != "LLM off":
            dec.receipt.append(f"reader {reading.status}: {reading.reason} (rules only)")
        if req.used_llm:
            dec.receipt.append("message read with LLM help (medicine words / intents only)")

        # 6.6 second opinion: runs in parallel with fact building; can only ADD protections
        t_so = time.time()
        so_future, so_early = (second_opinion.start(text, dec.action) if not reading.ok else
                               (None, second_opinion.Opinion("skipped", "reader already screened this message")))
        fact_cards, shown, extra = self._facts(dec, req, s)
        opinion = second_opinion.collect(so_future, so_early, t_so)
        so_info = {"status": opinion.status, "reason": opinion.reason, "seconds": opinion.seconds,
                   "flags": opinion.flags, "added": [], "before": dec.action, "after": dec.action}
        if opinion.status == "used":
            added = apply_second_opinion(dec, opinion.flags)
            so_info.update(added=added, after=dec.action)
            if added:
                dec.receipt.append(f"second opinion added: {', '.join(added)} ({so_info['before']} -> {dec.action})")
                fact_cards, shown, extra = self._facts(dec, req, s)   # facts must follow the stricter decision
        elif opinion.status != "skipped" or opinion.reason not in ("LLM off",):
            dec.receipt.append(f"second opinion {opinion.status}: {opinion.reason}".rstrip(": "))
        parts = safety_lines(dec)
        cards: list[C.Card] = []
        if parts:
            cards.append(C.EmergencyCard(parts[0], dec.self_harm) if dec.action == "emergency" else
                         C.InterceptBanner(parts, dec.intercept, dec.banned))
        # output check per card: an unsafe card becomes the fixed refusal, the other cards survive
        fact_cards, replaced = check_cards(fact_cards, lambda t: C.RefusalCard(replaced=t))
        for t, why in replaced:
            dec.receipt.append(f"output check replaced the {t} card ({', '.join(why)})")
        facts = C.facts_text(fact_cards)
        if facts and violations(facts):  # backstop: a violation that only appears across card boundaries
            fact_cards = [C.RefusalCard(replaced="facts")]
            facts = None
            dec.receipt.append("output check replaced the informational text")
        cards += fact_cards
        ctx.update(s, req, [m.mention for m in dec.medicines], shown)

        focus = dec.focus
        product = focus.product if focus else None
        clarify = []
        if focus and not focus.mention.confident:
            clarify = [focus.mention.name] + [cat.products[a].name for a in focus.mention.alternatives if a in cat.products]
            cards.append(C.Clarify(clarify[:3]))
        if not any(isinstance(c, C.SAFETY_CARDS) for c in cards) and not facts and not clarify:
            cards.append(C.Fallback())
        reply = compose(cards)
        medical = bool(dec.medicines) or dec.action != "allow"
        intent = ("emergency" if dec.emergency else "symptom" if dec.diagnosis_request else
                  "price" if "price" in req.intents and "substitute" not in req.intents else req.intents[0])
        story = narrate(cards, req.intents, text, safety_turn=bool(parts), catalog=cat)
        if story.reason and story.reason != "LLM off":
            dec.receipt.append(f"narrator: {story.source} ({story.reason})")
        llm = get_llm()
        if llm.enabled:
            dec.receipt.append(llm.usage_line())
        disc = disclaimer_card(s, medical, dec, extra, text, req.intents)
        qr = C.quick_replies(cards, dec.intercept)
        ui = ([story.lead] if story.lead else []) + cards + ([disc] if disc else []) + ([qr] if qr else [])
        return {
            "session_id": session_id,
            "response_text": reply,
            "cards": [c.as_contract() for c in ui],
            "narrator": {"source": story.source, "reason": story.reason},
            "second_opinion": so_info,
            "reader": reading.as_receipt(),
            "intent": intent,
            "safety_guard": {
                "is_restricted_schedule_h": bool(focus and focus.restricted),
                "intercept_triggered": dec.intercept,
                "mandated_prompt": msg.MANDATED_PROMPT if dec.intercept else None,
                "is_banned": dec.banned, "is_diagnosis_detected": dec.diagnosis_request, "is_emergency": dec.emergency,
            },
            "detected_medication": ({"product_id": product.product_id, "brand_name": product.name,
                                     "active_composition": product.composition, "composition_id": product.composition_id,
                                     "schedule": product.category} if product else None),
            "substitutes": extra.get("substitutes", []),
            "prices": extra.get("prices", []),
            "stores": extra.get("stores", []),
            "clarification_options": clarify[:3],
            "health_answer": extra.get("health_answer"),
            "interactions": extra.get("interactions"),
            # every medical turn (incl. unrecognised-medicine and health-topic turns) carries the disclaimer
            "disclaimer": disc.text if disc else None,
            "disclaimer_acknowledged": s.acknowledged,
            "disclaimer_acknowledged_at": s.acknowledged_at,
            "receipt": dec.receipt,
        }

    def _brand_info_product(self, mv):
        """Brand typed alone whose matched listing has no verified composition ("Dettol" -> a soap listing):
        health information may come from the brand's verified products, but only when they ALL share one ingredient
        set and none is restricted. Information only: the Safety Kernel's verdict on the mention is unchanged."""
        p = mv.product
        if p is None or p.ingredients or not mv.mention.brand_only:
            return None
        df = self.catalog.index.df
        stem = df.loc[df["canonical_id"] == p.product_id, "stem"]
        if stem.empty:
            return None
        ids = df.loc[df["stem"] == stem.iloc[0], "canonical_id"].unique()
        verified = [self.catalog.products[i] for i in ids if i in self.catalog.products
                    and self.catalog.products[i].ingredients]
        if not verified or len({frozenset(v.ingredients) for v in verified}) != 1 \
                or any(v.requires_prescription for v in verified):
            return None
        return verified[0]

    # ------------------------------------------------ facts -> cards (Phase 11; wording owned by cards.py)
    def _facts(self, dec: Decision, req, s: ctx.Session) -> tuple[list[C.Card], list[str] | None, dict]:
        extra: dict = {}
        if dec.action in ("emergency", "refuse_misuse") or dec.banned:
            return [], None, extra
        lines: list[C.Card] = []
        if "store" in req.intents or s.pending == "need_pincode" or (req.pincode and s.last_intents and "store" in s.last_intents):
            if req.pincode:
                stores = nearest_kendras(req.pincode)
                extra["stores"] = stores
                s.pending = None
                lines.append(C.StoreCard(req.pincode, stores))
            else:
                s.pending = "need_pincode"
                lines.append(C.StoreCard(None, asked_for_pincode=True))
        shown: list[str] | None = None
        answers: list[HealthAnswer] = []
        no_advice = dec.prescribing_request or dec.diagnosis_request or dec.dosing_request
        missed = dec.missed_dose and not no_advice   # answered by the curated missed-dose guidance, not a monograph
        wants_health = not no_advice and not missed and any(i in req.intents for i in ("info", "compare", "interaction"))
        meds = [(mv.product.name if mv.product else mv.mention.name,
                 mv.product.composition if mv.product else None,
                 mv.product.ingredients if mv.product else (mv.mention.ref,),
                 mv.product.product_id if mv.product else None) for mv in dec.medicines[:4]]
        if wants_health and "interaction" in req.intents and len(meds) >= 2:
            items = [ix.Item(n, tuple(ings)) for n, _, ings, _ in meds]
            found = ix.check(items)
            extra["interactions"] = [f.as_contract() for f in found]
            txt, cites = ix.render(items, found)
            lines.append(C.InteractionCard(txt, "check", extra["interactions"]))
            answers.append(HealthAnswer("", ix_cites(cites), ["interactions"], [], True))
            wants_health = False
        elif wants_health and "interaction" in req.intents and len(meds) == 1 and len(meds[0][2]) == 1 \
                and not re.search(r"alcohol|drink|beer|wine|sharab|shara?ab|daa?ru|milk|food", text_l(req)):
            ing = meds[0][2][0]
            partners = ix.known_partners(ing)
            if partners:
                extra["interactions"] = [{"kind": "known_partner", "ingredient_a": ing, "ingredient_b": n,
                                          "severity": sev} for n, sev in partners]
                lines.append(C.InteractionCard(
                    f"Medicines with a major or moderate interaction with {ing} (DDInter) [1]: "
                    + ", ".join(f"{n} ({sev.lower()})" for n, sev in partners)
                    + ". This is not a complete list. " + ix.ADVICE, "known_partners", extra["interactions"]))
                answers.append(HealthAnswer("", ix_cites([ix.DDINTER]), ["interactions"], [], True))
                wants_health = False
        compare = wants_health and "compare" in req.intents and len(meds) >= 2
        for mv in dec.medicines[:2]:
            p = mv.product
            if not p:
                lines.append(C.MedicineCard(mv.mention.name, generic=True, category=mv.category))
                if wants_health and not answers or compare:
                    a = answer_medicine(mv.mention.name, None, (mv.mention.ref,), req.text,
                                        habit_forming=habit_forming_set((mv.mention.ref,)),
                                        sections_override=["uses"] if compare else None)
                    answers.append(a)
                    if a.text:
                        lines.append(info_card(a, answers[:-1]))
                continue
            card = C.MedicineCard(p.name, p.product_id, p.composition, p.category)
            lines.append(card)
            if wants_health and not answers or compare:
                info = self._brand_info_product(mv)
                if info:
                    card.info_from, card.brand = info.name, mv.mention.text.title()
                src = info or p
                hf = habit_forming(src.product_id)
                a = answer_medicine(src.name, src.composition, src.ingredients, req.text,
                                    habit_forming=hf if hf is not None else habit_forming_set(tuple(src.ingredients)),
                                    sections_override=["uses"] if compare else None,
                                    product_id=src.product_id, form=src.form)
                answers.append(a)
                if a.text:
                    lines.append(info_card(a, answers[:-1]))
            if "substitute" in req.intents and "substitutes" not in extra:
                res = refresh_with_live(find_substitutes(p, self.catalog, price_book()), self.catalog, self.prices)
                extra["substitutes"] = [c.as_contract() for c in res.substitutes]
                lines.append(C.SubstituteTable(render_substitutes(res), p.product_id, extra["substitutes"], res.note))
                # remember the list (catalog products only) for "the second one" / "the cheapest one"
                shown = [c.product_id for c in res.substitutes if c.tier == "brand"]
            if "price" in req.intents:
                quotes = self.prices.quotes(p)
                extra.setdefault("prices", []).extend(quotes)
                lines.append(C.PriceStrip(p.product_id, [dict(q, freshness=freshness(q)) for q in quotes[:4]]))
        if missed:
            a = answer_topic_id("missed_dose")
            if a:
                answers.append(a)
                lines.append(info_card(a, answers[:-1], kind="topic"))
        if compare:
            sets = [set(m[2]) for m in meds[:2]]
            extra_rows = [(n, sorted(set(ings) - other)) for (n, _, ings, _), other in ((meds[0], sets[1]), (meds[1], sets[0]))]
            card = C.CompareCard((meds[0][0], meds[1][0]), sets[0] == sets[1], meds[0][1] == meds[1][1],
                                 [(n, e) for n, e in extra_rows if e])
            if card.same_ingredients or card.extra:
                lines.append(card)
        if not dec.medicines and dec.action == "allow" and not no_advice and not lines:
            a = answer_topic(req.text)
            if a:
                answers.append(a)
                lines.append(info_card(a, [], kind="topic"))
        if answers:
            merged = merge_answers(answers)
            extra["health_answer"] = merged.as_contract()
            src = render_sources(merged)
            if src:
                lines.append(C.SourcesCard(src, extra["health_answer"]["citations"]))
        return lines, shown, extra


# ------------------------------------------------ health helpers
def text_l(req) -> str:
    return req.text.lower()


@lru_cache(maxsize=20_000)
def habit_forming(product_id: str) -> bool | None:
    rows = db_query("SELECT habit_forming FROM products WHERE product_id = %s", (product_id,))
    return rows[0][0] if rows and rows[0][0] is not None else None


@lru_cache(maxsize=20_000)
def habit_forming_set(ingredients: tuple[str, ...]) -> bool | None:
    """Habit-forming flag for an ingredient SET (generic name typed, or a listing without its own flag):
    yes if any monograph of exactly these ingredients says so; no only if all flagged ones say no."""
    if not ingredients:
        return None
    ings = sorted(set(ingredients))
    rows = db_query("SELECT bool_or(habit_forming), count(habit_forming) FROM products "
                    "WHERE ingredients @> %s::text[] AND ingredients <@ %s::text[]", (ings, ings))
    return rows[0][0] if rows and rows[0][1] else None


def ix_cites(cites: list[tuple[str, str]]):
    from medibot.health.answer import Citation
    return [Citation(i + 1, t, u) for i, (t, u) in enumerate(cites)]


def _offset(prev: list[HealthAnswer]) -> int:
    return sum(len(a.citations) for a in prev)


DISCLAIMER_HASH = hashlib.sha256(msg.DISCLAIMER.encode()).hexdigest()[:16]
FULL_EVERY = 5   # repeat the full disclaimer every Nth medical turn


MEDICAL_WORDS = re.compile(r"medicine|medication|tablet|capsule|syrup|drops?\b|cream|ointment|injection|dawai|dawa|"
                           r"goli|\brx\b|side ?effects?|substitute|generic|alternative|dose|pharmacy|chemist|"
                           r"price|kitne|rate|sasta|sasti", re.I)


def disclaimer_card(s: ctx.Session, medical: bool, dec: Decision, extra: dict, text: str = "",
                    intents: list[str] | None = None) -> C.Disclaimer | None:
    """Disclaimer policy (11.4). Short text on every medical turn (a medicine, a safety action, a health answer, or a
    medicine question we could not resolve — not greetings / off-topic); the FULL text on the first intercept and
    the first health answer of a session, every FULL_EVERY-th medical turn, and every medical turn until
    acknowledged. Lives in a card / the `disclaimer` field only, so response_text stays the facts + safety texts."""
    asked_about_medicine = bool(MEDICAL_WORDS.search(text)) and "greeting" not in (intents or [])
    if not medical and not extra.get("health_answer") and not asked_about_medicine:
        return None
    s.medical_turns += 1
    reasons = []
    if not s.acknowledged:
        reasons.append("not acknowledged")
    if dec.intercept and "intercept" not in s.full_shown_for:
        reasons.append("first intercept")
        s.full_shown_for.add("intercept")
    if extra.get("health_answer") and "health" not in s.full_shown_for:
        reasons.append("first health answer")
        s.full_shown_for.add("health")
    if s.medical_turns % FULL_EVERY == 0:
        reasons.append(f"every {FULL_EVERY}th medical turn")
    full = bool(reasons)
    return C.Disclaimer(msg.DISCLAIMER if full else msg.SHORT_DISCLAIMER, full, not s.acknowledged)


def compose(cards: list[C.Card]) -> str:
    """response_text from the cards: safety block, then the fact cards (one block, single newlines), then
    "Did you mean"; or the fallback. Same layout as the replies before cards existed."""
    safety = [c.render() for c in cards if isinstance(c, C.SAFETY_CARDS) and not isinstance(c, C.RefusalCard)]
    refusal = list(dict.fromkeys(c.render() for c in cards if isinstance(c, C.RefusalCard)))  # once, even if 2 cards
    facts = C.facts_text(cards)
    blocks = safety + refusal + ([facts] if facts else [])
    reply = "\n\n".join(blocks)
    for c in cards:
        if isinstance(c, C.Clarify):
            reply += "\n\n" + c.render()
    if not reply:
        reply = next((c.render() for c in cards if isinstance(c, C.Fallback)), C.Fallback().render())
    return reply


def info_card(a: HealthAnswer, prev: list[HealthAnswer], kind: str = "medicine") -> C.InfoCard:
    return C.InfoCard(renumber(a, prev), a.sections, a.missing, a.grounded, kind)


def renumber(a: HealthAnswer, prev: list[HealthAnswer]) -> str:
    """Citation numbers continue across several answers in one reply ([1][2] then [3] ...)."""
    off = _offset(prev)
    return re.sub(r"\[(\d+)\]", lambda m: f"[{int(m.group(1)) + off}]", a.text) if off else a.text


def merge_answers(answers: list[HealthAnswer]) -> HealthAnswer:
    from medibot.health.answer import Citation
    cites, off = [], 0
    for a in answers:
        cites += [Citation(c.n + off, c.title, c.url, c.note) for c in a.citations]
        off += len(a.citations)
    return HealthAnswer("", cites, [s for a in answers for s in a.sections], [m for a in answers for m in a.missing],
                        any(a.grounded for a in answers))


# ------------------------------------------------ model-first reader merge
SLANG = set("""wid wit abt bcz coz cuz thru dat dis wen hw r n y lol lmao lmfao rofl ngl idk idc wtf wth omg omfg bro bruh dude yo yoo yaar yar tbh smh fr pls plz
plss u ur wat wht k kk ok okay hmm hmmm umm uh ya yeah yea nah haha hehe btw imo imho fyi asap thx ty""".split())


def _rule_mention_is_safe_alone(m) -> bool:
    """A rule match the model did NOT list is kept only when it is an exact name made of rare words: a real brand
    the model missed ("alprax") keeps its intercept; slang or a near-miss of an English word ("lol", "ngl",
    "waking" -> Making, "cheapr" -> Chear) is dropped."""
    words = [w for w in tokenize(m.text) if not NUMBER.match(w) and not FORM_WORDS.match(w)]
    # judged on the BRAND word: "Medela Mini Electric Breast Pump" is a real product even though "mini",
    # "electric", "breast", "pump" are English words; "lol" / "wid" / "waking" fail on the brand word itself
    if not words or words[0] in SLANG or _common(words[0]):
        return False
    if m.kind == "ingredient":
        return True
    name = set(tokenize(m.name))
    return all(w in name for w in words)          # typed exactly, not a fuzzy look-alike


def merge_reading(now: list, reading, cat, message: str = "") -> list:
    """Rule mentions + the model's medicine phrases (resolved by OUR resolver, never trusted as-is)."""
    phrases = [set(tokenize(p)) for p in reading.medicines]
    kept = [m for m in now if any(set(tokenize(m.text)) & p for p in phrases) or _rule_mention_is_safe_alone(m)]
    for phrase in reading.medicines:
        found = find_mentions(phrase, cat) or model_named(phrase, cat, message)
        fix = reading.spelling.get(phrase)
        if not found and fix and spelling_close(phrase, fix):
            found = [replace(m, text=phrase, confident=False) for m in model_named(fix, cat, message)]
        if not any(m.confident for m in found) and fix:
            # the model's spelling fix ("naxodam" -> "Naxdom") is used only if OUR catalog knows it confidently and it
            # still looks like what was typed (no swap to another medicine); the user is asked "Did you mean …?"
            for m in find_mentions(fix, cat):
                if m.confident and spelling_close(phrase, fix):
                    found = [replace(m, text=phrase, confident=False, confidence=min(m.confidence, 85.0))]
                    break
        for m in found:
            if all(m.ref != x.ref for x in kept):
                kept.append(m)
    return kept


def model_named(phrase: str, cat, message: str = "") -> list:
    """The model says this phrase IS a medicine ("i pill"), so look it up directly: the free-text guards (no span may
    start on "i" or "pill") exist for raw text, not for a name the model identified. Still strict: a real catalog
    product whose name contains every typed word; several such products -> unsure, and the user is asked."""
    want = set(tokenize(phrase))
    if not want:
        return []
    hits = [h for h in cat.index.resolve(phrase, 8)
            if h.kind == "product" and h.product_id in cat.products and want <= set(tokenize(h.name))]
    if not hits:
        return []
    comps = {cat.products[h.product_id].composition_id for h in hits}
    # among matching products, the one sharing most words with the whole message ("i pill EMERGENCY ka price")
    said = set(tokenize(message))
    hits.sort(key=lambda h: -len(said & set(tokenize(h.name))))
    top = hits[0]
    return [Mention("product", top.product_id, top.name, (0, 0), phrase, min(top.confidence, 90.0),
                    confident=len(comps) == 1, brand_only=False,   # already a named product: no brand-stem grouping
                    alternatives=tuple(h.product_id for h in hits[1:3]))]


def spelling_close(typed_text: str, fixed: str) -> bool:
    """A spelling fix, not a different medicine: the brand words stay similar (naxodam ~ naxdom 92)."""
    from rapidfuzz import fuzz
    t = [w for w in tokenize(typed_text) if not NUMBER.match(w) and not FORM_WORDS.match(w)]
    f = [w for w in tokenize(fixed) if not NUMBER.match(w) and not FORM_WORDS.match(w)]
    return bool(t and f) and fuzz.ratio(t[0], f[0]) >= 70 and t[0][0] == f[0][0]


def rules_intents(text: str) -> list[str]:
    return _rules(text).intents
