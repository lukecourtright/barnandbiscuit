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

Deploy to Railway via `railway.toml`. Auto-deploys on push to `main`.

No required environment variables in v1.

## Brand Name

The brand name is TBD. Change `this.BRAND` at the top of `static/index.html` and the `<title>` tag when the name is finalized.

## Architecture

**Backend (`main.py`):**
- `GET /` → serves `static/index.html`
- `GET /api/rinks` → reads and returns `rinks.json`
- `POST /api/rinks/submit` → appends community-submitted rinks to `pending_rinks.json` (not public until moderated)
- `/static` → static file mount

**Frontend (`static/index.html`):**
- Vanilla JS SPA, no bundler or framework
- `RinkFinder` class with `setState()` → `render()` pattern
- Leaflet.js 1.9.4 + CartoDB Dark Matter tiles (free, no API key)
- `brand-tokens.css` provides CSS custom properties for all colors/fonts/radii
- Single breakpoint at 768px (mobile vs desktop)

**Data (`rinks.json`):**
- 15 seed rinks; edit by hand to add/remove rinks
- `openNow` is computed dynamically in the browser from `hours` + current local time

**Brand system (`static/brand-tokens.css`, `static/logo/`):**
- Copied from `design_handoff_brand_system/` — do not edit; re-copy from source if updated
- Dark theme activated via `<html data-theme="dark">`

## Adding Rinks

Edit `rinks.json` directly. Schema:
- `id`, `name`, `address`, `city`, `state`, `lat`, `lng`
- `type`: `"NHL"` | `"OLYMPIC"` | `"SYNTHETIC"` | `"STANDARD"`
- `isPublic`: boolean
- `rating`, `reviewCount`, `checkins`
- `phone`, `website` (without https://)
- `hours`: object with Mon–Sun string values (e.g. `"6am–10pm"` or `"Closed"`)
- `amenities`: string array
- `events`: `[{ title, date }]`
- `reviews`: `[{ author, rating, text, date }]`
