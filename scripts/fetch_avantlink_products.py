"""AvantLink pipeline for live Equipment offers — the pilot network, chosen
over Amazon PA-API because AvantLink's product APIs have no post-approval
sales-volume gate (Amazon requires 10 sales in 30 days before granting
PA-API access; scripts/fetch_amazon_products.py stays scaffolded for once
that's cleared). Pure Hockey — already referenced in equipment.json's mock
data — runs its affiliate program on AvantLink, so this also restores a
retailer name that's already in the catalog.

Two phases mirror the existing Google Places / Amazon match-review pattern:

  1. search   - query AvantLink's ProductSearch API by category keyword
                (optionally scoped to one merchant, e.g. Pure Hockey's
                AvantLink merchant id), write candidates to a review CSV.
                No equipment.json/DB writes yet.
  2. apply    - after hand-editing that CSV (blank out bad matches), upsert
                a curated Equipment row (creating one if this SKU is new)
                and an EquipmentOffer row using the Buy_URL/price AvantLink
                returned — Buy_URL is already a live, ready-to-use tracking
                link, no manual affiliate-tag construction needed.

A third phase re-checks products already matched, no review step:

  3. refresh  - calls ProductPriceCheck (a direct merchant_id+sku lookup,
                not a keyword search) for every existing AvantLink
                EquipmentOffer and logs a new EquipmentPriceSnapshot, so
                priceHistory/deal/wasPrice stay live. No sales-volume
                prerequisite and a generous rate limit (3,600/hr,
                15,000/day) — safe to run daily from day one, unlike the
                Amazon pipeline.

Requires AVANTLINK_AFFILIATE_ID and AVANTLINK_WEBSITE_ID in the
environment, plus an approved AvantLink affiliate account and an approved
relationship with the target merchant (e.g. Pure Hockey) — see CLAUDE.md.

Unlike PA-API, these are plain unsigned GET requests (affiliate_id/
website_id as query params, no request signing). Field/param names below
(Product_SKU, Retail_Price, Buy_URL, ProductPriceCheck's own param names,
etc.) come from AvantLink's documented API shape — this hasn't been
exercised against a live account yet, so verify field names and that
output=json returns the expected shape the first time this actually runs,
and adjust if AvantLink's real response differs.

Usage:
  python scripts/fetch_avantlink_products.py search --category Sticks [--merchant-id ID] [--limit N] [--out FILE]
  python scripts/fetch_avantlink_products.py apply <csv_path> [--limit N]
  python scripts/fetch_avantlink_products.py refresh [--limit N]
"""
import argparse
import csv
import json
import os
import pathlib
import sys
import time
from datetime import datetime, timezone

import httpx

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
EQUIPMENT_FILE = REPO_ROOT / "equipment.json"
API_URL = "https://www.avantlink.com/api.php"
NETWORK = "avantlink"
SEARCH_FIELDNAMES = ["sku", "merchant_id", "merchant_name", "category", "brand", "title", "price", "url", "image"]

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

RESULT_FIELDS = "Merchant_Id|Merchant_Name|Product_SKU|Product_Name|Brand_Name|Retail_Price|Sale_Price|Buy_URL|Thumbnail_Image"


def get_credentials():
    affiliate_id = os.environ.get("AVANTLINK_AFFILIATE_ID")
    website_id = os.environ.get("AVANTLINK_WEBSITE_ID")
    if not (affiliate_id and website_id):
        sys.exit("AVANTLINK_AFFILIATE_ID and AVANTLINK_WEBSITE_ID must be set")
    return affiliate_id, website_id


def get_app_main():
    # main.py isn't a package; add the repo root to sys.path so the script
    # can import its engine/models regardless of the caller's cwd.
    sys.path.insert(0, str(REPO_ROOT))
    import main as app_main
    return app_main


def current_price(product):
    sale = product.get("Sale_Price")
    return float(sale) if sale else float(product.get("Retail_Price") or 0)


def search_products(client, affiliate_id, website_id, keywords, merchant_id=None, count=10):
    params = {
        "module": "ProductSearch",
        "affiliate_id": affiliate_id,
        "website_id": website_id,
        "search_term": keywords,
        "search_results_fields": RESULT_FIELDS,
        "search_results_count": count,
        "output": "json",
    }
    if merchant_id:
        params["merchant_id"] = merchant_id
    resp = client.get(API_URL, params=params)
    resp.raise_for_status()
    return resp.json()


def price_check(client, affiliate_id, website_id, merchant_id, sku):
    """Direct product lookup for refresh — avoids re-searching by keyword
    and hoping the same SKU still surfaces. Param names for ProductPriceCheck
    are inferred from ProductSearch's conventions; verify against a live
    account."""
    resp = client.get(API_URL, params={
        "module": "ProductPriceCheck",
        "affiliate_id": affiliate_id,
        "website_id": website_id,
        "merchant_id": merchant_id,
        "sku": sku,
        "output": "json",
    })
    resp.raise_for_status()
    result = resp.json()
    return result[0] if isinstance(result, list) and result else (result or None)


def cmd_search(args):
    if args.category not in CATEGORY_KEYWORDS:
        sys.exit(f"Unknown category {args.category!r} — must be one of {sorted(CATEGORY_KEYWORDS)}")
    affiliate_id, website_id = get_credentials()

    rows = []
    with httpx.Client(timeout=15) as client:
        results = search_products(
            client, affiliate_id, website_id, CATEGORY_KEYWORDS[args.category],
            merchant_id=args.merchant_id, count=args.limit or 10,
        )
        for product in results:
            rows.append({
                "sku": product.get("Product_SKU", ""),
                "merchant_id": product.get("Merchant_Id", ""),
                "merchant_name": product.get("Merchant_Name", ""),
                "category": args.category,
                "brand": product.get("Brand_Name", ""),
                "title": product.get("Product_Name", ""),
                "price": current_price(product),
                "url": product.get("Buy_URL", ""),
                "image": product.get("Thumbnail_Image", ""),
            })

    out = pathlib.Path(args.out or f"avantlink_{args.category.lower().replace(' ', '_')}_review.csv")
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SEARCH_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} candidates to {out} — review by hand (blank out sku for bad matches), then run apply.")


def cmd_apply(args):
    app_main = get_app_main()
    from sqlmodel import Session, select

    products = json.loads(EQUIPMENT_FILE.read_text(encoding="utf-8"))

    with open(args.csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if args.limit:
        rows = rows[: args.limit]

    applied, skipped, errors = 0, 0, 0
    with Session(app_main.engine) as session:
        for row in rows:
            sku = row.get("sku", "").strip()
            if not sku:
                skipped += 1
                continue

            price_raw = row.get("price", "").strip()
            url = row.get("url", "").strip()
            if not price_raw or not url:
                print(f"  {sku}: missing price/url in review CSV, skipping")
                errors += 1
                continue
            price = float(price_raw)

            existing_offer = session.exec(
                select(app_main.EquipmentOffer).where(
                    app_main.EquipmentOffer.network == NETWORK,
                    app_main.EquipmentOffer.sourceProductId == sku,
                )
            ).first()

            if existing_offer is None:
                equipment_id = max((p["id"] for p in products), default=100) + 1
                product = {
                    "id": equipment_id,
                    "category": row["category"],
                    "brand": row.get("brand", ""),
                    "name": row.get("title", ""),
                    "rating": 0,
                    "reviewCount": 0,
                    "imageUrl": row.get("image") or None,
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
                    retailerName=row.get("merchant_name") or "Pure Hockey",
                    network=NETWORK,
                    sourceProductId=sku,
                    sourceMerchantId=row.get("merchant_id") or None,
                    price=price,
                    url=url,
                    inStock=True,
                )
            else:
                equipment_id = existing_offer.equipmentId
                existing_offer.price = price
                existing_offer.url = url
                if row.get("merchant_id"):
                    existing_offer.sourceMerchantId = row["merchant_id"]
                existing_offer.lastCheckedAt = datetime.now(timezone.utc).isoformat()
                offer = existing_offer

            session.add(offer)
            session.commit()
            session.refresh(offer)
            session.add(app_main.EquipmentPriceSnapshot(equipmentOfferId=offer.id, price=price))
            session.commit()

            print(f"  {sku}: {'added new' if existing_offer is None else 'updated'} equipment id {equipment_id} @ ${price}")
            applied += 1

    EQUIPMENT_FILE.write_text(json.dumps(products, indent=2), encoding="utf-8")
    print(
        f"\n{applied} applied, {skipped} skipped (no SKU), {errors} errors. "
        f"equipment.json updated for curated fields — push to main to sync on next deploy; "
        f"live offer/price data is already committed to this DB."
    )


def cmd_refresh(args):
    app_main = get_app_main()
    from sqlmodel import Session, select

    affiliate_id, website_id = get_credentials()
    with Session(app_main.engine) as session, httpx.Client(timeout=15) as client:
        offers = session.exec(
            select(app_main.EquipmentOffer).where(app_main.EquipmentOffer.network == NETWORK)
        ).all()
        if args.limit:
            offers = offers[: args.limit]

        updated, errors = 0, 0
        for offer in offers:
            if not offer.sourceMerchantId:
                print(f"  {offer.sourceProductId}: no stored merchant id, skipping (re-run apply to backfill it)")
                errors += 1
                continue
            try:
                product = price_check(client, affiliate_id, website_id, offer.sourceMerchantId, offer.sourceProductId)
            except Exception as e:
                print(f"  error checking {offer.sourceProductId}: {e}")
                errors += 1
                continue
            if product is None:
                print(f"  {offer.sourceProductId}: no longer available, leaving stale")
                errors += 1
                continue

            offer.price = current_price(product)
            offer.url = product.get("Buy_URL", offer.url)
            offer.lastCheckedAt = datetime.now(timezone.utc).isoformat()
            session.add(offer)
            session.commit()
            session.add(app_main.EquipmentPriceSnapshot(equipmentOfferId=offer.id, price=offer.price))
            session.commit()
            updated += 1
            time.sleep(0.1)  # generous rate limit (3600/hr, 15000/day) — light throttle only

    print(f"Refreshed {updated} offers, {errors} errors")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_search = sub.add_parser("search", help="Search AvantLink ProductSearch for a category, write a review CSV")
    p_search.add_argument("--category", required=True, choices=sorted(CATEGORY_KEYWORDS))
    p_search.add_argument("--merchant-id", default=None, help="AvantLink merchant id, e.g. Pure Hockey's, to scope the search to one retailer")
    p_search.add_argument("--limit", type=int, default=10)
    p_search.add_argument("--out", default=None)
    p_search.set_defaults(func=cmd_search)

    p_apply = sub.add_parser("apply", help="Merge each reviewed SKU into equipment.json + EquipmentOffer rows")
    p_apply.add_argument("csv_path")
    p_apply.add_argument("--limit", type=int, default=None)
    p_apply.set_defaults(func=cmd_apply)

    p_refresh = sub.add_parser("refresh", help="Re-check price/stock for every existing AvantLink EquipmentOffer, log a new price snapshot")
    p_refresh.add_argument("--limit", type=int, default=None)
    p_refresh.set_defaults(func=cmd_refresh)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
