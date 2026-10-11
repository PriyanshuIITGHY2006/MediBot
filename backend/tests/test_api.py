"""Phase 12 API: PS schema, safety through HTTP, privacy, caps, rate limit, never a 500."""
import os

import pytest

os.environ["MEDIBOT_LLM"] = "off"
os.environ["MEDIBOT_RATE_PER_MIN"] = "1000"

from fastapi.testclient import TestClient  # noqa: E402

from medibot.api import app as api  # noqa: E402
from medibot.safety import messages as msg  # noqa: E402

PS_KEYS = {"user_query", "session_id", "disclaimer_acknowledged", "safety_guard", "detected_medication",
           "substitutes", "disclaimer"}


@pytest.fixture(scope="module")
def client():
    with TestClient(api.app) as c:
        yield c


def test_session_start_and_ack(client):
    s = client.post("/api/v1/session/start").json()
    assert s["requires_acknowledgement"] and s["disclaimer"] == msg.DISCLAIMER
    assert client.post("/api/v1/session/ack", json={"session_id": s["session_id"]}).json()["disclaimer_acknowledged"]


def test_ps_example_query_matches_the_schema(client):
    r = client.post("/api/v1/medibot/query", json={"user_query": "Can I get a cheaper alternative to Augmentin 625 Duo?",
                                                   "disclaimer_acknowledged": True}).json()
    assert PS_KEYS <= set(r)
    g = r["safety_guard"]
    assert g["is_restricted_schedule_h"] and g["intercept_triggered"] and g["mandated_prompt"] == msg.MANDATED_PROMPT
    assert r["response_text"].startswith(msg.MANDATED_PROMPT)
    dm = r["detected_medication"]
    assert dm["brand_name"].startswith("Augmentin 625") and dm["schedule"].startswith("Schedule H")
    s = r["substitutes"][0]
    assert s["composition_identically_verified"] and s["savings_percentage"] > 25 and "doctor" in s["user_advisory"]
    assert isinstance(s["partner_price_comparison"], list) and r["disclaimer_acknowledged"] is True


def test_otc_price_is_not_intercepted(client):
    r = client.post("/api/v1/medibot/query", json={"user_query": "Dolo 650 price"}).json()
    assert not r["safety_guard"]["intercept_triggered"] and r["detected_medication"]["schedule"] == "OTC"


def test_emergency_over_http(client):
    r = client.post("/api/v1/medibot/query", json={"user_query": "my dad isnt waking up and hes breathing weird"}).json()
    assert r["safety_guard"]["is_emergency"] and "112" in r["response_text"]


def test_multi_turn_keeps_the_session(client):
    sid = client.post("/api/v1/session/start").json()["session_id"]
    client.post("/api/v1/medibot/query", json={"user_query": "augmentin 625 price", "session_id": sid})
    r = client.post("/api/v1/medibot/query", json={"user_query": "iska sasta option?", "session_id": sid}).json()
    assert r["substitutes"] and r["detected_medication"]["brand_name"].startswith("Augmentin 625")


@pytest.mark.parametrize("body,code", [
    ({"user_query": ""}, 422),
    ({"user_query": "x" * 1001}, 422),
    ({"user_query": "dolo", "session_id": "../../etc"}, 422),
    ({"user_query": 5}, 422),
    ({}, 422),
])
def test_bad_input_is_rejected_not_crashed(client, body, code):
    assert client.post("/api/v1/medibot/query", json=body).status_code == code


def test_control_characters_are_cleaned(client):
    r = client.post("/api/v1/medibot/query", json={"user_query": "dolo\x00 650\x07 price"})
    assert r.status_code == 200 and r.json()["detected_medication"]


def test_crash_returns_safe_json(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("simulated")
    monkeypatch.setattr(api.bot(), "query", boom)
    with TestClient(api.app, raise_server_exceptions=False) as c:
        r = c.post("/api/v1/medibot/query", json={"user_query": "dolo 650 price"})
    assert r.status_code == 503 and r.json()["response_text"] == msg.FALLBACK_ERROR and "Traceback" not in r.text


def test_rate_limit(monkeypatch):
    monkeypatch.setattr(api, "RATE", 3)
    api._hits.clear()
    with TestClient(api.app) as c:
        codes = [c.post("/api/v1/session/start").status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[3:] == [429, 429]
    api._hits.clear()


def test_feedback_metrics_and_forget_me(client):
    from medibot.api import store
    sid = client.post("/api/v1/session/start").json()["session_id"]
    t = client.post("/api/v1/medibot/query", json={"user_query": "dolo 650 price", "session_id": sid}).json()
    fb = client.post("/api/v1/feedback", json={"session_id": sid, "turn_id": t["turn_id"], "rating": 5,
                                                "comment": "great, call me on 9876543210"}).json()
    if not store.available():
        pytest.skip("database not reachable")
    assert fb["stored"]
    rows = store._exec("SELECT comment FROM api_feedback WHERE session_hash = %s", (store.h(sid),))
    assert rows and "9876543210" not in rows[0][0]                       # PII scrubbed
    assert not store._exec("SELECT 1 FROM api_turns WHERE session_hash = %s AND intent IS NULL", (store.h(sid),))
    m = client.get("/api/v1/metrics").json()
    assert m["storage"] == "ok" and m["turns"] >= 1 and m["csat"]["ratings"] >= 1
    gone = client.delete(f"/api/v1/session/{sid}").json()
    assert gone["forgotten"] and gone["rows_deleted"] >= 3
    assert not store._exec("SELECT 1 FROM api_turns WHERE session_hash = %s", (store.h(sid),))


def test_optimize_bill(client):
    r = client.post("/api/v1/optimize", json={"items": [{"name": "Augmentin 625 Duo", "quantity": 10},
                                                       {"name": "Dolo 650", "quantity": 30},
                                                       {"name": "zzzqqq", "quantity": 1}]}).json()
    by = {i["input"]: i for i in r["items"]}
    assert by["Augmentin 625 Duo"]["mandated_prompt"] == msg.MANDATED_PROMPT
    assert by["zzzqqq"]["status"] == "not_recognised"
    assert r["monthly_savings_inr"] > 0 and 0 < r["savings_percentage"] < 100 and "doctor" in r["advisory"]


def test_health(client):
    h = client.get("/health").json()
    assert h["status"] == "ok" and h["catalog_products"] > 100000
