# MyMediaLibrary — Project Context for Claude Code

> Last updated: April 2026 — reflects full session history

## What is MyMediaLibrary

Self-hosted media library dashboard for Kodi/Jellyfin/Emby users. Scans local video files, reads metadata from `.nfo` files (Kodi/Jellyfin format), fetches streaming provider availability via Jellyseerr, and serves a filterable web interface in a single Docker container on port 8094.

**One-liner:** Visualize your entire media library, spot what's already on your streaming subscriptions, and identify low-quality encodes worth upgrading.

---

## Repository Structure

```
MyMediaLibrary/
├── .github/
│   └── workflows/
│       └── docker-publish.yml  ← build + push to ghcr.io on every push to main
├── CLAUDE.md
├── README.md             ← bilingual EN/FR
├── .gitignore
├── compose.yaml
├── conf/
│   ├── Dockerfile
│   ├── scanner.py        ← Python scanner + HTTP API server
│   ├── entrypoint.sh     ← container startup
│   └── nginx.conf        ← full nginx config (envsubst for LIBRARY_PATH)
└── app/
    ├── index.html           ← HTML shell only (~23kb)
    ├── app.css              ← all styles (~33kb)
    ├── app.js               ← all JavaScript (~78kb, 1612 lines)
    ├── providers_map.json   ← reference provider map (versioned, copied to /data/ on first start)
    └── i18n/
        ├── fr.json          ← French translations
        └── en.json          ← English translations
```

---

## Architecture Decisions

### Image auto-suffisante
App code (`app/`) is embedded in the Docker image at `/usr/share/nginx/html/`. Only `/data` is a persistent volume (`config.json`, `library.json`, `scanner.log`). The image is published to `ghcr.io/mymedialibrary/mymedialibrary:latest` via GitHub Actions on every push to `main`.

### File split (index.html / app.css / app.js)
The original single-file index.html was split into 3 files. `index.html` is the HTML shell only. `app.css` has all styles. `app.js` has all JS. Dockerfile copies full `app/` directory (`COPY app/ /usr/share/nginx/html/`).

### scanner.py
- **No external DB** — generates `library.json` only
- **NFO-first** — reads all metadata from `.nfo` files (title, year, tmdb_id, resolution, codec, HDR, runtime, season/episode counts)
- **Jellyseerr = providers only** — fetches FR streaming providers via tmdb_id directly (no search by title). Disable via `ENABLE_JELLYSEERR=false`.
- **Two media types:** `movie` (flat folder) and `tv` (tvshow.nfo + season subfolders)
- **Parallel enrichment:** ThreadPoolExecutor(5) per category
- **providers_fetched flag** — distinguishes "no FR providers" from "never fetched"
- **Provider normalization via file** — `load_provider_map()` reads `/data/providers_map.json` at scan start. Raw provider names pass through as-is if not in the map. No hard-coded regex.
- **providers_raw / providers_raw_meta** — raw provider names accumulated across scans in `library.json` (for map building)
- **Rotating log:** 5MB max, 3 backups at `/data/scanner.log`
- **HTTP API server** on `127.0.0.1:8095`: `POST /api/scan/start`, `GET /api/scan/status`, `GET /health`, `GET /api/providers-map`, `POST /api/providers-map`
- **Exposes `config` block** in library.json with all env vars (except API key — just `jellyseerr_key_set: bool`)

### nginx.conf
- Full nginx config (worker_processes, events, http blocks) — copied to `/etc/nginx/nginx.conf`
- `root /usr/share/nginx/html` — serves static app files
- `/library.json` — `alias /data/library.json` with no-cache headers
- `/posters/` — serves local poster images from LIBRARY_PATH (rewrite + `merge_slashes off` for `#`, `%`, spaces)
- `/api/scan`, `/api/config`, `/api/auth`, `/api/jellyseerr`, `/api/providers-map`, `/health` — proxy to `127.0.0.1:8095`
- `LIBRARY_PATH` injected via `envsubst` at container startup (requires `gettext` in Dockerfile)

### entrypoint.sh
- Runs `envsubst` on `/etc/nginx/nginx.conf` before starting nginx
- Copies `app/providers_map.json` → `/data/providers_map.json` if absent (never overwrites)
- Writes `/app/scanner_env.sh` (all env vars, chmod 600)
- Writes `/app/scan_cron.sh` (sources scanner_env.sh then runs scanner)
- Cron file at `/etc/cron.d/mymedialibrary`
- Cron calls the wrapper — avoids dcron env inheritance issues on Alpine

---

## library.json Schema

```json
{
  "scanned_at": "ISO date",
  "library_path": "/library",
  "total_items": 1234,
  "categories": ["Movies", "Tv"],
  "config": { "library_path": "...", "enable_movies": true, "movies_folders": "movies", "enable_series": true, "series_folders": "tv", "scan_cron": "0 3 * * *", "log_level": "INFO", "enable_jellyseerr": true, "jellyseerr_url": "...", "jellyseerr_key_set": true },
  "providers_raw": ["Netflix", "Amazon Prime Video", "Canal+ Séries"],
  "providers_raw_meta": { "Netflix": { "logo": "https://...", "logo_url": "https://..." } },
  "items": [{
    "id": 0, "path": "movies/My.Movie.(2023)", "title": "My Movie", "raw": "My.Movie.(2023)",
    "year": "2023", "category": "Movies", "type": "movie",
    "size_b": 12345678, "size": "11.8 GB", "file_count": 1,
    "added_at": "2023-11-15T00:00:00", "added_ts": 1700006400,
    "poster": "/posters/movies/My.Movie.(2023)/poster.jpg", "poster_local": "...",
    "tmdb_id": "967582", "resolution": "1080p", "width": 1920, "height": 800,
    "codec": "H.264", "hdr": false, "plot": "...", "runtime": "87", "runtime_min": 87,
    "season_count": null, "episode_count": null,
    "providers": [{ "name": "Netflix", "logo": "https://..." }],
    "providers_fetched": true
  }]
}
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LIBRARY_PATH` | `/library` | Root path (fixed to `/library` in container — adapt volume source in compose.yaml) |
| `SCAN_CRON` | `0 3 * * *` | Cron schedule |
| `LOG_LEVEL` | `INFO` | DEBUG/INFO/WARNING/ERROR |
| `ENABLE_JELLYSEERR` | `true` | Enable provider enrichment |
| `JELLYSEERR_URL` | — | Jellyseerr URL |
| `JELLYSEERR_APIKEY` | — | Jellyseerr API key |
| `APP_PASSWORD` | — | Optional password protection (enables login screen) |

All other settings (Jellyseerr, folders, UI preferences) are configured directly from the web interface and persisted in `config.json`.

---

## Scan Modes

| Mode | Filesystem+NFO | Jellyseerr | Notes |
|------|---------------|------------|-------|
| `--enrich` / default | ✅ | ✅ missing only | Daily recommended |
| `--quick` | ✅ | ❌ | Fast, no network |
| `--full` | ✅ | ✅ force all | Force refresh |
| `--reset` | — | — | Delete library.json |
| `--serve` | — | — | Start HTTP API |
| `--category NAME` | scoped | scoped | One category only |

---

## Frontend (app.js) — Key Architecture

### State Variables
```javascript
let allItems=[], categories=[], groups=[];
let enablePlot=true;
let activeGroup='all', activeCat='all', activeProvider='all';
let activeResolution='all', activeType='all', activeCodec='all';
let currentTab='library', currentView='grid';
let serverConfig={};  // from library.json config block
```

### Filter Flow
1. User clicks a pill → `clickX()` → sets `activeX` → calls `onFilter()`
2. `onFilter()` → `renderStorageBar()` + `renderProviderFilter()` + `renderResolutionFilter()` + `renderCodecFilter()` + `renderStats(filterItems())` + render current tab + `saveState()` + `syncMobileFilters()`
3. `filterItems()` applies all active filters + search to `allItems`
4. `baseItems(except)` — same but skips one filter (so active pills don't hide their own options)
5. Search input calls `onFilter()` directly

### Filter State Persistence
`saveState()` saves to `localStorage['mediaState']`. `restoreState()` restores and re-renders all filter pills with correct active classes.

### Layout
- **Single layout: sidebar left** — `position:sticky; top:0; height:100vh`
- `html,body { overflow:hidden }` — page scroll disabled
- `.main-content { overflow-y:auto }` — only content area scrolls
- `.app-layout { height:100vh; overflow:hidden; display:flex }`
- Sidebar resizable via drag handle (custom JS)
- **Mobile (≤768px):** sidebar hidden, fixed topbar (logo + filter/theme/settings buttons) + fixed bottom nav (3 tabs) + slide-down filter panel

### i18n System
- Translation files: `app/i18n/fr.json` and `app/i18n/en.json`
- Engine: `loadTranslations(lang)` fetches `/i18n/{lang}.json`, `t(key, vars)` resolves dot-notation keys with `{placeholder}` substitution, `applyTranslations()` updates `[data-i18n]` DOM elements
- Language stored in `config.system.language` (persisted in `config.json`)
- Applied at startup in `loadLibrary()` without page reload; changeable from Settings > Système tab
- **Auto-toggle on onboarding step 0:** `_langTimer` (setInterval 5s) alternates FR↔EN display until user clicks a language button. Cleared by `onbNext()`.
- State variables: `TRANSLATIONS = {}`, `CURRENT_LANG = 'fr'`

### Settings Modal
- 4 tabs: Bibliothèque / Jellyseerr / Système
- Système tab has: language selector (`cfgLanguage`), synopsis toggle (`enablePlot`), accent color, log level
- "Enregistrer" button only shown when editable fields exist
- Compose-configured fields → read-only with note

### Stats Panel (buildStats)
**Important:** `globalEncart` and `yearDecadeHtml` vars MUST be declared BEFORE the `return ''` statement. If inside the return, JS throws syntax error.

- **Top encart** — uses `allItems` (ignores filters): films/series/total/disk + horizontal bars per category
- **Year/Decade bar chart** — from `allItems.year`, switch button
- **Filtered pies** — Groupes, Catégories, Résolution, Codec, Providers (2-col grid, `switchablePie`)
- **Timeline curves** — monthly evolution, default: 12 months

### Mobile Table View
All `<td>` hidden by default, only `col-poster` and `col-mobile-info` shown. `col-mobile-info` is an extra `<td>` injected in `tableHTML()` with title + badges + meta.

### Lazy Loading
Grid view: batches of 100 via `IntersectionObserver`. `_lazyItems`, `_lazyPage`, `LAZY_BATCH=100`.

---

## providers_map.json

File at `/data/providers_map.json` — maps raw Jellyseerr provider names to normalized display names. Created on first container start by `entrypoint.sh` with sensible defaults. Editable by user without rebuild. Exposed via `GET/POST /api/providers-map`.

The reference file `app/providers_map.json` is versioned in the repo and embedded in the image via `COPY app/ /usr/share/nginx/html/`. On first container start, `entrypoint.sh` copies it to `/data/providers_map.json` if absent. User customizations are never overwritten on image updates.

Raw names seen during scans are accumulated in `library.json` as `providers_raw` (list) and `providers_raw_meta` (dict with logo URLs) — useful for building the map.

---

## Known Constraints / Gotchas

- **nginx envsubst**: requires `gettext` in Dockerfile (`apk add gettext`)
- **nginx.conf path**: full config at `/etc/nginx/nginx.conf` (not `conf.d/default.conf`) — entrypoint runs envsubst on this file
- **dcron env**: use `/app/scan_cron.sh` wrapper + `/app/scanner_env.sh`
- **Poster URL encoding**: `poster_rel_path()` encodes each path component — handles `#`, `%`, spaces
- **providers_fetched**: `false` = never fetched. `[]` + `true` = fetched, no FR providers
- **TV resolution**: from first episode NFO of first season folder
- **Sticky sidebar**: MUST have `html,body {overflow:hidden}` + `.main-content {overflow-y:auto}`
- **Scan dropdown**: `position:fixed` + `getBoundingClientRect()`, opens upward
- **Mobile filter sync**: `syncMobileFilters()` called unconditionally in every `onFilter()`
- **buildStats structure**: global vars before return — see Stats Panel note above
- **Duplicate IDs**: avoid having the same HTML id in both sidebar and mobile panel — use `querySelectorAll` for mobile stats bar
- **`<style>` in index.html**: there are no inline styles — all in app.css
- **`<script>` in index.html**: `<script src="app.js"></script>` before `</body>`, no defer needed
- **`select.has-value`**: CSS class applied dynamically to selects when they have a chosen value — uses `border-color: var(--accent)`
- **i18n files path**: served as static assets from `/i18n/fr.json` and `/i18n/en.json` (under `/usr/share/nginx/html/i18n/`)

---

## Authentication
Optional password protection via `APP_PASSWORD` environment variable. When set, the frontend shows a login screen; credentials are checked via `POST /api/auth`. Without `APP_PASSWORD`, the app is accessible without authentication — use a reverse proxy (NPM, Traefik) or VPN/Tailscale for network-level protection.

---

## Deployment

```bash
# First deploy (image pre-built on ghcr.io)
mkdir mymedialibrary && cd mymedialibrary
mkdir data
curl -O https://raw.githubusercontent.com/MyMediaLibrary/MyMediaLibrary/main/compose.yaml
# Edit compose.yaml: set the /library volume to your media library path
docker compose up -d

# Update
docker compose pull
docker compose up -d

# Common commands
docker compose exec mymedialibrary python3 /app/scanner.py --reset
docker compose exec mymedialibrary python3 /app/scanner.py --quick
docker compose logs -f
```

---

## Pending Ideas

- **Emby watch status** (vu/non vu) — direct browser call to Emby API via tmdb_id
- **Duplicate detection** — flag items with identical tmdb_id across categories
- **Audio language filter** — `<audio><language>` already in NFO
- **Direct link** to Jellyfin/Jellyseerr from a card via tmdb_id
- **Export Letterboxd/Trakt** — CSV with tmdb_ids
- **Heatmap** — GitHub-style calendar for library additions
