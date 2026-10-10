"""Safety Kernel: the deterministic decision for every message. No LLM is involved in this decision.

Order (first match wins for the response type; flags accumulate):
  1. emergency / self-harm            -> emergency card only
  2. banned medicine mentioned        -> mandated prompt + banned notice
  3. restricted medicine mentioned    -> mandated prompt first (then allowed info)
     (any of several mentioned medicines being restricted is enough)
  4. misuse / prescription-seeking    -> mandated prompt (if a medicine is involved) + refusal
  5. diagnosis request / symptom talk -> refusal + general guidance
  6. prescribing / dosing request     -> refusal
  7. otherwise                        -> allowed (OTC or no medicine)
Every decision carries a safety receipt: what fired and why.
"""
from __future__ import annotations

from collections import Counter

from dataclasses import dataclass, field

from medibot.catalog import Catalog, Product
from medibot.mentions import Mention, find_mentions, tokenize
from medibot.safety import detectors as d
from medibot.safety import messages as msg


@dataclass
class MedicineVerdict:
    mention: Mention
    product: Product | None
    restricted: bool
    banned: bool
    category: str
    reason: str
    legal_ref: str


@dataclass
class Decision:
    action: str                                   # emergency | banned | intercept | refuse_diagnosis | refuse_prescribing
                                                  # | refuse_dosing | refuse_misuse | allow
    intercept: bool = False                       # mandated prompt must be shown first
    banned: bool = False
    emergency: bool = False
    self_harm: bool = False
    diagnosis_request: bool = False
    prescribing_request: bool = False
    dosing_request: bool = False
    missed_dose: bool = False                     # "I missed a dose": general guidance (never an amount)
    rx_seeking: bool = False
    misuse: bool = False
    jailbreak: bool = False
    medicines: list[MedicineVerdict] = field(default_factory=list)
    receipt: list[str] = field(default_factory=list)

    @property
    def focus(self) -> MedicineVerdict | None:
        """The medicine the reply is about: the first restricted one, else the first mentioned."""
        for m in self.medicines:
            if m.restricted:
                return m
        return self.medicines[0] if self.medicines else None


def brand_majority(mention: Mention, catalog: Catalog, message: str = "") -> tuple[Product, str] | None:
    """Brand typed alone ("calpol", "digene"): decide by the brand's variants, not one arbitrary listing.
    Restricted if at least half of the verified variants are restricted (Calpol tablets are OTC; Calpol T is not)."""
    df = catalog.index.df
    stem = df.loc[df["canonical_id"] == mention.ref, "stem"]
    if stem.empty:
        return None
    ids = df.loc[df["stem"] == stem.iloc[0], "canonical_id"].unique()
    top = catalog.products.get(mention.ref)
    unusual = {"injection", "kit", "other"}
    variants = [catalog.products[i] for i in ids if i in catalog.products and catalog.products[i].composition
                and (catalog.products[i].form not in unusual or (top and top.form in unusual))]
    if len(variants) < 2:
        return None
    restricted = [v for v in variants if v.requires_prescription]
    pop = dict(zip(df["canonical_id"], df["popularity"]))
    sets = Counter(frozenset(v.ingredients) for v in variants)
    odd = ("dangler", "assorted", "combo", "kit", "pack of", "on the go")

    typed = set(tokenize(message))

    def flagship(group: list[Product]) -> Product:
        # the user named THIS listing beyond the brand ("Deriva I 10mg Capsule"): keep it
        if top is not None and top in group:
            if all(w in typed for w in tokenize(top.name)[1:]):  # every word after the brand was typed
                return top
        """The variant people usually mean: the brand's most common ingredient set, a plain tablet, popular, short
        name ("crocin" -> Crocin Advance, not Crocin Pain Relief with caffeine; "combiflam" -> the tablet)."""
        return min(group, key=lambda v: (-sets[frozenset(v.ingredients)], any(w in v.name.lower() for w in odd),
                                         v.form != "tablet", -float(pop.get(v.product_id, 0) or 0), len(v.name)))
    tie = len(restricted) * 2 == len(variants)
    if (tie and top is not None and top.requires_prescription) or len(restricted) * 2 > len(variants):
        rep = flagship(restricted)
        return rep, f"brand typed alone: {len(restricted)}/{len(variants)} variants need a prescription"
    allowed = [v for v in variants if not v.requires_prescription]
    rep = flagship(allowed)  # a real product, not a promo pack
    return rep, f"brand typed alone: {len(allowed)}/{len(variants)} variants are OTC"


def judge_medicine(mention: Mention, catalog: Catalog, message: str = "") -> MedicineVerdict:
    if mention.kind == "product":
        p = catalog.product(mention.ref)
        if p is None:
            return MedicineVerdict(mention, None, True, False, "unknown", "product not in catalog -> prescription by default", "")
        if mention.brand_only:
            bm = brand_majority(mention, catalog, message)
            if bm:
                rep, why = bm
                return MedicineVerdict(mention, rep, rep.requires_prescription, rep.category == "banned", rep.category,
                                       f"{why}; e.g. {rep.name}: {rep.reasons or rep.category}", rep.legal_refs)
        return MedicineVerdict(mention, p, p.requires_prescription, p.category == "banned", p.category,
                               p.reasons or p.category, p.legal_refs)
    ing = catalog.ingredient(mention.ref)
    if ing is None:
        return MedicineVerdict(mention, None, True, False, "unknown", "ingredient not known -> prescription by default", "")
    # generic name typed: assume the usual (oral) use; restricted unless allowed OTC by mouth and unscheduled
    if ing.schedule in {"X", "NDPS"}:
        return MedicineVerdict(mention, None, True, False, "controlled", f"{ing.name}: controlled substance", ing.schedule_refs)
    if ing.schedule == "H1":
        return MedicineVerdict(mention, None, True, False, "schedule_h1", f"{ing.name}: Schedule H1", ing.schedule_refs)
    if ing.schedule == "H":
        return MedicineVerdict(mention, None, True, False, "schedule_h", f"{ing.name}: Schedule H", ing.schedule_refs)
    if ing.is_corticosteroid or not ing.oral_otc:
        return MedicineVerdict(mention, None, True, False, "prescription", f"{ing.name}: not on the OTC list", "")
    return MedicineVerdict(mention, None, False, False, "otc", f"{ing.name}: OTC by mouth", "")


def decide(text: str, catalog: Catalog, context_medicines: list[Mention] | None = None,
           mentions: list[Mention] | None = None) -> Decision:
    dec = Decision(action="allow")
    lowered = text.lower()

    # 1. emergencies first: nothing else matters
    if d.first(d.EMERGENCY_SELF_HARM, lowered):
        dec.action, dec.emergency, dec.self_harm = "emergency", True, True
        dec.receipt.append(f"self-harm signal: '{d.first(d.EMERGENCY_SELF_HARM, lowered)}'")
        return dec
    if hit := d.first(d.EMERGENCY, lowered):
        dec.action, dec.emergency = "emergency", True
        dec.receipt.append(f"emergency signal: '{hit}'")
        return dec

    # flags
    dec.jailbreak = bool(d.first(d.JAILBREAK, lowered))
    dec.misuse = bool(d.first(d.MISUSE, lowered))
    dec.rx_seeking = bool(d.first(d.RX_SEEKING, lowered))
    dec.diagnosis_request = bool(d.first(d.DIAGNOSIS_REQUEST, lowered) or d.first(d.SYMPTOM_STATEMENT, lowered))
    dec.prescribing_request = bool(d.first(d.PRESCRIBING_REQUEST, lowered))
    dec.missed_dose = bool(d.first(d.MISSED_DOSE, lowered))
    dec.dosing_request = bool(d.first(d.DOSING_REQUEST, d.MISSED_DOSE.sub(" ", lowered)))
    if dec.missed_dose:
        dec.receipt.append("missed-dose question -> general guidance only" +
                           (" (a dosing request is also present -> refused)" if dec.dosing_request else ""))
    if dec.jailbreak:
        dec.receipt.append("jailbreak / instruction-override attempt ignored (safety rules are not instructions)")

    # medicines: mentioned now, else carried over from the conversation
    explicit = mentions is not None
    if not explicit:
        mentions = find_mentions(text, catalog)
    if not mentions and context_medicines:
        mentions = list(context_medicines)
        dec.receipt.append("no medicine named -> using the medicine from the conversation")
    dec.medicines = [judge_medicine(m, catalog, text) for m in mentions]
    for mv in dec.medicines:
        dec.receipt.append(f"{mv.mention.name}: {mv.category} ({mv.reason})" + (f" [{mv.legal_ref}]" if mv.legal_ref else ""))

    # 2-3. banned / restricted medicines -> mandated prompt
    if any(m.banned for m in dec.medicines):
        dec.action, dec.banned, dec.intercept = "banned", True, True
    elif any(m.restricted for m in dec.medicines):
        dec.action, dec.intercept = "intercept", True

    # 4. misuse is always intercepted, with or without a named medicine
    if dec.misuse:
        dec.intercept = True
        if dec.action == "allow":
            dec.action = "refuse_misuse"
        dec.receipt.append("misuse intent -> intercept + refusal")
    if dec.rx_seeking and dec.medicines and not dec.intercept:
        # asking to bypass a prescription for an OTC product is fine; for anything restricted it is already intercepted
        dec.receipt.append("prescription-bypass question about an OTC product -> allowed")

    # 5-6. refusals (do not override an intercept: the mandated prompt still comes first)
    if dec.action == "allow":
        if dec.diagnosis_request:
            dec.action = "refuse_diagnosis"
        elif dec.prescribing_request and not dec.medicines:
            dec.action = "refuse_prescribing"
            dec.diagnosis_request = True  # schema: is_diagnosis_detected covers diagnose/prescribe requests
        elif dec.dosing_request:
            dec.action = "refuse_dosing"
    if dec.prescribing_request:
        dec.diagnosis_request = True
    return dec


def safety_lines(dec: Decision) -> list[str]:
    """The fixed safety texts that must appear in the reply, in order."""
    if dec.action == "emergency":
        return [msg.SELF_HARM if dec.self_harm else msg.EMERGENCY]
    out = []
    if dec.intercept:
        out.append(msg.MANDATED_PROMPT)
    if dec.banned:
        ref = next((m.legal_ref.split(" | ")[0] for m in dec.medicines if m.banned), "Section 26A notification")
        out.append(msg.banned_notice(ref))
    if dec.misuse:
        out.append(msg.MISUSE_REFUSAL)
    elif dec.rx_seeking and dec.intercept:
        out.append(msg.RX_SEEKING_REFUSAL)
    if dec.action == "refuse_diagnosis" or (dec.diagnosis_request and not dec.prescribing_request and dec.action != "allow"):
        out.append(msg.DIAGNOSIS_REFUSAL)
    if dec.prescribing_request and dec.action in ("refuse_prescribing", "intercept", "refuse_diagnosis"):
        out.append(msg.PRESCRIBING_REFUSAL)
    if dec.dosing_request:
        out.append(msg.DOSING_REFUSAL)
    return out
