"""Database acceptance tests (Phase 4). Run after `make db`."""
import sys
import time
from pathlib import Path

import pandas as pd
import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "db"))
from load import database_url  # noqa: E402


@pytest.fixture(scope="module")
def cur():
    try:
        conn = psycopg.connect(database_url(), connect_timeout=3)
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"database not reachable: {e}")
    with conn, conn.cursor() as c:
        c.execute("SET search_path = medibot, public")
        yield c


def one(cur, sql, *args):
    cur.execute(sql, args)
    return cur.fetchone()[0]


def test_counts_match_processed_files(cur):
    P = ROOT / "data/processed"
    for table, file in [("products", "products"), ("product_safety", "product_safety"),
                        ("compositions", "compositions"), ("jan_aushadhi", "jan_aushadhi")]:
        assert one(cur, f"SELECT count(*) FROM {table}") == len(pd.read_parquet(P / f"{file}.parquet", columns=[]))


def test_every_product_has_a_safety_label(cur):
    assert one(cur, "SELECT count(*) FROM products p LEFT JOIN product_safety s USING (product_id) "
                    "WHERE s.product_id IS NULL") == 0


def test_every_composition_has_ingredients(cur):
    assert one(cur, "SELECT count(*) FROM compositions c WHERE NOT EXISTS "
                    "(SELECT 1 FROM composition_ingredients ci WHERE ci.composition_id = c.composition_id)") == 0


def test_no_otc_product_with_controlled_ingredient(cur):
    assert one(cur, """SELECT count(*) FROM products p JOIN product_safety s USING (product_id)
                       JOIN ingredients i ON i.name = ANY (p.ingredients)
                       WHERE s.category = 'otc' AND i.schedule IN ('X','NDPS','H1')""") == 0


def test_substitutes_query_is_fast_and_correct(cur):
    sql = """WITH t AS (SELECT composition_id FROM products WHERE key = %s)
             SELECT p.name, lp.price_per_unit_inr FROM products p JOIN t USING (composition_id)
             JOIN latest_prices lp ON lp.product_id = p.product_id
             WHERE p.substitutable ORDER BY lp.price_per_unit_inr LIMIT 5"""
    one(cur, "SELECT 1")  # warm connection
    t0 = time.perf_counter()
    cur.execute(sql, ("augmentin 625 duo tablet",))
    rows = cur.fetchall()
    assert (time.perf_counter() - t0) < 0.05
    assert len(rows) == 5 and all(r[1] < 22.34 for r in rows)  # all cheaper than Augmentin's Rs 22.34/tablet


def test_jan_aushadhi_generic_for_augmentin(cur):
    assert one(cur, """SELECT price_per_unit_inr FROM jan_aushadhi WHERE usable AND composition_id =
                       (SELECT composition_id FROM products WHERE key = 'augmentin 625 duo tablet')""") == pytest.approx(9.64, abs=0.01)


def test_known_major_interaction(cur):
    sev = one(cur, """SELECT max(severity) FROM interactions x
                      JOIN ingredients a ON a.ingredient_id = x.ingredient_a JOIN ingredients b ON b.ingredient_id = x.ingredient_b
                      WHERE (a.base, b.base) IN (('aspirin','warfarin'), ('warfarin','aspirin'))""")
    assert sev == "Major"


def test_safety_advice_present(cur):
    adv = one(cur, """SELECT i.safety_advice FROM product_info i JOIN products p USING (product_id)
                      WHERE p.key = 'dolo 650 tablet' AND i.source = 'mid'""")
    assert adv and "pregnancy" in adv and "alcohol" in adv


def test_nearest_kendra_query(cur):
    t0 = time.perf_counter()
    cur.execute("""SELECT kendra_code FROM kendras WHERE lat IS NOT NULL ORDER BY
                   (lat - 26.1878)^2 + ((lon - 91.6916) * cos(radians(26.19)))^2 LIMIT 3""")
    assert len(cur.fetchall()) == 3 and (time.perf_counter() - t0) < 0.1


def test_kendras_have_no_personal_data(cur):
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='medibot' AND table_name='kendras'")
    cols = {r[0] for r in cur.fetchall()}
    assert not cols & {"contact_person", "contact_number", "phone"}
