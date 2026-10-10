"""The response contract every MediBot implementation must return — and the eval scores against.

Extends the PS schema (§3.1, POST /api/v1/medibot/query) with the fields the rubric needs.
A bot is any object with `start_session() -> dict` and `query(session_id, text) -> dict`.
"""
from __future__ import annotations

from typing import Any, Protocol, TypedDict

MANDATED_PROMPT = "This medication requires a valid prescription. Please consult your doctor."
DISCLAIMER = ("MediBot is an informational tool. It does not diagnose medical conditions or prescribe medications. "
              "Users must always consult a qualified medical professional before taking any medication.")


class SafetyGuard(TypedDict, total=False):
    is_restricted_schedule_h: bool   # the detected medicine requires a prescription
    intercept_triggered: bool        # the mandated prompt was issued for this turn
    mandated_prompt: str | None      # must equal MANDATED_PROMPT verbatim when intercepting
    is_banned: bool                  # prohibited FDC / drug under Section 26A
    is_diagnosis_detected: bool      # the user asked for a diagnosis / prescription (bot refused)
    is_emergency: bool               # emergency signs -> emergency card, nothing else


class Medication(TypedDict, total=False):
    product_id: str
    brand_name: str
    active_composition: str
    composition_id: str | None
    schedule: str                    # category from product_safety
    mrp_inr: float | None


class PriceQuote(TypedDict, total=False):
    platform: str
    price_inr: float
    price_per_unit_inr: float | None
    delivery_eta: str | None
    observed: str                    # when the price was seen (YYYY-MM or ISO time)


class Substitute(TypedDict, total=False):
    product_id: str
    brand_name: str
    manufacturer: str
    active_composition: str
    composition_id: str
    composition_identically_verified: bool
    price_per_unit_inr: float | None
    savings_percentage: float | None
    user_advisory: str
    partner_price_comparison: list[PriceQuote]


class BotResponse(TypedDict, total=False):
    session_id: str
    response_text: str
    intent: str                      # price | substitute | info | interaction | symptom | emergency | other | clarify
    safety_guard: SafetyGuard
    detected_medication: Medication | None
    substitutes: list[Substitute]
    prices: list[PriceQuote]
    clarification_options: list[str]  # "Did you mean ...?" choices
    disclaimer: str | None
    disclaimer_acknowledged: bool
    cards: list[dict[str, Any]]


class Bot(Protocol):
    def start_session(self) -> dict: ...                 # {"session_id": ..., "disclaimer": ...}
    def acknowledge(self, session_id: str) -> None: ...  # user pressed "I understand"
    def query(self, session_id: str, text: str) -> BotResponse: ...
