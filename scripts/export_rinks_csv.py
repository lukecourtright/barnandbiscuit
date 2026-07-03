"""Export rinks.json to a single CSV for manual spot-checking / editing.

One row per rink, sorted by state/city/name for easy scanning (e.g. to spot
rinks that are missing entirely), covering the fields worth hand-verifying
(name, address, city, state, lat/lng, type, isPublic, phone, website,
amenities, hours). Engagement fields (rating, reviewCount, checkins) and
events/reviews are left out entirely — they're randomized placeholders, not
real data, and editing them here would have no effect since
merge_rinks_csv.py ignores them.

Edit the output CSV by hand (Excel/Sheets/etc.): fix any row's fields to
correct existing data, or add new rows with a blank `id` for rinks that are
missing. Then run merge_rinks_csv.py on the edited file to apply it back
into rinks.json.

Usage: python scripts/export_rinks_csv.py [output_path]
"""
import csv
import json
import pathlib
import sys

RINKS_FILE = pathlib.Path(__file__).resolve().parent.parent / "rinks.json"
HOURS_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
HOURS_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

FIELDNAMES = (
    ["id", "name", "address", "city", "state", "lat", "lng", "type", "isPublic", "phone", "website", "amenities"]
    + [f"hours_{d}" for d in HOURS_DAYS]
)


def rink_to_row(r):
    row = {
        "id": r["id"],
        "name": r["name"],
        "address": r["address"],
        "city": r["city"],
        "state": r["state"],
        "lat": r["lat"],
        "lng": r["lng"],
        "type": r["type"],
        "isPublic": r["isPublic"],
        "phone": r.get("phone") or "",
        "website": r.get("website") or "",
        "amenities": "; ".join(r.get("amenities", [])),
    }
    hours = r.get("hours", {})
    for key, label in zip(HOURS_DAYS, HOURS_LABELS):
        row[f"hours_{key}"] = hours.get(label, "")
    return row


def main(out_path):
    rinks = json.loads(RINKS_FILE.read_text(encoding="utf-8"))
    rinks.sort(key=lambda r: (r["state"], r["city"], r["name"]))
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for r in rinks:
            writer.writerow(rink_to_row(r))
    print(f"Exported {len(rinks)} rinks to {out_path}")


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "rinks_full_export.csv"
    main(out)
