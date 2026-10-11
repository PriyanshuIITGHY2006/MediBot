"""Bill / prescription photo -> medicine list (Phase 15.1). Two readers, local first:

  1. Tesseract, on this machine (default). The photo never leaves the server. Good on printed pharmacy bills and
     typed prescriptions; weak on handwriting.
  2. A vision model through the Cline gateway (MEDIBOT_OCR_MODEL, default a cheap Gemini Flash-Lite). OPT-IN only:
     the caller must pass vision=True, because the photo is sent to an outside service. Used when the user asks
     for it (e.g. a handwritten prescription) - never silently.

Either way the reader only proposes lines; every name is then matched against the catalog (the same mention
finder as the chat), quantities found on the page are kept, and the user edits the list before any plan is made.
Photos are never stored. A reader that fails returns an empty list with a reason, never an exception.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import subprocess

import httpx

from medibot.billsplit import parse_list
from medibot.llm import route
from medibot.mentions import find_mentions

MAX_BYTES = 8 * 1024 * 1024
OCR_MODEL = os.environ.get("MEDIBOT_OCR_MODEL", "cline:google/gemini-3.5-flash-lite")
VISION_TIMEOUT = float(os.environ.get("MEDIBOT_OCR_TIMEOUT", "25"))

# lines on a bill that are never medicines
_NOISE = re.compile(r"\b(total|sub\s*total|gst|cgst|sgst|igst|amount|discount|invoice|bill\s*no|date|phone|mob|"
                    r"gstin|dl\s*no|licen[cs]e|patient|doctor|dr\.|address|thank|cash|upi|balance|round\s*off|"
                    r"pharmacist|signature|batch|exp|hsn|mrp\s*total)\b", re.I)
# a strip / pack size printed in the name: 15's, 10 TAB, 1x10, strip of 15
_PACK = re.compile(r"\b(\d{1,3})\s*['’]?\s*s\b|\b1\s*[x×]\s*(\d{1,3})\b|strip\s+of\s+(\d{1,3})", re.I)

VISION_PROMPT = """This is a photo of an Indian pharmacy bill or a doctor's prescription. List every medicine on it.
Return only JSON: {"medicines": [{"name": string, "quantity": integer or null}]}
- name: the brand or generic name WITH strength and form as written (e.g. "Dolo 650 Tablet", "Pan 40", "Augmentin 625 Duo")
- quantity: total tablets / capsules / ml to buy if the page states it (a bill's Qty column times the pack size, or
  a prescription's count such as "x 10 days, twice daily" -> 20). null if not stated. Never guess.
- skip totals, taxes, doctor / patient / shop details. Do not add anything that is not on the page.
- if nothing is readable, return {"medicines": []}"""


class ReadError(ValueError):
    pass


def _load(data: bytes):
    from PIL import Image, ImageOps, UnidentifiedImageError
    if not data or len(data) > MAX_BYTES:
        raise ReadError("photo must be under 8 MB")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError):
        raise ReadError("that file isn't a readable image (use JPG, PNG or WebP)")
    if img.width * img.height > 40_000_000:
        raise ReadError("image is too large")
    return ImageOps.exif_transpose(img).convert("RGB")


def _tesseract_text(img) -> str:
    from PIL import ImageOps
    g = ImageOps.autocontrast(ImageOps.grayscale(img))
    if g.width < 1600:                                    # small phone crops read better upscaled
        k = 1600 / g.width
        g = g.resize((1600, int(g.height * k)))
    buf = io.BytesIO()
    g.save(buf, format="PNG")
    try:
        out = subprocess.run(["tesseract", "stdin", "stdout", "--psm", "6", "-l", "eng"], input=buf.getvalue(),
                             capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return out.stdout.decode("utf-8", "replace")


_FORM_PREFIX = re.compile(r"^\s*(?:\d{1,2}\s*[.)]\s*)?(?:tab(?:let)?s?|cap(?:sule)?s?|syp|syrup|inj|oint)\.?\s+", re.I)
_DOSE = re.compile(r"\b([0-3])\s*-\s*([0-3])\s*-\s*([0-3])\b|\b([o0]d|bd|bid|tds|tid|qid|hs)\b", re.I)
_DAYS = re.compile(r"(?:[x×*]\s*|for\s+)(\d{1,3})\s*(?:days?|d)\b", re.I)
_PER_DAY = {"od": 1, "hs": 1, "bd": 2, "bid": 2, "tds": 3, "tid": 3, "qid": 4}


def _rx_quantity(s: str) -> tuple[int | None, int]:
    """Prescription line -> (units, where the dosing starts). "1-0-1 x 5 days" -> 10, "OD x 15 days" -> 15. Only
    arithmetic on what is written: no dose pattern or no day count -> None."""
    d, n = _DOSE.search(s), _DAYS.search(s)
    start = min([m.start() for m in (d, n) if m] or [len(s)])
    if not (d and n):
        return None, start
    per_day = sum(int(g) for g in d.groups()[:3]) if d.group(1) else _PER_DAY[d.group(4).lower().replace("0", "o")]
    return (per_day * int(n.group(1)) or None), start


def _lines_from_text(text: str, catalog) -> list[dict]:
    """OCR text -> lines that name a catalog product. Bill rows ("DOLO 650 TAB 15's 2 32.28 64.56"): the name is
    what comes before the pack size, quantity = strips x pack size. Prescription rows ("1. Tab Dolo 650 1-0-1 x 5
    days"): the name is what comes before the dosing, quantity = doses per day x days."""
    out = []
    for raw in text.splitlines():
        s = re.sub(r"[|_=~`]+", " ", raw).strip()
        if len(s) < 3 or _NOISE.search(s) or not re.search(r"[A-Za-z]{3}", s):
            continue
        s = _FORM_PREFIX.sub("", s)
        qty, cut = _rx_quantity(s)
        pack = _PACK.search(s)
        if pack and pack.start() < cut:
            cut = pack.start()
            pack_n = next(int(g) for g in pack.groups() if g)
            strips = re.findall(r"(?<![\d.])(\d{1,2})(?![\d.'’])", s[pack.end():])
            qty = pack_n * (int(strips[0]) if strips else 1)
        head = re.split(r"\s(?:\d+\.\d{2}|₹|rs\.?\s*\d)", s[:cut], maxsplit=1, flags=re.I)[0].strip(" -:,.")
        if len(head) < 3 or not [m for m in find_mentions(head, catalog) if m.kind == "product"]:
            continue
        if qty is None:                                      # a typed list line: "Dolo 650 x 30"
            parsed = parse_list(s)
            if parsed and parsed[0]["quantity_given"]:
                qty = parsed[0]["quantity"]
        out.append({"name": head[:120], "quantity": qty})
    return out


def _vision(img) -> tuple[list[dict], str | None]:
    url, key, model = route(OCR_MODEL)
    if not key:
        return [], "photo reading by AI isn't configured on this server"
    img = img.copy()
    img.thumbnail((1600, 1600))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    b64 = base64.b64encode(buf.getvalue()).decode()
    body = {"model": model, "max_tokens": 800, "temperature": 0, "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": VISION_PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}]}
    try:
        r = httpx.post(url, json=body, headers={"Authorization": f"Bearer {key}"}, timeout=VISION_TIMEOUT)
        payload = r.json()
        if "choices" not in payload and isinstance(payload.get("data"), dict):
            payload = payload["data"]                    # Cline gateway wraps the OpenAI shape in {"data": ...}
        content = payload["choices"][0]["message"]["content"] or ""
        m = re.search(r"\{.*\}", content, re.S)
        meds = json.loads(m.group(0)).get("medicines", []) if m else []
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
        return [], "the AI reader couldn't read this photo right now"
    out = []
    for x in meds[:25]:
        if not isinstance(x, dict) or not isinstance(x.get("name"), str):
            continue
        q = x.get("quantity")
        out.append({"name": x["name"].strip()[:120],
                    "quantity": int(q) if isinstance(q, (int, float)) and 0 < q <= 1000 else None})
    return out, None


def _same_strength(written: str, product_name: str) -> bool:
    """Every number written next to the name (650, 40, 625) must be in the matched product's name. OCR misreads
    ("Pan 46") must never become a different strength ("PAN 20"); they stay unmatched for the user to pick."""
    have = set(re.findall(r"\d+(?:\.\d+)?", product_name))
    return all(n in have for n in re.findall(r"\d+(?:\.\d+)?", written))


def read_bill(bot, data: bytes, vision: bool = False) -> dict:
    """Photo bytes -> {lines: [{name, quantity, quantity_given, product_id, matched_name, composition, confident}],
    engine, note}. Raises ReadError only for a bad upload."""
    img = _load(data)
    cat = bot.catalog
    note = None
    if vision:
        raw, note = _vision(img)
        engine = "vision"
    else:
        raw = _lines_from_text(_tesseract_text(img), cat)
        engine = "tesseract"
        if not raw:
            note = "couldn't find a medicine name in this photo. If it's handwritten, try the AI reader."
    lines, seen = [], set()
    for x in raw:
        ms = [m for m in find_mentions(x["name"], cat) if m.kind == "product"]
        p = cat.products.get(ms[0].ref) if ms else None
        if p and not _same_strength(x["name"], p.name):
            p, ms = None, []
        if p and p.product_id in seen:
            continue
        if p:
            seen.add(p.product_id)
        lines.append({"name": p.name if p else x["name"], "written": x["name"],
                      "quantity": x["quantity"] or 10, "quantity_given": x["quantity"] is not None,
                      "product_id": p.product_id if p else None, "composition": p.composition if p else None,
                      "requires_prescription": p.requires_prescription if p else None,
                      "confident": bool(ms and ms[0].confident)})
    return {"lines": lines[:25], "engine": engine, "note": note, "stored": False}
