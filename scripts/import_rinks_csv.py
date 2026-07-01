"""Merge a CSV of real rink data into rinks.json.

CSV columns: name, address, city, state, lat, lng, type, isPublic, phone,
website, amenities (semicolon-separated), hours_mon..hours_sun.
Engagement fields (rating, reviewCount, checkins) are randomized placeholders;
events/reviews start empty. ids continue from the current max in rinks.json.

Usage: python scripts/import_rinks_csv.py path/to/batch.csv
"""
import csv
import json
import pathlib
import random
import sys

RINKS_FILE = pathlib.Path(__file__).resolve().parent.parent / "rinks.json"
HOURS_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
HOURS_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DEFAULT_HOURS = "Call for hours"

# Map freeform type strings to the app's four canonical values
TYPE_MAP = {
    "NHL": "NHL",
    "OLYMPIC": "OLYMPIC",
    "SYNTHETIC": "SYNTHETIC",
    "STANDARD": "STANDARD",
    "INDOOR": "STANDARD",  # generic "Indoor" → STANDARD
}


def row_to_rink(row, next_id):
    hours = {}
    for key, label in zip(HOURS_DAYS, HOURS_LABELS):
        value = row.get(f"hours_{key}", "").strip()
        hours[label] = value if value else DEFAULT_HOURS

    raw_amenities = row.get("amenities", "")
    sep = ";" if ";" in raw_amenities else ","
    amenities = [a.strip() for a in raw_amenities.split(sep) if a.strip()]

    return {
        "id": next_id,
        "name": row["name"].strip(),
        "address": row["address"].strip(),
        "city": row["city"].strip(),
        "state": row["state"].strip(),
        "lat": float(row["lat"]),
        "lng": float(row["lng"]),
        "type": TYPE_MAP.get(row["type"].strip().upper(), "STANDARD"),
        "isPublic": row["isPublic"].strip().lower() in ("true", "yes", "1"),
        "rating": round(random.uniform(3.8, 4.9), 1),
        "reviewCount": random.randint(50, 900),
        "phone": row.get("phone", "").strip() or None,
        "website": (row.get("website", "").strip().removeprefix("https://").removeprefix("http://")) or None,
        "checkins": random.randint(200, 3000),
        "hours": hours,
        "amenities": amenities,
        "events": [],
        "reviews": [],
    }


def main(csv_path):
    rinks = json.loads(RINKS_FILE.read_text(encoding="utf-8"))
    next_id = max((r["id"] for r in rinks), default=0) + 1

    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if not row.get("name", "").strip():
                continue
            rinks.append(row_to_rink(row, next_id))
            next_id += 1

    RINKS_FILE.write_text(json.dumps(rinks, indent=2), encoding="utf-8")
    print(f"Imported into {RINKS_FILE}, total rinks: {len(rinks)}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python scripts/import_rinks_csv.py <csv_path>")
    main(sys.argv[1])
