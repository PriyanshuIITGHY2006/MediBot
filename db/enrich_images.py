"""Enrichment: product image URLs -> medibot.products.image_url (only where empty).

Source: Indian Medicine Master Dataset, out_india/medicine_images.csv (374k remote URLs on 1mg's CDN,
collected from three Kaggle scrapes). These are 1mg's product photos: the UI must attribute them
("Image: 1mg") and fall back to a placeholder; they are not ours to redistribute.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "db"))
sys.path.insert(0, str(ROOT / "data/pipeline"))
from load import database_url  # noqa: E402
from sources import key_of  # noqa: E402

IMAGES = ROOT / "data/raw/kaggle_indian-medicine-master-dataset/Indian-Medicine-Dataset (1)/out_india/medicine_images.csv"


def build() -> None:
    img = pd.read_csv(IMAGES, usecols=["label", "image_kind", "image_ref"])
    img = img[img["image_kind"].eq("remote_url") & img["image_ref"].str.startswith("https://", na=False)]
    img["key"] = img["label"].map(key_of)
    img = img.drop_duplicates("key")[["key", "image_ref"]]
    with psycopg.connect(database_url()) as conn, conn.cursor() as cur:
        cur.execute("CREATE TEMP TABLE img (key text PRIMARY KEY, url text)")
        with cur.copy("COPY img (key, url) FROM STDIN") as cp:
            for k, u in img.itertuples(index=False, name=None):
                cp.write_row((k, u))
        cur.execute("""UPDATE medibot.products p SET image_url = i.url FROM img i
                       WHERE p.key = i.key AND p.image_url IS NULL""")
        updated = cur.rowcount
        cur.execute("SELECT count(*) FILTER (WHERE image_url IS NOT NULL), count(*) FROM medibot.products")
        have, total = cur.fetchone()
        conn.commit()
    print(f"  images added: {updated:,}; products with an image: {have:,}/{total:,}")


if __name__ == "__main__":
    build()
