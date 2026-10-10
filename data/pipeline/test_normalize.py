import pytest

from normalize import (
    composition_key,
    parse_composition,
    parse_form,
    parse_pack,
    parse_release,
    parse_strength,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("500mg", "500mg"),
        ("0.5mg", "0.5mg"),
        ("1.2gm", "1200mg"),
        ("500mcg", "0.5mg"),
        ("200mg/5ml", "40mg/ml"),
        ("40mg/ml", "40mg/ml"),
        ("1gm/10ml", "100mg/ml"),
        ("2% w/w", "2pct_ww"),
        ("0.1% w/v", "0.1pct_wv"),
        ("40IU", "40iu"),
        ("1000IU/5ml", "200iu/ml"),
        ("60 Million spores", "60million_spores"),
        ("5 Billion CFU", "5billion_cfu"),
    ],
)
def test_strength(raw, expected):
    assert parse_strength(raw).key() == expected


@pytest.mark.parametrize("raw", ["NA", "", None, "q.s.", "Pyridoxine"])
def test_strength_unknown(raw):
    assert parse_strength(raw) is None


def test_composition_order_and_spelling_do_not_matter():
    a = parse_composition("Amoxycillin  (500mg)+  Clavulanic Acid (125mg)")
    b = parse_composition("Clavulanic Acid (125 mg) + Amoxicillin (500mg)")
    assert composition_key(a, "tablet", "IR") == composition_key(b, "tablet", "IR")


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Paracetamol (650mg)", "paracetamol:650mg"),
        ("DOMPERIDONE 30MG+RABEPRAZOLE SODIUM 20MG", "domperidone:30mg|rabeprazole sodium:20mg"),
        ("LEVOCETIRIZINE-5MG", "levocetirizine:5mg"),
        ("DEXTROSE+ POTASSIUM CHLORIDE+ SODIUM CHLORIDE+ SODIUM CITRATE-2.7+ 0.3+ 0.52+ 0.58GM+ GM+ GM+ GM",
         "dextrose:2700mg|potassium chloride:300mg|sodium chloride:520mg|sodium citrate:580mg"),
        ("ALUMINIUM HYDROXIDE+ MAGNESIUM HYDROXIDE+ SIMETHICONE-830+ 185+ 50MG/10ML+ MG/10ML+ MG/10ML",
         "aluminium hydroxide:83mg/ml|magnesium hydroxide:18.5mg/ml|simethicone:5mg/ml"),
        ("Generic Name  Paracetamol 650 mg  Also Known As: Acetaminophen", "paracetamol:650mg"),
        ('["amoxycillin (500mg) ", " clavulanic acid (125mg)"]', "amoxicillin:500mg|clavulanic acid:125mg"),
        ("Paracetamol(Acetaminophen) (500mg)", "paracetamol:500mg"),
        ("Vitamin B6 (Pyridoxine) (10mg)", "vitamin b6:10mg"),
    ],
)
def test_standard_composition(raw, expected):
    from normalize import to_standard_composition
    comps = parse_composition(to_standard_composition(raw))
    assert "|".join(c.key() for c in comps) == expected


@pytest.mark.parametrize("raw", ["AYURVEDIC", None, "", "Vitamins and minerals", "A+ B-5MG"])
def test_standard_composition_refuses_ambiguous(raw):
    from normalize import to_standard_composition
    assert to_standard_composition(raw) is None


def test_alias_in_ingredient_name():
    a = parse_composition("Paracetamol/Acetaminophen  (500mg) + Tramadol (50mg)")
    b = parse_composition("Tramadol (50mg)+ Paracetamol (500mg)")
    assert composition_key(a, "tablet", "IR") == composition_key(b, "tablet", "IR")
    assert [c.ingredient for c in parse_composition("Insulin Isophane/NPH (70%)")] == ["insulin isophane"]


def test_unit_equivalence():
    a = parse_composition("Cyanocobalamin (500mcg)")
    b = parse_composition("Cyanocobalamin (0.5mg)")
    assert composition_key(a, "tablet", "IR") == composition_key(b, "tablet", "IR")


def test_different_strength_is_different():
    a = parse_composition("Amoxycillin (500mg) + Clavulanic Acid (125mg)")
    b = parse_composition("Amoxycillin (875mg) + Clavulanic Acid (125mg)")
    assert composition_key(a, "tablet", "IR") != composition_key(b, "tablet", "IR")


def test_extra_ingredient_is_different():
    two = parse_composition("Cetirizine (5mg) + Paracetamol (325mg)")
    three = parse_composition("Cetirizine (5mg) + Paracetamol (325mg) + Phenylephrine (10mg)")
    assert composition_key(two, "tablet", "IR") != composition_key(three, "tablet", "IR")


def test_unstated_strength_never_matches():
    assert composition_key(parse_composition("Cetirizine (NA) + Paracetamol (NA)"), "syrup", "IR") is None
    assert composition_key(parse_composition("Levosalbutamol + Ambroxol (30mg)"), "syrup", "IR") is None


@pytest.mark.parametrize(
    "name,label,form",
    [
        ("Augmentin 625 Duo Tablet", "strip of 10 tablets", "tablet"),
        ("Augmentin Duo Oral Suspension", "bottle of 30 ml Oral Suspension", "suspension"),
        ("Augmentin 1.2gm Injection", "vial of 1 Powder for Injection", "injection"),
        ("Calpol 250 Tablet DT", "strip of 10 tablet dt", "tablet_dispersible"),
        ("Clindafin N Gel", "tube of 20 gm Gel", "gel"),
        ("Sinarest Paediatric Drops", "packet of 15 ml Oral Drops", "oral_drops"),
        ("Moxikind-CV Dry Syrup", None, "dry_syrup"),
        ("Gelusil MPS Tablet", None, "tablet"),
        ("Becosules Capsule", "strip of 20 capsules", "capsule"),
        ("Asthalin Inhaler", None, "inhaler"),
    ],
)
def test_form(name, label, form):
    assert parse_form(name, label) == form


@pytest.mark.parametrize(
    "name,label,release",
    [
        ("Glycomet 500 Tablet SR", "strip of 10 tablet sr", "SR"),
        ("Metolar XR 50 Tablet", None, "ER"),
        ("Zerodol MR Tablet", "strip of 10 tablets", "IR"),     # MR = muscle-relaxant brand suffix
        ("Pantocid Tablet MR", None, "MR"),                     # after the form word = modified release
        ("Dr. Ortho Oil", None, "IR"),
        ("Augmentin 625 Duo Tablet", "strip of 10 tablets", "IR"),
        ("Pan 40 Tablet", None, "IR"),
    ],
)
def test_release(name, label, release):
    assert parse_release(name, label) == release


@pytest.mark.parametrize(
    "label,qty,unit",
    [
        ("strip of 10 tablets", 10, "unit"),
        ("strip of 15 tablets", 15, "unit"),
        ("bottle of 100 ml Syrup", 100, "ml"),
        ("tube of 20 gm Gel", 20, "g"),
        ("vial of 1 Injection", 1, "unit"),
        ("strip of 10 capsule sr", 10, "unit"),
    ],
)
def test_pack(label, qty, unit):
    p = parse_pack(label)
    assert (p.quantity, p.unit) == (qty, unit)
