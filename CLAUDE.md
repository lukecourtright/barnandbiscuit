# CLAUDE.md

## Running the App

```bash
# Windows (opens browser automatically)
run.bat

# Direct
python -m uvicorn main:app --port 8000 --reload
```

App serves at `http://localhost:8000`. No build step needed.

## Setup

```bash
pip install -r requirements.txt
```

## Deployment

Live at `https://barnandbiscuit-production.up.railway.app`. GitHub repo: `github.com/lukecourtright/barnandbiscuit`. Deploys to Railway via `railway.toml`, auto-deploying on push to `main`. The Postgres addon is linked to the web service.

`DATABASE_URL` — Postgres connection string, auto-injected by the Railway Postgres addon. Not required locally: if unset, the app falls back to a local `dev.db` SQLite file (gitignored).

`SECRET_KEY` — signs the session cookie used for login, set as a Railway env var. Not required locally: falls back to an insecure dev default if unset.

## Brand Name

The brand name is TBD — "HockeyLifers" domain was taken, "Barn & Biscuit" is the current placeholder. To rename:
1. Change `this.BRAND = 'Barn & Biscuit'` near the top of `static/index.html`
2. Update `<title>` in the same file
3. That's it — all wordmark rendering derives from `this.BRAND`

---

## Architecture

### File Structure

```
barnbiscuit/
├── main.py                    # FastAPI app + SQLModel models
├── rinks.json                 # Curated rink data — source of truth, synced into the DB on startup
├── rinks_import_template.csv  # CSV template for bulk-adding rinks (fill in, run import script)
├── scripts/
│   ├── import_rinks_csv.py   # Merges a filled CSV batch (new rinks) into rinks.json
│   ├── export_rinks_csv.py   # Dumps all of rinks.json to one CSV for manual review/editing
│   └── merge_rinks_csv.py    # Applies a hand-edited export back into rinks.json (updates by id, appends blank-id rows)
├── dev.db                     # Local SQLite fallback when DATABASE_URL is unset (gitignored)
├── requirements.txt
├── railway.toml
├── run.bat
└── static/
    ├── index.html           # Entire frontend SPA
    ├── brand-tokens.css     # CSS custom properties (Neon Night palette)
    └── logo/                # Favicons + SVG marks
```

### Backend (`main.py`)

Data is stored in a database (Postgres in production via Railway addon, local SQLite fallback otherwise) accessed through SQLModel. `rinks.json` remains the human/AI-edited source of truth — on every startup, `sync_rinks_from_file()` creates tables if missing, upserts (by `id`) every rink from `rinks.json` into the `Rink` table, and deletes any `Rink` row whose `id` is no longer in the file, so pushing an updated `rinks.json` to `main` (additions, edits, *and* removals) is enough to update production data on the next deploy.

- `GET /` → serves `static/index.html`
- `GET /api/rinks` → queries the `Rink` table, returns all rows as JSON (same shape as before)
- `POST /api/rinks/submit` → inserts community-submitted rinks into the `PendingRink` table (`id`, `submittedAt`, raw `data` JSON blob) — not public until moderated, no validation yet
- `POST /api/auth/signup`, `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me` → email/password auth against the `User` table (`id`, `email`, `passwordHash` (bcrypt), `displayName`, `createdAt`). Login state is a signed, httponly session cookie (Starlette `SessionMiddleware`, see `SECRET_KEY` above) holding `user_id` — no tokens handled in JS.
- `/static` → static file mount for CSS, logos, etc.

### Frontend (`static/index.html`)

Vanilla JS SPA — no bundler, no framework.

**`RinkFinder` class** manages all state and rendering:
- `this.rinks` — fetched from `/api/rinks` on init
- `this.state` — single state object (search, filters, selectedRinkId, drawerOpen, activeTab, locationStatus, mobileView, checkinsById, checkinConfirm, heroIdx, myCheckins, myReviews, myPhotos, reviewOpen, reviewRating, reviewToast, photoToast, currentUser, showAuth, authMode, etc.)
- `setState(partial | fn)` — merges partial state and calls `render(prev)`
- `render(prev)` — diffs against prev state, updates the DOM in targeted sections

**Three dynamic render sections** (rebuilt via `innerHTML` on change):
- `#rink-list` + `#mobile-rink-list` — rink cards, rebuilt on filter/search/selection changes
- `#drawer-body` — Info/Photos/Reviews/Schedule tab content, rebuilt on selection/tab/checkin changes (Schedule is a UI label only — it still renders `rink.events` via `renderEventsTab()`)
- Modals — toggled via `display` on `showReport`/`showAddRink`/`showAuth` state. The auth modal doubles as sign-in/sign-up, switching via `authMode` (`updateAuthUI()` toggles the display-name field, title, and error text)

**All other DOM updates** (location label, toggle state, filter chip active class, distance label, count) are targeted property sets, not full re-renders.

**Detail drawer structure** (`renderDrawer()`, `static/index.html`):
- Fixed **photo hero** (168px, gradient scrim) with a "{N} photos" chip and close button, overlaid rink name/badges — photos are deterministic placeholder `picsum.photos` URLs seeded by rink id (`getPhotos()`), not real rink photos (see Not Yet Implemented)
- Below the hero, one scrollable container holds, in order: **thumb rail** (`renderThumbRail()` — click a thumb or the Photos tab to re-feature it as the hero via `heroIdx`), a **check-in + Directions row** (`renderCheckinRow()` — visible across all tabs, unlike the old Info-tab-only button), a **live check-in feed card** (`renderFeedCard()` — deterministic mock rows from `getMockFeed()`, plus a persistent "You" row once `myCheckins[rinkId]` is set), then a **sticky tab bar** (Info/Photos/Reviews/Schedule) and the tab body
- `myCheckins`/`myReviews`/`myPhotos` are session-only client state overlaid on top of the persisted `rinks.json` data (same pattern as the pre-existing `checkinsById`) — nothing here is sent to the backend
- The Reviews tab's composer reads its `<textarea>` via `document.getElementById('review-text').value` only at submit time (not mirrored into `state` on every keystroke) to avoid `innerHTML`-driven focus loss, since `renderDrawer()` is not diffed/keyed

**Map** (Leaflet.js 1.9.4 + CartoDB Dark Matter tiles, free, no API key):
- Custom teardrop `divIcon` pins: cyan default, gold when selected
- `updateMarkers()` called on filter/search/selection changes — adds/removes markers from the map to match the filtered list
- `map.invalidateSize()` called after drawer opens/closes so Leaflet redraws to the new viewport width
- `map.panTo()` called when a rink is selected

**Geolocation flow:**
1. `requestLocation()` called on init and on nav button click
2. On grant: flies to user coords, zoom 10, adds cyan circle marker, sorts by distance
3. On deny: "Location Off" label, distance filter/sort gracefully hidden

**`openNow`** is computed dynamically in the browser from `hours[day]` + current local time — not stored in `rinks.json`.

**Responsive breakpoint:** 768px
- Below: sidebar hidden, nav links hidden, floating Map/List toggle, full-screen list overlay (`#mobile-list`)
- Above: 355px sidebar, 400px detail drawer

### Data (`rinks.json`)

Source of truth for rink data — edit by hand to add/remove/update. Synced into the `Rink` table (Postgres/SQLite, see Backend above) on every app startup: rows are upserted by `id`, and any DB row whose `id` is no longer present in `rinks.json` is deleted, so removals in the file propagate too. `openNow` is not stored — it's derived at runtime in the browser.

**Current count:** ~658 rinks, covering all 50 states. Built up via state-by-state CSV batches from 2026-06-30 through 2026-07-02, plus a gap-finding merge pass — see git log for the batch-by-batch history.

**Bulk import workflow:**
1. Copy `rinks_import_template.csv`, fill in one region's worth of rinks, save as a new file.
2. Run `python scripts/import_rinks_csv.py path/to/batch.csv` — appends to `rinks.json` with sequential `id`s.
3. Push `rinks.json` to `main` → Railway auto-deploys and syncs to Postgres on startup.

**Manual spot-check / gap-finding workflow:**
1. Run `python scripts/export_rinks_csv.py` — dumps every rink to `rinks_full_export.csv`, sorted by state/city/name for easy scanning.
2. Edit that one file by hand: correct any row's fields, or add new rows with a blank `id` for rinks that are missing entirely.
3. Run `python scripts/merge_rinks_csv.py rinks_full_export.csv` — updates existing rinks by `id` (only reports fields that actually changed) and appends blank-`id` rows as new rinks. Never deletes; round-trips with zero diff if nothing was edited.
4. Push `rinks.json` to `main` as usual.

**CSV field notes (learned from IL/WI batch):**
- `type` — use `NHL`, `OLYMPIC`, `SYNTHETIC`, or `STANDARD`. `Indoor` also accepted (maps to `STANDARD`). Use `OLYMPIC` for rinks that explicitly have an Olympic-size (200×100 ft) sheet. Any other value (e.g. `Arena`, `Ice Rink`) silently falls back to `STANDARD` in the import script — prefer setting `STANDARD` explicitly in the CSV for multi-purpose/pro arenas rather than relying on the fallback.
- `amenities` — comma-separated or semicolon-separated, both work (auto-detected).
- `website` — `https://` and `http://` prefixes are stripped automatically.
- `hours_*` — use `"Varies"` when hours change seasonally/weekly (stored as-is and displayed). Leave blank to default to `"Call for hours"`.
- `events`/`reviews`/`rating`/`reviewCount`/`checkins` — not in the CSV. Rating/counts get randomized illustrative placeholders; events/reviews start empty.
- Watch for the same address appearing twice under different names (e.g. a rink under an old name and its current naming-rights name) — that's usually one rink double-listed, not two distinct facilities. Co-located but genuinely distinct facilities (e.g. a pro team's game arena and a separate public rec rink in the same complex) are fine to keep as separate entries.

**Schema** (mirrors the `Rink` SQLModel in `main.py` field-for-field — `hours`/`amenities`/`events`/`reviews` are stored as JSON columns, everything else as real columns):
```json
{
  "id": 1,
  "name": "Rink Name",
  "address": "123 Ice Ln",
  "city": "Boston",
  "state": "MA",
  "lat": 42.35,
  "lng": -71.15,
  "type": "NHL",           // "NHL" | "OLYMPIC" | "SYNTHETIC" | "STANDARD"
  "isPublic": true,
  "rating": 4.6,
  "reviewCount": 312,
  "phone": "(617) 555-0000",
  "website": "example.com",   // without https://
  "checkins": 847,
  "hours": {
    "Mon": "6am–10pm",
    "Tue": "6am–10pm",
    "Wed": "6am–10pm",
    "Thu": "6am–10pm",
    "Fri": "6am–10pm",
    "Sat": "8am–8pm",
    "Sun": "Closed"           // or "Private" for members-only
  },
  "amenities": ["Pro Shop", "Locker Rooms"],
  "events": [{ "title": "Public Skate", "date": "Sat 1–3 PM" }],
  "reviews": [{ "author": "Name", "rating": 5, "text": "Great rink.", "date": "2d ago" }]
}
```

### Brand System (`static/brand-tokens.css`, `static/logo/`)

- Copied from `C:\Users\lukec\Desktop\SpendTools\design_handoff_brand_system\` — do not edit in place; re-copy from source if the design system is updated
- Dark theme activated by `<html data-theme="dark">` on the root element
- All colors in `index.html` use `var(--token-name)` from this file
- Key tokens: `--bg` (#0A0E1A), `--surface` (#131A2B), `--surface-2` (#1C2540), `--border` (#2A3450), `--color-primary` (cyan #14CFCF), `--font-display` (Space Grotesk), `--font-body` (Hanken Grotesk), `--font-mono` (Space Mono)

---

## Not Yet Implemented

- Google Places API integration (rink data currently curated by hand in `rinks.json`)
- Admin UI for moderating community-submitted rinks (sit in the `PendingRink` table, unvalidated) — accounts now exist, so this can gate on an `isAdmin`-style check when built
- Server-persisted check-ins, reviews, and photos (session-only in v1 — see `myCheckins`/`myReviews`/`myPhotos` above) — accounts now exist to attribute these to, but none of it is wired to the `User` table
- Schema migrations (tables are created via `SQLModel.metadata.create_all()`, no Alembic yet)
- Real rink photos — the drawer's photo hero/thumb rail/Photos tab currently use deterministic placeholder images (`picsum.photos` seeded by rink id), not actual photos of the rinks; no `photos` field exists on the `Rink` model yet
- Community and News sections (nav links present but inactive)
- "Submit an Event" button (UI only, no backend) — "Write a Review" now has a working session-local composer (see above), just not server-persisted
