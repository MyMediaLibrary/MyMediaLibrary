# Mediatheque — Project Context for Claude Code

> Last updated: April 2026 — reflects full session history

## What is Mediatheque

Self-hosted media library dashboard for Kodi/Jellyfin/Emby users. Scans local video files, reads metadata from `.nfo` files (Kodi/Jellyfin format), fetches streaming provider availability via Jellyseerr, and serves a filterable web interface in a single Docker container on port 8094.

**One-liner:** Visualize your entire media library, spot what's already on your streaming subscriptions, and identify low-quality encodes worth upgrading.

---

## Repository Structure

```
mediatheque/
├── CLAUDE.md
├── README.md             ← bilingual EN/FR
├── .gitignore
├── compose.yaml
├── conf/
│   ├── Dockerfile
│   ├── scanner.py        ← Python scanner + HTTP API server
│   ├── entrypoint.sh     ← container startup
│   └── nginx.conf        ← nginx (envsubst for LIBRARY_PATH)
└── data/
    ├── index.html        ← HTML shell only (~23kb)
    ├── app.css           ← all styles (~33kb)
    └── app.js            ← all JavaScript (~78kb, 1612 lines)
```

---

## Architecture Decisions

### File split (index.html / app.css / app.js)
The original single-file index.html was split into 3 files. `index.html` is the HTML shell only. `app.css` has all styles. `app.js` has all JS. Dockerfile copies full `data/` directory (`COPY data/ /data/`).

### scanner.py
- **No external DB** — generates `library.json` only
- **NFO-first** — reads all metadata from `.nfo` files (title, year, tmdb_id, resolution, codec, HDR, runtime, season/episode counts)
- **Jellyseerr = providers only** — fetches FR streaming providers via tmdb_id directly (no search by title). Disable via `ENABLE_JELLYSEERR=false`.
- **Two media types:** `movie` (flat folder) and `tv` (tvshow.nfo + season subfolders)
- **Parallel enrichment:** ThreadPoolExecutor(5) per category
- **providers_fetched flag** — distinguishes "no FR providers" from "never fetched"
- **Rotating log:** 5MB max, 3 backups at `/var/log/scanner.log`
- **HTTP API server** on `127.0.0.1:8095`: `POST /api/scan/start`, `GET /api/scan/status`, `GET /health`
- **Exposes `config` block** in library.json with all env vars (except API key — just `jellyseerr_key_set: bool`)

### nginx.conf
- `/library.json` — no-cache
- `/posters/` — serves local poster images from LIBRARY_PATH (rewrite + `merge_slashes off` for `#`, `%`, spaces)
- `/api/auth` — password check endpoint, proxies to `127.0.0.1:8095`
- `/api/scan` and `/health` — proxy to `127.0.0.1:8095`
- `LIBRARY_PATH` injected via `envsubst` at container startup (requires `gettext` in Dockerfile)

### entrypoint.sh
- Runs `envsubst` on nginx.conf before starting nginx
- Writes `/app/scanner_env.sh` (all env vars, chmod 600)
- Writes `/app/scan_cron.sh` (sources scanner_env.sh then runs scanner)
- Cron calls the wrapper — avoids dcron env inheritance issues on Alpine

---

## library.json Schema

```json
{
  "scanned_at": "ISO date",
  "library_path": "/mnt/media/library",
  "total_items": 1234,
  "categories": ["Movies", "Tv"],
  "config": { "library_path": "...", "enable_movies": true, "movies_folders": "movies", "enable_series": true, "series_folders": "tv", "scan_cron": "0 3 * * *", "log_level": "INFO", "enable_jellyseerr": true, "jellyseerr_url": "...", "jellyseerr_key_set": true },
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
| `LIBRARY_PATH` | `/mnt/media/library` | Root path |
| `OUTPUT_PATH` | `/data/library.json` | JSON output |
| `ENABLE_MOVIES` | `true` | Enable movie scanning |
| `MOVIES_FOLDERS` | `movies` | Comma-separated folder names |
| `ENABLE_SERIES` | `true` | Enable TV scanning |
| `SERIES_FOLDERS` | `tv` | Comma-separated folder names |
| `SCAN_CRON` | `0 3 * * *` | Cron schedule |
| `LOG_LEVEL` | `INFO` | DEBUG/INFO/WARNING/ERROR |
| `ENABLE_JELLYSEERR` | `true` | Enable provider enrichment |
| `JELLYSEERR_URL` | — | Jellyseerr URL |
| `JELLYSEERR_APIKEY` | — | Jellyseerr API key |
| `APP_PASSWORD` | — | Optional password protection (enables login screen) |

All variables visible in Settings popup (⚙️ in sidebar). Compose-configured = read-only. Otherwise editable, saved to localStorage.

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

### Settings Modal
- 4 tabs: Bibliothèque / Scan / Jellyseerr / Système
- Système tab has: synopsis toggle (`enablePlot`), log level
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

## Provider Whitelist (normalized)
`Amazon Prime`, `Netflix`, `Max`, `Disney+`, `Paramount+`, `Apple TV+`, `Animation Digital Network`, `Crunchyroll`

---

## Known Constraints / Gotchas

- **nginx envsubst**: requires `gettext` in Dockerfile (`apk add gettext`)
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

---

## Authentication
Optional password protection via `APP_PASSWORD` environment variable. When set, the frontend shows a login screen; credentials are checked via `POST /api/auth`. Without `APP_PASSWORD`, the app is accessible without authentication — use a reverse proxy (NPM, Traefik) or VPN/Tailscale for network-level protection.

---

## Deployment

```bash
# First deploy
git clone https://github.com/magicgg91/mediatheque.git /opt/stacks/mediatheque
cd /opt/stacks/mediatheque && nano compose.yaml
docker compose up -d --build

# Update conf/ files → rebuild needed
docker compose down && docker compose up -d --build

# Update data/ files only → no rebuild (volume mounted)
git pull  # nginx serves ./data/ directly

# Common commands
docker compose exec mediatheque python3 /app/scanner.py --reset
docker compose exec mediatheque python3 /app/scanner.py --quick
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
