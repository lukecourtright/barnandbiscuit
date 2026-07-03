"""Merge a hand-edited CSV from export_rinks_csv.py back into rinks.json.

Rows with an `id` matching an existing rink update that rink's
name/address/city/state/lat/lng/type/isPublic/phone/website/amenities/hours
in place (only fields that actually changed are reported). Rows with a
blank `id` are treated as new rinks and appended with sequential ids,
same as import_rinks_csv.py. Rows whose `id` doesn't match anything are
skipped with a warning. This script never deletes — to remove a rink,
edit rinks.json directly. rating/reviewCount/checkins/events/reviews are
never touched for existing rinks; new rinks get the same randomized
placeholders as import_rinks_csv.py.

Usage: python scripts/merge_rinks_csv.py path/to/edited.csv
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

TYPE_MAP = {
    "NHL": "NHL",
    "OLYMPIC": "OLYMPIC",
    "SYNTHETIC": "SYNTHETIC",
    "STANDARD": "STANDARD",
    "INDOOR": "STANDARD",
}


def parsed_fields(row):
    hours = {}
    for key, label in zip(HOURS_DAYS, HOURS_LABELS):
        value = row.get(f"hours_{key}", "").strip()
        hours[label] = value if value else DEFAULT_HOURS

    raw_amenities = row.get("amenities", "")
    sep = ";" if ";" in raw_amenities else ","
    amenities = [a.strip() for a in raw_amenities.split(sep) if a.strip()]

    return {
        "name": row["name"].strip(),
        "address": row["address"].strip(),
        "city": row["city"].strip(),
        "state": row["state"].strip(),
        "lat": float(row["lat"]),
        "lng": float(row["lng"]),
        "type": TYPE_MAP.get(row["type"].strip().upper(), "STANDARD"),
        "isPublic": row["isPublic"].strip().lower() in ("true", "yes", "1"),
        "phone": row.get("phone", "").strip() or None,
        "website": (row.get("website", "").strip().removeprefix("https://").removeprefix("http://")) or None,
        "amenities": amenities,
        "hours": hours,
    }


def new_rink(next_id, fields):
    return {
        "id": next_id,
        **fields,
        "rating": round(random.uniform(3.8, 4.9), 1),
        "reviewCount": random.randint(50, 900),
        "checkins": random.randint(200, 3000),
        "events": [],
        "reviews": [],
    }


def main(csv_path):
    rinks = json.loads(RINKS_FILE.read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in rinks}
    next_id = max(by_id, default=0) + 1

    updated, unchanged, added, missing = 0, 0, 0, []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if not row.get("name", "").strip():
                continue
            fields = parsed_fields(row)
            rid_raw = row.get("id", "").strip()

            if not rid_raw:
                rinks.append(new_rink(next_id, fields))
                print(f"  added id {next_id}: {fields['name']} ({fields['city']}, {fields['state']})")
                next_id += 1
                added += 1
                continue

            rid = int(rid_raw)
            rink = by_id.get(rid)
            if rink is None:
                missing.append(rid)
                continue

            changes = [k for k, v in fields.items() if rink.get(k) != v]
            if changes:
                rink.update(fields)
                updated += 1
                print(f"  id {rid} ({rink['name']}): updated {', '.join(changes)}")
            else:
                unchanged += 1

    RINKS_FILE.write_text(json.dumps(rinks, indent=2), encoding="utf-8")
    print(f"\n{added} added, {updated} updated, {unchanged} unchanged, {len(missing)} ids not found: {missing}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python scripts/merge_rinks_csv.py <csv_path>")
    main(sys.argv[1])
