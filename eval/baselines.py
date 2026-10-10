"""Reference bots that sanity-check the eval itself (not real MediBot implementations).

NullBot        never intercepts, never recognises anything  -> A1 must be 0%, A2 0%
AlwaysBlockBot intercepts every message                      -> A1 100%, A2 100% (every OTC wrongly blocked)
"""
from __future__ import annotations

import uuid

from eval.contract import DISCLAIMER, MANDATED_PROMPT


class NullBot:
    def start_session(self):
        return {"session_id": uuid.uuid4().hex, "disclaimer": None}

    def acknowledge(self, session_id):
        pass

    def query(self, session_id, text):
        return {"session_id": session_id, "response_text": "Sorry, I can't help with that yet.",
                "safety_guard": {"intercept_triggered": False}, "detected_medication": None, "substitutes": []}


class AlwaysBlockBot:
    def start_session(self):
        return {"session_id": uuid.uuid4().hex, "disclaimer": DISCLAIMER}

    def acknowledge(self, session_id):
        pass

    def query(self, session_id, text):
        return {"session_id": session_id, "response_text": MANDATED_PROMPT,
                "safety_guard": {"intercept_triggered": True, "mandated_prompt": MANDATED_PROMPT, "is_banned": False},
                "detected_medication": None, "substitutes": [], "disclaimer": DISCLAIMER}
