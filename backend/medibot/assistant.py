"""MediBot assistant: understanding -> context -> Safety Kernel -> facts -> reply. Implements the eval Bot contract.

The Safety Kernel is the only authority on what may be said; the LLM (understanding.py) only helps read
the message. Facts (prices, stores) come from the processed data, never from a model.
"""
from __future__ import annotations

import json
import re
import uuid
from functools import lru_cache
from pathlib import Path

import pandas as pd

from medibot import context as ctx
from medibot.catalog import load_catalog
from medibot.mentions import find_mentions
from medibot.safety import messages as msg
from medibot.safety.kernel import Decision, decide, safety_lines
from medibot.safety.output_check import violations
from medibot.prices.engine import PriceEngine, freshness
from medibot.substitutes import find_substitutes, refresh_with_live
from medibot.substitutes import render as render_substitutes
from medibot.understanding import understand
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
    return df[df["status"].eq(1)].assign(pin=lambda d: d["pinCode"].astype(str))  # owner name / phone never loaded


def nearest_kendras(pincode: str, n: int = 3) -> list[dict]:
    k = kendras()
    exact = k[k["pin"] == pincode]
    near = k[k["pin"].str[:3] == pincode[:3]] if len(exact) < n else exact.iloc[0:0]
    out = pd.concat([exact, near]).drop_duplicates("storeCode").head(n)
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
        self.sessions.setdefault(session_id, ctx.Session()).acknowledged = True

    def query(self, session_id: str, text: str) -> dict:
        s = self.sessions.setdefault(session_id, ctx.Session())
        cat = self.catalog
        now = find_mentions(text, cat)
        req = understand(text, have_mentions=bool(now), have_context=bool(s.focus))
        for w in req.medicine_words:  # LLM-suggested words still pass the deterministic resolver
            for m in find_mentions(w, cat):
                if m.confident and all(m.ref != x.ref for x in now):
                    now.append(m)
        follow_up = bool(re.match(r"^\s*(and|aur|or|what about|how about|and what about|also)\b", text.lower())) \
            or len(text.split()) <= 3
        if s.last_intents and req.intents == ["info"] and (not now or follow_up):
            req.intents = s.last_intents  # "and dolo 650?" / "price?" keeps the previous question type
        used, notes = ctx.resolve(req, now, s, cat)
        dec = decide(text, cat, mentions=used)
        dec.receipt = notes + dec.receipt
        if req.used_llm:
            dec.receipt.append("message read with LLM help (medicine words / intents only)")

        parts = safety_lines(dec)
        facts, shown, extra = self._facts(dec, req, s)
        reply = "\n\n".join(parts + ([facts] if facts else []))
        if facts and violations(facts):  # never ship an unsafe informational sentence
            reply = "\n\n".join(parts + [msg.PRESCRIBING_REFUSAL])
            dec.receipt.append("output check replaced the informational text")
        ctx.update(s, req, [m.mention for m in dec.medicines], shown)

        focus = dec.focus
        product = focus.product if focus else None
        clarify = []
        if focus and not focus.mention.confident:
            clarify = [focus.mention.name] + [cat.products[a].name for a in focus.mention.alternatives if a in cat.products]
            reply += "\n\nDid you mean: " + " / ".join(clarify[:3]) + "?"
        medical = bool(dec.medicines) or dec.action != "allow"
        intent = ("emergency" if dec.emergency else "symptom" if dec.diagnosis_request else
                  "price" if "price" in req.intents and "substitute" not in req.intents else req.intents[0])
        return {
            "session_id": session_id,
            "response_text": reply or ("I can help with medicine prices, identical cheaper alternatives, general "
                                       "medicine information and Jan Aushadhi stores. Which medicine are you asking about?"),
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
            "disclaimer": msg.SHORT_DISCLAIMER if medical else None,
            "disclaimer_acknowledged": s.acknowledged,
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

    # ------------------------------------------------ facts (templated; the LLM narrator comes later)
    def _facts(self, dec: Decision, req, s: ctx.Session) -> tuple[str | None, list[str] | None, dict]:
        extra: dict = {}
        if dec.action in ("emergency", "refuse_misuse") or dec.banned:
            return None, None, extra
        lines: list[str] = []
        if "store" in req.intents or s.pending == "need_pincode" or (req.pincode and s.last_intents and "store" in s.last_intents):
            if req.pincode:
                stores = nearest_kendras(req.pincode)
                extra["stores"] = stores
                s.pending = None
                if stores:
                    lines.append("Jan Aushadhi Kendras near " + req.pincode + ":\n" + "\n".join(
                        f"• {k['store_code']}: {k['address']}, {k['district']} {k['pincode']}" for k in stores))
                else:
                    lines.append(f"I couldn't find a Jan Aushadhi Kendra listed for pincode {req.pincode}.")
            else:
                s.pending = "need_pincode"
                lines.append("Please share your 6-digit pincode and I'll find the nearest Jan Aushadhi Kendras.")
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
            lines.append(txt)
            answers.append(HealthAnswer("", ix_cites(cites), ["interactions"], [], True))
            wants_health = False
        elif wants_health and "interaction" in req.intents and len(meds) == 1 and len(meds[0][2]) == 1 \
                and not re.search(r"alcohol|drink|beer|wine|sharab|daru|milk|food", text_l(req)):
            ing = meds[0][2][0]
            partners = ix.known_partners(ing)
            if partners:
                extra["interactions"] = [{"kind": "known_partner", "ingredient_a": ing, "ingredient_b": n,
                                          "severity": sev} for n, sev in partners]
                lines.append(f"Medicines with a major or moderate interaction with {ing} (DDInter) [1]: "
                             + ", ".join(f"{n} ({sev.lower()})" for n, sev in partners)
                             + ". This is not a complete list. " + ix.ADVICE)
                answers.append(HealthAnswer("", ix_cites([ix.DDINTER]), ["interactions"], [], True))
                wants_health = False
        compare = wants_health and "compare" in req.intents and len(meds) >= 2
        for mv in dec.medicines[:2]:
            p = mv.product
            if not p:
                lines.append(f"{mv.mention.name.title()} is a generic medicine name.")
                if wants_health and not answers or compare:
                    a = answer_medicine(mv.mention.name, None, (mv.mention.ref,), req.text,
                                        habit_forming=habit_forming_set((mv.mention.ref,)),
                                        sections_override=["uses"] if compare else None)
                    answers.append(a)
                    if a.text:
                        lines.append(renumber(a, answers[:-1]))
                continue
            lines.append(f"{p.name} — contains {p.composition or 'composition not verified'}.")
            if wants_health and not answers or compare:
                info = self._brand_info_product(mv)
                if info:
                    brand = mv.mention.text.title()
                    lines.append(f"{p.name} has no verified composition, so the information below is for {info.name}, "
                                 f"the {brand} product with a verified composition — other {brand} products may differ.")
                src = info or p
                hf = habit_forming(src.product_id)
                a = answer_medicine(src.name, src.composition, src.ingredients, req.text,
                                    habit_forming=hf if hf is not None else habit_forming_set(tuple(src.ingredients)),
                                    sections_override=["uses"] if compare else None,
                                    product_id=src.product_id, form=src.form)
                answers.append(a)
                if a.text:
                    lines.append(renumber(a, answers[:-1]))
            if "substitute" in req.intents and "substitutes" not in extra:
                res = refresh_with_live(find_substitutes(p, self.catalog, price_book()), self.catalog, self.prices)
                extra["substitutes"] = [c.as_contract() for c in res.substitutes]
                lines.append(render_substitutes(res))
                # remember the list (catalog products only) for "the second one" / "the cheapest one"
                shown = [c.product_id for c in res.substitutes if c.tier == "brand"]
            if "price" in req.intents:
                quotes = self.prices.quotes(p)
                extra.setdefault("prices", []).extend(quotes)
                for q in quotes[:4]:
                    unit = f", ₹{q['price_per_unit_inr']:.2f}/unit" if q.get("price_per_unit_inr") else ""
                    stock = "" if q.get("in_stock") is None else (" · in stock" if q["in_stock"] else " · out of stock")
                    lines.append(f"• {q['platform']}: ₹{q['price_inr']:.2f} ({q.get('pack_label') or 'pack'}{unit}) — "
                                 f"{freshness(q)}{stock}")
                    if q.get("above_nppa_ceiling"):
                        c = q["above_nppa_ceiling"]
                        lines.append(f"  ⚠ above the government ceiling price of ₹{c['ceiling_per_unit_inr']:.2f}/unit ({c['source']})")
                if not quotes:
                    lines.append("• No recent price on record for this pack.")
        if missed:
            a = answer_topic_id("missed_dose")
            if a:
                answers.append(a)
                lines.append(renumber(a, answers[:-1]))
        if compare:
            sets = [set(m[2]) for m in meds[:2]]
            if sets[0] == sets[1]:
                lines.append(f"{meds[0][0]} and {meds[1][0]} have the same active ingredients"
                             + (" (check the strengths above)." if meds[0][1] != meds[1][1] else "."))
            else:
                for (n, _, ings, _), other in ((meds[0], sets[1]), (meds[1], sets[0])):
                    extra_ings = sorted(set(ings) - other)
                    if extra_ings:
                        lines.append(f"{n} also contains {', '.join(extra_ings)}.")
        if not dec.medicines and dec.action == "allow" and not no_advice and not lines:
            a = answer_topic(req.text)
            if a:
                answers.append(a)
                lines.append(a.text)
        if answers:
            merged = merge_answers(answers)
            extra["health_answer"] = merged.as_contract()
            src = render_sources(merged)
            if src:
                lines.append(src)
        return ("\n".join(lines) or None), shown, extra


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
