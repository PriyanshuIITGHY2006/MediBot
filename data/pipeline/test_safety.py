"""Prescription Guard data tests (Phase 3). These protect rubric A1 (the 60-point cap) and A2.

Invariants run over ALL 284k products; the case table pins decisions for named medicines.
"""
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
P = ROOT / "data/processed"
pytestmark = pytest.mark.skipif(not (P / "product_safety.parquet").exists(), reason="safety not built")

TOPICAL = {"cream", "ointment", "gel", "lotion", "dusting_powder", "shampoo", "soap", "spray", "patch",
           "mouthwash", "oral_gel", "solution", "powder", "emulsion"}


@pytest.fixture(scope="module")
def data():
    ps = pd.read_parquet(P / "product_safety.parquet")
    p = pd.read_parquet(P / "products.parquet", columns=["product_id", "key", "name", "form", "ingredients", "composition"])
    ing = pd.read_parquet(P / "ingredient_safety.parquet").set_index("ingredient")
    return p.merge(ps, on="product_id"), ing


# ---------------------------------------------------------------- invariants (A1)


def test_every_product_is_tagged(data):
    d, _ = data
    assert d["category"].notna().all()


def test_no_otc_product_contains_controlled_h1_or_x(data):
    d, ing = data
    otc = d[d.category == "otc"].explode("ingredients")
    sched = otc["ingredients"].map(ing["schedule"])
    bad = otc[sched.isin(["X", "NDPS", "H1"])]
    assert bad.empty, bad[["name", "ingredients"]].head(10).to_string()


def test_otc_schedule_h_only_via_topical_exemption(data):
    d, ing = data
    otc = d[d.category == "otc"].explode("ingredients")
    h = otc[otc["ingredients"].map(ing["schedule"]) == "H"]
    not_topical = h[~h["form"].isin(TOPICAL | {"eye_drops", "eye_ointment", "eye_gel", "ear_drops", "eye_ear_drops",
                                               "nasal_drops", "nasal_spray"})]
    assert not_topical.empty, not_topical[["name", "form", "ingredients"]].head(10).to_string()
    steroid = h[h["ingredients"].map(ing["is_corticosteroid"]).astype(bool)]
    assert steroid.empty, steroid[["name", "ingredients"]].head(10).to_string()


def test_no_otc_injection(data):
    d, _ = data
    assert not ((d.category == "otc") & (d.form == "injection")).any()


def test_no_otc_cough_cold_syrup(data):
    d, _ = data
    liquids = {"syrup", "dry_syrup", "suspension", "oral_drops"}
    cough = d[(d.category == "otc") & d.form.isin(liquids) & d.reasons.str.contains("cough", na=False)]
    assert cough.empty


def test_corticosteroids_never_otc(data):
    d, ing = data
    otc = d[d.category == "otc"].explode("ingredients")
    assert not otc["ingredients"].map(ing["is_corticosteroid"]).fillna(False).astype(bool).any()


def test_banned_only_from_in_force_notifications(data):
    d, _ = data
    banned = d[d.category == "banned"]
    assert banned["legal_refs"].str.len().gt(0).all()
    # notifications under court relief / examination must never be cited as the reason
    assert not banned["legal_refs"].str.contains(r"S\.O\. 713\(E\)|S\.O\. 815\(E\)", regex=True).any()


# ---------------------------------------------------------------- named cases


CASES = [
    # PS sandbox presets
    ("augmentin 625 duo tablet", "schedule_h"),
    ("dolo 650 tablet", "otc"),
    ("allegra 120mg tablet", "schedule_h"),       # policy: follow Schedule H (fexofenadine #197)
    ("alprax 0.5mg tablet", "controlled"),
    # legal-H "OTC-feeling" medicines (policy decision 1)
    ("combiflam tablet", "schedule_h"),
    ("pan 40 tablet", "schedule_h"),
    ("okacet tablet", "schedule_h"),
    # cough syrups (policy decision 2)
    ("benadryl syrup", "prescription"),
    # topicals (policy decision 3)
    ("candid cream", "otc"),
    ("candid-b cream", "schedule_h"),             # beclometasone: steroid stays restricted
    ("soframycin 1% skin cream", "otc"),          # topical antibiotic: legal exemption
    ("neosporin ointment", "otc"),
    ("betadine 10% solution", "otc"),             # ambiguous "solution" resolved to topical
    ("mintop 2% solution", "otc"),                # minoxidil topical (2022 OTC draft)
    ("refresh tears eye drop", "otc"),
    ("moxicip eye drop", "schedule_h1"),          # antibiotic eye drops never exempt
    # bans: qualifiers and court relief
    ("acenex sr plus 100mg/325mg/15mg tablet", "schedule_h"),  # real composition has serratiopeptidase too -> not the 2-drug ban
    ("gloar-sr tablet", "banned"),                          # Aceclofenac (SR) + Paracetamol, S.O. 4420(E)
    ("aldigesic p 100mg/325mg tablet", "prescription"),     # same molecules, IR: NOT banned
    ("esulide 100mg/500mg tablet dt", "banned"),            # Nimesulide + Paracetamol dispersible, S.O. 2394(E)
    ("ap 100mg/325mg tablet", "schedule_h"),                # same, ordinary tablet: NOT banned
    ("cheston cold tablet", "banned"),                      # 2024 ban, S.O. 3385(E)
    ("amaryl mp 2mg tablet sr", "schedule_h"),              # #215 status uncertain -> not called banned
    # chronic medicines: prescription
    ("thyronorm 50mcg tablet", "prescription"),
    ("glycomet 500 sr tablet", "prescription"),
    # OTC staples
    ("crocin advance tablet", "otc"),
    ("d cold total tablet", "otc"),
    ("dulcolax tablet", "otc"),
    ("duphalac oral solution", "otc"),
    ("evion 400mg capsule", "otc"),
]


@pytest.mark.parametrize("key,expected", CASES, ids=[c[0] for c in CASES])
def test_named_case(data, key, expected):
    d, _ = data
    rows = d[d.key == key]
    assert not rows.empty, f"{key} not in catalog"
    r = rows.iloc[0]
    assert r.category == expected, f"{r['name']}: {r.category} ({r.reasons} {r.legal_refs})"
