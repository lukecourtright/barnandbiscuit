"""Amazon PA-API pipeline for live Equipment offers. Two phases mirror the
existing rinks Google Places workflow (scripts/fetch_google_places_data.py):

  1. search   - search PA-API for a category's keywords, write ASIN
                candidates to a review CSV. No equipment.json/DB writes yet.
  2. apply    - after hand-editing that CSV (blank out bad matches), pull
                full item details per remaining ASIN and either update the
                matching EquipmentOffer (if this ASIN was matched before) or
                create a new curated Equipment row (appended to
                equipment.json, same as a hand-added product) plus its first
                EquipmentOffer/EquipmentPriceSnapshot.

A third phase re-checks products already matched, with no review step:

  3. refresh  - re-fetch current price/stock for every existing Amazon
                EquipmentOffer and log a new EquipmentPriceSnapshot, so
                priceHistory/deal/wasPrice on the site stay live. Meant to
                run on a daily schedule (see CLAUDE.md) — separate from the
                equipment.json startup sync, which never touches offers.

Requires AMAZON_PA_API_ACCESS_KEY, AMAZON_PA_API_SECRET_KEY,
AMAZON_PA_API_PARTNER_TAG in the environment, and an approved Amazon
Associates + Product Advertising API account (see CLAUDE.md).

Uses the python-amazon-paapi package (see requirements.txt). Its response
object attribute paths below (item_info.by_line_info.brand.display_value,
offers.listings[0].price.amount, etc.) are written from that package's
documented response shape — this hasn't been exercised against a live
response yet since PA-API access requires approval first. Verify these
paths against a real search/apply run once credentials are in hand, and
adjust if the library's actual attribute names differ.

Usage:
  python scripts/fetch_amazon_products.py search --category Sticks [--limit N] [--out FILE]
  python scripts/fetch_amazon_products.py apply <csv_path> [--limit N]
  python scripts/fetch_amazon_products.py refresh [--limit N]
"""
import argparse
import csv
import json
import os
import pathlib
import sys
import time
from datetime import datetime, timezone

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
EQUIPMENT_FILE = REPO_ROOT / "equipment.json"
SEARCH_FIELDNAMES = ["asin", "category", "brand", "title", "price", "url"]

CATEGORY_KEYWORDS = {
    "Skates": "ice hockey skates",
    "Sticks": "ice hockey stick",
    "Helmets": "ice hockey helmet",
    "Gloves": "ice hockey gloves",
    "Shoulder pads": "ice hockey shoulder pads",
    "Elbow pads": "ice hockey elbow pads",
    "Shin guards": "ice hockey shin guards",
    "Pants": "ice hockey pants",
    "Bags": "ice hockey equipment bag",
    "Goalie gear": "ice hockey goalie equipment",
}


def get_client():
    access_key = os.environ.get("AMAZON_PA_API_ACCESS_KEY")
    secret_key = os.environ.get("AMAZON_PA_API_SECRET_KEY")
    partner_tag = os.environ.get("AMAZON_PA_API_PARTNER_TAG")
    if not (access_key and secret_key and partner_tag):
        sys.exit("AMAZON_PA_API_ACCESS_KEY, AMAZON_PA_API_SECRET_KEY, and AMAZON_PA_API_PARTNER_TAG must be set")
    from amazon_paapi import AmazonApi
    return AmazonApi(access_key, secret_key, partner_tag, "US")


def get_app_main():
    # main.py isn't a package; add the repo root to sys.path so the script
    # can import its engine/models regardless of the caller's cwd.
    sys.path.insert(0, str(REPO_ROOT))
    import main as app_main
    return app_main


def extract_brand(item):
    bl = item.item_info.by_line_info if item.item_info else None
    return bl.brand.display_value if bl and bl.brand else ""


def extract_title(item):
    return item.item_info.title.display_value if item.item_info and item.item_info.title else ""


def extract_image(item):
    img = item.images.primary.large if item.images and item.images.primary else None
    return img.url if img else None


def extract_listing(item):
    return item.offers.listings[0] if item.offers and item.offers.listings else None


def fetch_items(api, asins):
    """Returns {asin: item} for up to 10 ASINs via PA-API GetItems."""
    result = api.get_items(asins)
    items = result.items_result.items if result.items_result else []
    return {item.asin: item for item in items}


def cmd_search(args):
    if args.category not in CATEGORY_KEYWORDS:
        sys.exit(f"Unknown category {args.category!r} — must be one of {sorted(CATEGORY_KEYWORDS)}")
    api = get_client()
    result = api.search_items(
        keywords=CATEGORY_KEYWORDS[args.category],
        search_index="SportingGoods",
        item_count=min(args.limit or 10, 10),
    )
    items = result.search_result.items if result.search_result else []

    rows = []
    for item in items:
        listing = extract_listing(item)
        rows.append({
            "asin": item.asin,
            "category": args.category,
            "brand": extract_brand(item),
            "title": extract_title(item),
            "price": listing.price.amount if listing else "",
            "url": item.detail_page_url,
        })

    out = pathlib.Path(args.out or f"amazon_{args.category.lower().replace(' ', '_')}_review.csv")
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SEARCH_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} candidates to {out} — review by hand (blank out asin for bad matches), then run apply.")


def cmd_apply(args):
    app_main = get_app_main()
    from sqlmodel import Session, select

    api = get_client()
    products = json.loads(EQUIPMENT_FILE.read_text(encoding="utf-8"))

    with open(args.csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if args.limit:
        rows = rows[: args.limit]

    applied, skipped, errors = 0, 0, 0
    with Session(app_main.engine) as session:
        for row in rows:
            asin = row.get("asin", "").strip()
            if not asin:
                skipped += 1
                continue
            try:
                item = fetch_items(api, [asin]).get(asin)
            except Exception as e:
                print(f"  error fetching {asin}: {e}")
                errors += 1
                continue
            if item is None:
                print(f"  {asin}: not found")
                errors += 1
                continue

            listing = extract_listing(item)
            if listing is None:
                print(f"  {asin}: no current offer/price, skipping")
                errors += 1
                continue
            price = float(listing.price.amount)
            in_stock = bool(listing.availability and listing.availability.type == "Now")

            existing_offer = session.exec(
                select(app_main.EquipmentOffer).where(
                    app_main.EquipmentOffer.network == "amazon-pa-api",
                    app_main.EquipmentOffer.sourceProductId == asin,
                )
            ).first()

            if existing_offer is None:
                equipment_id = max((p["id"] for p in products), default=100) + 1
                product = {
                    "id": equipment_id,
                    "category": row["category"],
                    "brand": extract_brand(item) or row.get("brand", ""),
                    "name": extract_title(item) or row.get("title", ""),
                    "rating": 0,
                    "reviewCount": 0,
                    "imageUrl": extract_image(item),
                    "deal": None,
                    "note": "Stable price",
                    "priceIsGood": False,
                    "wasPrice": None,
                    "priceHistory": [],
                    "featuredQuote": "",
                    "retailers": [],
                    "specs": [],
                    "reviewList": [],
                }
                products.append(product)
                session.merge(app_main.Equipment(**product))
                offer = app_main.EquipmentOffer(
                    equipmentId=equipment_id,
                    retailerName="Amazon",
                    network="amazon-pa-api",
                    sourceProductId=asin,
                    price=price,
                    url=item.detail_page_url,
                    inStock=in_stock,
                )
            else:
                equipment_id = existing_offer.equipmentId
                existing_offer.price = price
                existing_offer.url = item.detail_page_url
                existing_offer.inStock = in_stock
                existing_offer.lastCheckedAt = datetime.now(timezone.utc).isoformat()
                offer = existing_offer

            session.add(offer)
            session.commit()
            session.refresh(offer)
            session.add(app_main.EquipmentPriceSnapshot(equipmentOfferId=offer.id, price=price))
            session.commit()

            print(f"  {asin}: {'added new' if existing_offer is None else 'updated'} equipment id {equipment_id} @ ${price}")
            applied += 1
            time.sleep(1)  # PA-API default rate limit is ~1 req/sec

    EQUIPMENT_FILE.write_text(json.dumps(products, indent=2), encoding="utf-8")
    print(
        f"\n{applied} applied, {skipped} skipped (no ASIN), {errors} errors. "
        f"equipment.json updated for curated fields — push to main to sync on next deploy; "
        f"live offer/price data is already committed to this DB."
    )


def cmd_refresh(args):
    app_main = get_app_main()
    from sqlmodel import Session, select

    api = get_client()
    with Session(app_main.engine) as session:
        offers = session.exec(
            select(app_main.EquipmentOffer).where(app_main.EquipmentOffer.network == "amazon-pa-api")
        ).all()
        if args.limit:
            offers = offers[: args.limit]

        updated, errors = 0, 0
        for i in range(0, len(offers), 10):
            batch = offers[i : i + 10]
            try:
                items_by_asin = fetch_items(api, [o.sourceProductId for o in batch])
            except Exception as e:
                print(f"  error fetching batch starting at {i}: {e}")
                errors += len(batch)
                continue
            for offer in batch:
                item = items_by_asin.get(offer.sourceProductId)
                listing = extract_listing(item) if item else None
                if listing is None:
                    print(f"  {offer.sourceProductId}: no current offer, leaving stale")
                    errors += 1
                    continue
                offer.price = float(listing.price.amount)
                offer.inStock = bool(listing.availability and listing.availability.type == "Now")
                offer.lastCheckedAt = datetime.now(timezone.utc).isoformat()
                session.add(offer)
                session.commit()
                session.add(app_main.EquipmentPriceSnapshot(equipmentOfferId=offer.id, price=offer.price))
                session.commit()
                updated += 1
            time.sleep(1)

    print(f"Refreshed {updated} offers, {errors} errors")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_search = sub.add_parser("search", help="Search PA-API for a category, write a review CSV")
    p_search.add_argument("--category", required=True, choices=sorted(CATEGORY_KEYWORDS))
    p_search.add_argument("--limit", type=int, default=10)
    p_search.add_argument("--out", default=None)
    p_search.set_defaults(func=cmd_search)

    p_apply = sub.add_parser("apply", help="Pull item details for each reviewed ASIN, write equipment.json + EquipmentOffer rows")
    p_apply.add_argument("csv_path")
    p_apply.add_argument("--limit", type=int, default=None)
    p_apply.set_defaults(func=cmd_apply)

    p_refresh = sub.add_parser("refresh", help="Re-check price/stock for every existing Amazon EquipmentOffer, log a new price snapshot")
    p_refresh.add_argument("--limit", type=int, default=None)
    p_refresh.set_defaults(func=cmd_refresh)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
