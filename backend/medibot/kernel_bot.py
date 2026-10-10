"""KernelBot: the Safety Kernel wrapped in the eval Bot contract, with templated (non-LLM) replies.

Used to measure the guard on the eval set before the LLM layers exist. Safety texts come from
medibot.safety.messages; the informational part is a short template from catalog facts.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

from medibot.catalog import load_catalog
from medibot.mentions import Mention
from medibot.safety import messages as msg
from medibot.safety.kernel import Decision, decide, safety_lines
from medibot.safety.output_check import violations


@dataclass
class Session:
    acknowledged: bool = False
    medicines: list[Mention] = field(default_factory=list)


def guess_intent(text: str) -> str:
    t = text.lower()
    if re.search(r"cheap|sasta|sasti|alternative|substitute|generic|same as|option", t):
        return "substitute"
    if re.search(r"price|cost|rate|kitne|how much is|buy|where", t):
        return "price"
    if re.search(r"together|interact|with alcohol|and \w+ together", t):
        return "interaction"
    return "info"


class KernelBot:
    def __init__(self):
        self.catalog = load_catalog()
        self.sessions: dict[str, Session] = {}

    def start_session(self):
        sid = uuid.uuid4().hex
        self.sessions[sid] = Session()
        return {"session_id": sid, "disclaimer": msg.DISCLAIMER, "requires_acknowledgement": True}

    def acknowledge(self, session_id):
        self.sessions.setdefault(session_id, Session()).acknowledged = True

    def query(self, session_id, text):
        s = self.sessions.setdefault(session_id, Session())
        dec = decide(text, self.catalog, context_medicines=s.medicines)
        if dec.medicines:
            s.medicines = [m.mention for m in dec.medicines]
        parts = safety_lines(dec)
        info = self._info(dec)
        if info and dec.action not in ("emergency",):
            parts.append(info)
        reply = "\n\n".join(parts)
        bad = violations(info or "")
        if bad:  # never ship an unsafe informational sentence
            parts = [p for p in parts if p != info] + [msg.PRESCRIBING_REFUSAL]
            reply = "\n\n".join(parts)
            dec.receipt.append(f"output check replaced text ({', '.join(bad)})")
        focus = dec.focus
        product = focus.product if focus else None
        clarify = []
        if focus and not focus.mention.confident:
            names = [focus.mention.name] + [self.catalog.products[a].name for a in focus.mention.alternatives
                                            if a in self.catalog.products]
            clarify = names[:3]
            parts.append("Did you mean: " + " / ".join(clarify) + "?")
            reply = "\n\n".join(parts)
        medical = bool(dec.medicines) or dec.action != "allow"
        return {
            "session_id": session_id,
            "response_text": reply or "I can help with medicine prices, cheaper identical alternatives and general "
                                      "medicine information. Which medicine are you asking about?",
            "intent": "emergency" if dec.emergency else ("symptom" if dec.diagnosis_request else guess_intent(text)),
            "safety_guard": {
                "is_restricted_schedule_h": bool(focus and focus.restricted),
                "intercept_triggered": dec.intercept,
                "mandated_prompt": msg.MANDATED_PROMPT if dec.intercept else None,
                "is_banned": dec.banned,
                "is_diagnosis_detected": dec.diagnosis_request,
                "is_emergency": dec.emergency,
            },
            "detected_medication": ({"product_id": product.product_id, "brand_name": product.name,
                                     "active_composition": product.composition, "composition_id": product.composition_id,
                                     "schedule": product.category} if product else None),
            "substitutes": [],
            "clarification_options": clarify,
            "disclaimer": msg.SHORT_DISCLAIMER if medical else None,
            "disclaimer_acknowledged": s.acknowledged,
            "receipt": dec.receipt,
        }

    def _info(self, dec: Decision) -> str | None:
        if dec.action in ("emergency", "refuse_misuse"):
            return None
        lines = []
        for mv in dec.medicines[:2]:
            if mv.product:
                comp = mv.product.composition or "composition not verified"
                lines.append(f"{mv.product.name} — contains {comp}.")
            else:
                lines.append(f"{mv.mention.name.title()} is a generic medicine name.")
        return " ".join(lines) or None
