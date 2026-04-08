# Documentation — MyMediaLibrary (EN)

## Table of contents

1. [Overview](#1-overview)
2. [Installation](#2-installation)
3. [Library structure](#3-library-structure)
4. [Onboarding](#4-onboarding)
5. [Web interface](#5-web-interface)
6. [Filters](#6-filters)
7. [Streaming providers](#7-streaming-providers)
8. [Statistics](#8-statistics)
9. [Settings](#9-settings)
10. [Technical architecture](#10-technical-architecture)

---

## 1. Overview

**MyMediaLibrary** is a self-hosted dashboard for visualizing a movie and TV library. It runs in a single Docker container (nginx + Python 3 + dcron) with no database.

**Flow:**
1. The Python scanner reads subdirectories of `LIBRARY_PATH`, parses `.nfo` files (Kodi/Jellyfin/Emby format), and generates `data/library.json`.
2. The web interface (vanilla JS) loads `library.json` and renders cards with filters, sorting, and statistics.
3. Configuration is persisted in `data/config.json` (folders, Jellyseerr, UI preferences).

---

## 2. Installation

**Requirements:** Docker + Docker Compose, library with `.nfo` files.

```bash
mkdir mymedialibrary && cd mymedialibrary && mkdir data
curl -O https://raw.githubusercontent.com/MyMediaLibrary/MyMediaLibrary/main/compose.yaml
# edit compose.yaml — update the volume path
docker compose up -d
```

Open `http://localhost:8094`.

### compose.yaml

```yaml
services:
  mymedialibrary:
    image: ghcr.io/mymedialibrary/mymedialibrary:latest
    container_name: mymedialibrary
    ports:
      - "8094:80"
    volumes:
      - ./data:/data                        # config.json, library.json, scanner.log
      - /path/to/your/library:/library:ro   # your media library, read-only
    environment:
      LIBRARY_PATH: /library
      # APP_PASSWORD: ""
    restart: unless-stopped
```

### Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `LIBRARY_PATH` | ✅ | — | Root path of the library inside the container |
| `APP_PASSWORD` | ❌ | — | Password (enables login screen) |

Auto-scan schedule and log level are configured in **Settings > System** and persisted in `config.json`.

### Updating

```bash
docker compose pull && docker compose up -d
```

---

## 3. Library structure

The scanner reads the **direct subdirectories** of `LIBRARY_PATH`. Each subdirectory is a **folder** that you assign a type to (Movies, Series, Ignore) from the interface.

### Recommended structure

```
/library/                    ← LIBRARY_PATH
├── movies/
│   ├── Film (2010)/
│   │   ├── Film.mkv
│   │   └── Film.nfo
│   └── ...
├── series/
│   ├── Serie/
│   │   ├── tvshow.nfo
│   │   ├── Season 01/
│   │   │   ├── Serie - S01E01.mkv
│   │   │   └── Serie - S01E01.nfo
│   │   └── ...
│   └── ...
└── anime/
    └── ...
```

### .nfo files

`.nfo` files (Kodi/Jellyfin format) are read automatically to extract:
- Title, year, synopsis, runtime
- Resolution, video codec, audio codec, HDR
- Local posters (poster.jpg/png adjacent to the .nfo)

Without `.nfo`, the title is derived from the folder name (e.g. `Film (2010)` → title `Film`, year `2010`).

### Multiple sources

```yaml
volumes:
  - /nas1/movies:/library/movies:ro
  - /nas2/series:/library/series:ro
  - ./data:/data
environment:
  LIBRARY_PATH: /library
```

---

## 4. Onboarding

The setup wizard appears on first launch (or when `config.json` is missing/empty).

**Steps:**

1. **Welcome screen** — app description, "Get started" button
2. **Folders** — lists subdirectories of `LIBRARY_PATH`, assign a type to each (Movies / Series / Ignore). Unconfigured folders are skipped during scan. The "Next" button is disabled until all folders are configured.
3. **Jellyseerr** (optional) — URL + API key, connection test button
4. **Summary + Scan** — shows the configuration, "Launch scan" button that starts the initial scan and redirects to the library when done

---

## 5. Web interface

### Views

- **Library** — card grid (poster, title, year, resolution, codec, providers) + table view
- **Statistics** — detailed charts
- **Scanner** — manual trigger + last scan log

### Sidebar (desktop) / mobile panel

Shows active filters and allows browsing the library. On mobile, accessible via the filter button at the bottom of the screen.

### Cards

Each card displays:
- Local poster (if available) or placeholder
- Title + year
- Resolution (colored badge: 4K, 1080p, 720p…)
- Video codec
- Streaming provider logos (if Jellyseerr is enabled)
- Season/episode count (series)
- Synopsis on hover (optional, configurable in settings)

### Theme and language

- Light/dark theme, toggled via a button in the sidebar (sun/moon icon), persisted across sessions
- FR/EN language selectable in system settings, no page reload required

---

## 6. Filters

### Pill filters (low cardinality)

- **Type** — All / Movies / Series
- **Resolution** — All / 4K / 1080p / 720p / SD
- **Group** — by configured folder
- **Storage bar** — visual display of disk usage per folder

These filters are rendered as pill buttons (single selection).

### Multi-select dropdown filters (high cardinality)

- **Streaming (FR)** — available providers (Netflix, Prime Video…) + "No provider" option
- **Video codec** — H.264, H.265/HEVC, AV1…
- **Audio codec** — AAC, AC3, EAC3, TrueHD…

These filters use a dropdown with checkboxes. Selection is multiple (OR logic: an item passes if it matches **at least one** of the selected codecs/providers). Selection state is persisted in `localStorage`.

#### "No provider" option

In the Streaming filter, a special **"No provider"** option is shown first. It filters items that have no streaming provider associated.

#### Dynamic counts

The counts displayed in each dropdown correspond to items matching the **other active filters** (faceted search logic — `baseItems(except)` excludes the current filter from the count calculation).

---

## 7. Streaming providers

Streaming enrichment is optional and relies on **Jellyseerr**.

### Configuration

URL + API key in settings (Jellyseerr tab) or during onboarding. A "Test connection" button validates the credentials.

### Normalization

Provider names returned by Jellyseerr are normalized via `app/providers.json` (e.g. `"Amazon Prime Video"` → `"Prime Video"`). This file also associates an SVG logo with each provider.

### Visibility

Each provider can be hidden in settings (Jellyseerr tab → "Provider visibility"). Hidden providers do not appear on cards or in the filter.

---

## 8. Statistics

The Statistics tab displays:

- **Global summary** — total items, files, disk usage
- **By type** — Movies / Series breakdown
- **Resolution** — pie chart
- **Video codec** — pie chart
- **Audio codec** — pie chart
- **Release years** — bar chart by year or decade
- **Monthly evolution** — line chart of additions per month (size and/or item count), periods: all / 12 months / 30 days
- **By group / folder** — size or count
- **Streaming** — availability by provider, breakdown by group

All charts are filtered by the active library filters.

---

## 9. Settings

Accessible via the ⚙️ icon at the bottom of the sidebar.

### Library tab

- Library path (`LIBRARY_PATH`, read-only if set via compose.yaml)
- Show/hide Movies or Series
- Table of detected folders: type (Movies/Series/Ignore) + individual visibility

### Jellyseerr tab

- Enable/disable enrichment
- URL + API key + connection test
- Per-provider visibility (visible/hidden)

### System tab

- Language (FR/EN)
- Theme (Dark/Light)
- Accent color (picker + reset)
- Synopsis on hover (on/off)
- Auto-scan (cron)
- Log level
- Version

---

## 10. Technical architecture

### Stack

- **Container**: nginx:alpine + Python 3 + dcron (single image)
- **Frontend**: HTML/CSS + vanilla JS (no framework)
- **Backend**: minimal Python server (`scanner/server.py`) — REST API routes + static file serving
- **Scanner**: Python (`scanner/scan.py`) — `.nfo` parsing, metadata computation, `library.json` writing
- **Persistence**: `data/config.json` (config), `data/library.json` (index), `localStorage` (UI state)

### Filter state (app.js)

High-cardinality filters use **JS Sets**:

```js
let activeCodecs      = new Set();  // selected video codecs
let activeAudioCodecs = new Set();  // selected audio codecs
let activeProviders   = new Set();  // selected providers (+ '__none__')
```

The sentinel `'__none__'` in `activeProviders` represents items with no provider.

Low-cardinality filters use scalars (`'all'` or a value string).

### Dropdowns (renderFilterDropdown)

Generic function `renderFilterDropdown({ containerId, counts, label, activeSet, toggleFn, clearFn, getDisplay, pinFirst })`:
- `containerId`: target DOM element ID
- `counts`: `{ key: number }` occurrence object
- `activeSet`: the JS Set holding active state
- `toggleFn` / `clearFn`: global function names (strings) used in inline `onclick` handlers
- `pinFirst`: key to pin at the top (e.g. `'__none__'`)

Only one dropdown is open at a time (`openDropdown` global). Closing on outside click is handled via `document.addEventListener('click', ...)`.

### audio_codec field

The Python scanner writes the field in **snake_case**: `audio_codec`. In `app.js`, always use `item.audio_codec` (never `item.audioCodec`).

### Desktop + mobile rendering

Each dropdown filter targets both its containers directly (e.g. `codecSection` + `codecSectionMobile`). The `syncMobileFilters()` function only syncs pill-based filters (storage, resolution).

### Internationalisation

Files `app/i18n/fr.json` and `app/i18n/en.json`. Function `t('namespace.key')` with `{n}` substitution and `{s}` plural support. Language is persisted in `config.json` server-side and in `localStorage` client-side.
