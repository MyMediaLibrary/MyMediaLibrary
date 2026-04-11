# Documentation — MyMediaLibrary (EN)

## Table of contents

1. [Overview](#1-overview)
2. [Technical architecture](#2-technical-architecture)
3. [Installation](#3-installation)
4. [Library structure](#4-library-structure)
5. [Onboarding](#5-onboarding)
6. [Web interface](#6-web-interface)
7. [Filters](#7-filters)
8. [Streaming providers](#8-streaming-providers)
9. [Quality Scoring](#9-quality-scoring)
10. [Statistics](#10-statistics)
11. [Settings](#11-settings)

---

## 1. Overview

**MyMediaLibrary** is a self-hosted dashboard to visualize a movie and TV show library. It runs in a single Docker container with no database.

**Flow:**
1. The Python scanner reads subdirectories of `LIBRARY_PATH`, parses `.nfo` files (Kodi/Jellyfin/Emby format), and generates `data/library.json`.
2. The web interface (vanilla JS) loads `library.json` and renders cards with filters, sorting, and statistics.
3. Configuration is persisted in `data/config.json` (folders, Jellyseerr, UI preferences).

---

## 2. Technical architecture

### Stack

- **Container**: nginx:alpine + Python 3 + dcron (single image)
- **Frontend**: HTML/CSS + vanilla JS (no framework)
- **Backend**: minimal Python server (`scanner/server.py`) — REST API routes + static file serving
- **Scanner**: Python (`scanner/scan.py`) — `.nfo` parsing, metadata computation, `library.json` writing
- **Persistence**: `data/config.json` (config), `data/library.json` (index), `localStorage` (UI state)

### Internationalisation

Files `app/i18n/fr.json` and `app/i18n/en.json`. Function `t('namespace.key')` with `{n}` substitution and `{s}` plural support. Language is persisted in `config.json` server-side and in `localStorage` client-side.

---

## 3. Installation

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

## 4. Library structure

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

`.nfo` files (Kodi/Jellyfin/Emby format) are read automatically to extract:
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

## 5. Onboarding

The setup wizard appears on first launch (or when `config.json` is missing/empty).

**Steps:**

1. **Welcome screen** — app description, language selection, "Get started" button
2. **Folders** — lists subdirectories of `LIBRARY_PATH`, assign a type to each (Movies / Series / Ignore). Unconfigured folders are skipped during scan. The "Next" button is disabled until at least 1 folder is configured.
3. **Jellyseerr** (optional) — URL + API key, connection test button
4. **Summary + Scan** — shows the configuration, "Launch scan" button that starts the initial scan and redirects to the library when done

---

## 6. Web interface

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
- Streaming provider logos (if Jellyseerr is enabled)
- Season/episode count (series)
- Synopsis on hover (optional, configurable in settings)

### Theme and language

- Light/dark theme, toggled via a button in the sidebar (sun/moon icon), persisted across sessions
- FR/EN language selectable in system settings, no page reload required

---

## 7. Filters

### Pill filters (low cardinality)

- **Type** — All / Movies / Series
- **Resolution** — All / 4K / 1080p / 720p / SD
- **Group** — by configured folder

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

## 8. Streaming providers

Streaming enrichment is optional and relies on **Jellyseerr**.

### Configuration

URL + API key in settings (Jellyseerr tab) or during onboarding. A "Test connection" button validates the credentials.

### Normalization

Provider names returned by Jellyseerr are normalized via `app/providers.json` (e.g. `"Amazon Prime Video"` → `"Prime Video"`). This file also associates an SVG logo with each provider.

### Visibility

Each provider can be hidden in settings (Jellyseerr tab → "Provider visibility"). Hidden providers do not appear on cards or in the filter.

---

## 9. Quality Scoring

Each media item receives a global **quality score out of 100**. This score is calculated from multiple technical criteria to help identify higher-quality files, detect weak points, and prioritize upgrades in your library.

### Score structure

| Criterion | Points |
|---|---:|
| Video | 50 |
| Audio | 20 |
| Languages | 15 |
| Size | 15 |
| **Total** | **100** |

### Detailed criteria

#### 🎥 Video (50)

| Sub-criterion | Value | Points |
|---|---|---:|
| Resolution | 2160p | 25 |
| Resolution | 1080p | 20 |
| Resolution | 720p | 10 |
| Resolution | SD | 5 |
| Resolution | Unknown | 8 |
| Codec | AV1 / HEVC / H.265 | 15 |
| Codec | H.264 / AVC | 10 |
| Codec | Legacy (MPEG-2, VC-1, Xvid, DivX) | 3 |
| Codec | Unknown | 6 |
| HDR | Dolby Vision | 10 |
| HDR | HDR10+ | 8 |
| HDR | HDR10 / HLG | 5 |
| HDR | SDR | 0 |
| HDR | Unknown | 0 |

#### 🔊 Audio (20)

| Audio codec | Points |
|---|---:|
| TrueHD / Atmos | 20 |
| DTS-HD | 18 |
| DTS | 15 |
| EAC3 | 12 |
| AC3 | 10 |
| AAC | 6 |
| MP3 / MP2 | 3 |
| Unknown | 8 |

#### 🌍 Languages (15)

| Language profile | Points |
|---|---:|
| MULTI (French + others) | 15 |
| French only | 10 |
| Original language only (VO) | 5 |
| Unknown | 3 |

#### 💾 Size (15)

| Consistency state | Points |
|---|---:|
| Coherent | 15 |
| Too large | 8 |
| Too small | 5 |
| Unknown | 5 |

##### Size references (optimal range)

| Resolution | Codec | Optimal size |
|---|---|---|
| 1080p | H.265 | 2–10 GB |
| 1080p | H.264 | 4–15 GB |
| 4K | H.265 | 8–25 GB |
| 720p | All | 2–6 GB |
| SD | All | 500 MB – 2 GB |

### Penalties

Penalties are applied to correct incoherent combinations and avoid inflated scores in weak technical profiles.

| Situation | Penalty | Explanation |
|---|---|---|
| High video quality + weak audio | -10 / -5 | A very sharp image with poor sound creates an unbalanced viewing experience. |
| High resolution + legacy codec | -8 / -4 | HD/4K video encoded with an older codec often indicates less efficient compression quality. |
| Good video + limited languages | -5 | The file quality is good, but usability is lower for users needing more language options. |
| Inconsistent size | -5 | A file that is too small or too large for its profile can indicate uneven quality. |

> Maximum applied penalty: 20 points.

### Final score

```text
Final Score = Base Score - Penalties
Clamped between 0 and 100
```

### Quality levels

```text
0–20   → Level 1
21–40  → Level 2
41–60  → Level 3
61–80  → Level 4
81–100 → Level 5
```

### UI integration

Quality scoring is visible throughout the interface:
- badge on media cards
- table column
- CSV export
- statistics

### Tooltip

Hovering the quality badge shows a complete detailed tooltip:
- full breakdown by category
- applied penalties

### Filters

Quality scoring integrates with dedicated filters:
- level-based filter pills
- consistent level colors
- multi-selection support
- include / exclude behavior

### Stats

Statistics include score distribution views to provide a global quality analysis of the library.

---

## 10. Statistics

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

## 11. Settings

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
- Accent color (picker + reset)
- Synopsis on hover (on/off)
- Auto-scan (cron)
- Log level
- Version

---
