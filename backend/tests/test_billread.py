"""Phase 15.1 photo reader: dose arithmetic, the strength guard, bill / prescription line extraction, bad uploads.
The AI reader needs the network and is not tested here; it goes through the same matching and strength guard."""
import io
import os
import shutil

import pytest

os.environ["MEDIBOT_LLM"] = "off"

from medibot.billread import ReadError, _lines_from_text, _load, _rx_quantity, _same_strength, read_bill  # noqa: E402


@pytest.fixture(scope="module")
def bot():
    from medibot.api.deps import bot as get
    return get()


@pytest.mark.parametrize("line,qty", [
    ("Dolo 650 1-0-1 x 5 days", 10), ("Pan 40 1-0-0 x 10 days", 10), ("Becosules OD x 15 days", 15),
    ("Becosules 0D x 15 days", 15), ("Azee 500 BD for 3 days", 6), ("Pan 40", None), ("Dolo 650 1-0-1", None)])
def test_rx_quantity_is_doses_times_days(line, qty):
    assert _rx_quantity(line)[0] == qty


def test_strength_guard_rejects_a_misread_strength():
    assert _same_strength("Pan 40", "PAN 40 Tablet")
    assert not _same_strength("Pan 46", "PAN 20 Tablet")
    assert _same_strength("Becosules", "Becosules Capsule")


def test_bill_rows_and_prescription_lines(bot):
    text = """SHREE MEDICAL STORE GSTIN 07ABCDE1234F1Z5
Bill No: 4521 Date: 11/10/2026
DOLO 650 TAB 15's 2 32.28 64.56
TELMA 40 TAB 15's 2 189.00 378.00
Sub Total 442.56
1. Tab Pan 40 1-0-0 x 10 days
Thank you"""
    got = {x["name"]: x["quantity"] for x in _lines_from_text(text, bot.catalog)}
    assert got == {"DOLO 650 TAB": 30, "TELMA 40 TAB": 30, "Pan 40": 10}


def test_bad_uploads_are_refused():
    with pytest.raises(ReadError):
        _load(b"not an image")
    with pytest.raises(ReadError):
        _load(b"")


@pytest.mark.skipif(not shutil.which("tesseract"), reason="tesseract not installed")
def test_tesseract_reads_a_printed_bill(bot):
    from PIL import Image, ImageDraw, ImageFont
    font = ImageFont.truetype(next(p for p in ["/usr/share/fonts/liberation/LiberationMono-Regular.ttf",
                                               "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
                                               "/usr/share/fonts/TTF/DejaVuSansMono.ttf"] if os.path.exists(p)), 26)
    img = Image.new("RGB", (800, 160), "white")
    d = ImageDraw.Draw(img)
    for i, row in enumerate(["DOLO 650 TAB    15's  2   32.28   64.56", "PAN 40 TAB      15's  1  169.00  169.00"]):
        d.text((20, 30 + 50 * i), row, font=font, fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    r = read_bill(bot, buf.getvalue())
    assert r["engine"] == "tesseract" and r["stored"] is False
    got = {x["name"]: x["quantity"] for x in r["lines"]}
    assert got == {"Dolo 650 Tablet": 30, "PAN 40 Tablet": 15}
