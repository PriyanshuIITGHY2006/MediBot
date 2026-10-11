"""Request bodies. Every text field has its control characters removed and a length cap, so bad input is a 422,
never a crash. Response shapes are documented in docs/API.md (the PS schema first, then MediBot's extras)."""
from __future__ import annotations

import os
import re

from pydantic import BaseModel, Field, field_validator

MAX_CHARS = int(os.environ.get("MEDIBOT_MAX_INPUT_CHARS", "1000"))
SESSION_ID = r"^[A-Za-z0-9_-]+$"


class _Text(BaseModel):
    @field_validator("*", mode="before")
    @classmethod
    def _strip(cls, v):
        if isinstance(v, str):
            v = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", v).strip()   # control characters out
        return v


class SessionRef(_Text):
    session_id: str = Field(min_length=8, max_length=64, pattern=SESSION_ID)


class QueryIn(_Text):
    user_query: str = Field(min_length=1, max_length=MAX_CHARS)
    session_id: str | None = Field(default=None, min_length=8, max_length=64, pattern=SESSION_ID)
    disclaimer_acknowledged: bool = False
    language: str = Field(default="en", pattern=r"^(en|hi)$")    # display language of the cards (Phase 15.4)


class FeedbackIn(SessionRef):
    turn_id: str | None = Field(default=None, max_length=64)
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=500)


class OptimizeItem(_Text):
    name: str = Field(min_length=2, max_length=120)
    quantity: int = Field(default=1, ge=1, le=1000)          # units (tablets / ml) per month


class OptimizeIn(_Text):
    items: list[OptimizeItem] = Field(min_length=1, max_length=25)


class BillItem(_Text):
    name: str = Field(min_length=2, max_length=120)
    quantity: int = Field(default=10, ge=1, le=1000)         # units (tablets / ml / g) needed
    product_id: str | None = Field(default=None, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")


class BillPlanIn(_Text):
    items: list[BillItem] = Field(min_length=1, max_length=25)
    allow_alternatives: bool = True
    max_pharmacies: int | None = Field(default=None, ge=1, le=5)


class BillParseIn(_Text):
    text: str = Field(min_length=2, max_length=MAX_CHARS * 3)


class CabinetItem(_Text):
    product_id: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    per_day: float = Field(gt=0, le=50)                       # units a day, as the user's prescription says


class CabinetIn(_Text):
    items: list[CabinetItem] = Field(min_length=1, max_length=25)
