# Documentation — MyMediaLibrary (EN)

## Table of contents

1. [Overview](#1-overview)
2. [Technical architecture](#2-technical-architecture)
3. [Installation](#3-installation)
4. [Library structure](#4-library-structure)
5. [Onboarding](#5-onboarding)
6. [Scanner](#6-scanner)
7. [Data models](#7-data-models)
8. [Web interface](#8-web-interface)
9. [Filters](#9-filters)
10. [Streaming providers](#10-streaming-providers)
11. [Quality Scoring](#11-quality-scoring)
12. [Statistics](#12-statistics)
13. [Settings](#13-settings)

---

## 1. Overview

**MyMediaLibrary** is a self-hosted dashboard to visualize a movie and TV show library. It runs in a single Docker container with no database.

**Flow:**
1. The Python scanner reads subdirectories of `LIBRARY_PATH`, parses `.nfo` files (Kodi/Jellyfin/Emby format), and generates `data/library.json`.
2. The web interface (vanilla JS) loads `library.json` and renders cards with filters, sorting, and statistics.
3. Configuration is persisted in `data/config.json` (folders, Seerr, UI preferences).

---

## 2. Technical architecture

### Stack

- **Container**: nginx:alpine + Python 3 + dcron (single image)
- **Frontend**: HTML/CSS + vanilla JS (no framework)
- **Backend**: minimal Python server (`backend/scanner.py`) — REST API routes + static file serving
- **Scanner**: Python (`backend/scanner.py`) — `.nfo` parsing, metadata computation, `library.json` writing
- **Persistence**: `data/config.json` (config), `data/library.json` (index), `localStorage` (UI state)

### Internationalisation

Files `app/i18n/fr.json` and `app/i18n/en.json`. Function `t('namespace.key')` with `{n}` substitution and `{s}` plural support. Language is persisted in `config.json` server-side and in `localStorage` client-side.

### Timezone (`TZ`)

At startup, the entrypoint exports `TZ="${TZ:-UTC}"` before launching scanner services. In practice this means scanner API, initial scan and cron scans all run with `TZ` (default `UTC` when unset).

Main impact areas:
- log timestamps (for example `scanner.log`)
- technical timestamps (scan state, execution times)
- UI displays based on timestamps

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
| `TZ` | ❌ | `UTC` | Container timezone (logs and timestamps) |
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
3. **Seerr** (optional) — URL + API key, connection test button
4. **Summary + Scan** — shows the configuration, "Launch scan" button that starts the initial scan and redirects to the library when done

---

## 6. Scanner

The scanner is the core component of MyMediaLibrary. It reads the filesystem, parses `.nfo` files, and produces the JSON files consumed by the web interface.

### Overview

The scanner (`scanner.py`) analyses the content of `LIBRARY_PATH` and generates:

| File | Purpose |
|---|---|
| `/data/library.json` | Main index — loaded by the web interface |
| `/data/library_inventory.json` | Media presence/absence tracking (optional, enable in Settings > System) |

The detailed format of these files is described in the [Data models](#7-data-models) chapter.

### Scan modes

#### Quick scan

- Walks the filesystem and parses `.nfo` files
- Writes `library.json` incrementally, folder by folder
- Preserves enriched data from the previous scan (streaming providers, quality score)
- Does **not** call Seerr, does **not** recompute scores, does **not** update the inventory

#### Full scan (default)

Runs 4 phases in sequence:

1. **Filesystem + NFO** — folder traversal, `.nfo` parsing
2. **Seerr** — fetch FR streaming providers for each title
3. **Scoring** — compute quality score (if enabled in settings)
4. **Inventory** — update `library_inventory.json` (if enabled in settings)

> Each phase reads from the output of the previous phase on disk. Phases are fully independent.

### Scan triggers

| Origin | Mode | How |
|---|---|---|
| Container startup | Quick | Automatic via `entrypoint.sh` |
| Onboarding wizard | Quick | "Launch scan" button at the end of onboarding |
| "Scan" button in the UI | Full | Via the Scanner page |
| Cron | Full | Automatic schedule (Settings > System) |
| Folder configuration change | Quick | Automatic after saving in Settings > Library |

### Anti-concurrency lock

Only one scan can run at a time. The scanner uses an inter-process file lock (`/data/.scan.lock`) to coordinate all trigger origins (startup, cron, UI) and prevent simultaneous writes that would corrupt `library.json`.

If a scan is already running:
- A UI-triggered scan receives an error response (HTTP 409)
- A scheduled scan (cron or startup) is silently skipped with a log message

### Logs

Logs are available in `data/scanner.log` (host path) and viewable in Settings > System.

| Level | Content |
|---|---|
| `INFO` | Phase progression, per-folder progress, durations, detected statistics (video/audio codecs, languages, resolutions) |
| `DEBUG` | Technical details: Seerr results per item, NFO parsing, not-found items, inventory details |

### Data preservation (quick scan)

During a quick scan, enriched data accumulated by previous full scans is carried forward without being recomputed:

| Field | Source | Behavior |
|---|---|---|
| `providers` | Phase 2 (Seerr) | Copied from the existing `library.json` |
| `providers_fetched` | Phase 2 | Copied from the existing `library.json` |
| `quality` | Phase 3 (scoring) | Copied from the existing `library.json` |

The existing `library.json` is loaded **once** at the start of the scan and used as an immutable reference for all lookups. New items with no previous entry are created without enrichment — their data will be computed on the next full scan.

---

## 7. Data models

### `library.json`

Main file consumed by the web interface. Top-level structure:

```json
{
  "scanned_at": "2025-04-14T20:00:00.000000",
  "library_path": "/mnt/media/library",
  "total_items": 3289,
  "items": [ ... ],
  "meta": { "score_enabled": true }
}
```

Example item:

```json
{
  "id": "movie:Movies:The.Dark.Knight.2008",
  "path": "Movies/The.Dark.Knight.2008",
  "title": "The Dark Knight",
  "year": "2008",
  "category": "Movies",
  "type": "movie",
  "size": "14.0 GB",
  "resolution": "1080p",
  "codec": "HEVC",
  "audio_codec": "TRUEHD",
  "audio_languages": ["fra", "eng"],
  "providers": ["Netflix", "Canal+"],
  "quality": { "score": 87, "level": 5 }
}
```

The `id` field is the stable key for each item. Format: `{type}:{category}:{folder_name}`. It is identical in `library.json` and `library_inventory.json` for the same media item, enabling cross-file matching.

### `library_inventory.json`

Optional file (enable in Settings > System) that preserves the presence history of each media item and its video files across successive scans.

Main fields per item:

| Field | Description |
|---|---|
| `id` | Shared identifier with `library.json` |
| `status` | `"present"` or `"missing"` |
| `first_seen_at` | Date first detected on filesystem (never updated afterwards) |
| `last_seen_at` | Last date the item was found on the filesystem |
| `last_checked_at` | Date of the last scan that evaluated this item (updated even when missing) |
| `video_files` | List of video files with their own presence history |

**Present / missing logic:**

```
present → last_seen_at = now, last_checked_at = now
missing → last_seen_at unchanged, last_checked_at = now
```

An item becomes `"missing"` when its folder is no longer detected during a full scan covering all folders. History is preserved and the item is not deleted.

---

## 8. Web interface

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
- Streaming provider logos (if Seerr is enabled)
- Season/episode count (series)
- Synopsis on hover (optional, configurable in settings)

### Theme and language

- Light/dark theme, toggled via a button in the sidebar (sun/moon icon), persisted across sessions
- FR/EN language selectable in system settings, no page reload required

---

## 9. Filters

Main library filters now use a unified dropdown architecture (same behavior on desktop/mobile) for:
- **Folders**
- **Resolution**
- **Audio languages**
- **Video codecs**
- **Audio codecs**
- **Streaming providers**
- **Score** (dual-handle slider, only when scoring is enabled)

Shared capabilities:
- multi-selection
- per-filter **Include / Exclude** mode
- **Select all** action
- dynamic counts (faceted logic: computed against other active filters)
- descending sort by item count
- zero-count options hidden
- active options kept visible even when count reaches 0
- filter state persisted and restored after reload

> The **Type** filter (All / Movies / Series) remains a dedicated quick control.

### User example

1. Open **Audio languages**.
2. Select `French` + `English` (multi-select).
3. Switch to **Exclude** mode to remove these languages from results.
4. Use **Select all** to toggle all currently visible options.
5. Notice options are automatically sorted by current matching volume.

---

## 10. Streaming providers

Streaming enrichment is optional and relies on **Seerr**.

### Configuration

URL + API key in settings (Seerr tab) or during onboarding. A "Test connection" button validates the credentials.

### Current model

- Each media item stores a flat list of raw providers in `library.json` (`item.providers`).
- The app then applies a mapping to compute displayed providers.
- If a raw provider is unmapped (or mapped to `null`), it is grouped under **Autres**.
- If a media item has no providers, the UI shows **No provider** (dedicated behavior kept).

### `providers_mapping.json` (key file)

- Runtime mapping used by the app is `/data/providers_mapping.json`.
- On first startup, it is initialized from the bundled mapping file.
- After that, it is **never auto-overwritten**.
- After providers enrichment, newly detected raw providers are appended with `null`.

Example:

```json
{
  "Netflix": "Netflix",
  "Netflix Standard with Ads": "Netflix",
  "Premiere Max": null
}
```

Interpretation:
- non-`null` mapping → displayed provider
- `null` mapping → grouped into `Autres`

> Important: for a provider to appear in the selectable provider list in settings, it must have a **non-null** mapping in `providers_mapping.json`.
> If a provider is set to `null`, it is grouped into `Autres` and is not individually selectable.

### Provider logos

- Logos are defined in `providers_logo.json`.
- Logo lookup is done on the **final displayed provider** (after mapping).
- If no logo is found, fallback uses the **Autres** logo.
- **No provider** keeps its dedicated icon (red blocked circle).

### Customize displayed providers

1. Open `/data/providers_mapping.json`.
2. Edit mappings.
3. Reload the app (or restart the container if needed).

Example:

```json
{
  "Canal VOD": "Canal+",
  "OCS": "OCS",
  "Rakuten TV": null
}
```

Result:
- `Canal VOD` → displayed as `Canal+`
- `OCS` → displayed as `OCS`
- `Rakuten TV` → grouped into `Autres`

---

## 11. Quality Scoring

### Principle

Quality scoring is a global score **from 0 to 100**.
It combines 4 components: **video**, **audio**, **languages**, and **size**.

### Optional feature

The quality score is a **bonus feature**, **disabled by default**.
You can enable it anytime if you want a more advanced analysis of your library.

### Activation

Enable it in **Settings > Configuration** using the **Enable quality score** toggle.

### Configuration

Detailed configuration is available in **Settings > Score**:
- weights
- video rules
- audio rules
- language rules
- size rules (movies / series)

### Default values

Ready-to-use default values are provided out of the box.
You can customize everything and go back to defaults anytime using **Reset**.

### Runtime behavior

Scores are computed during scans when the feature is enabled.
After changing score settings, the backend runs a **targeted score recomputation** without a full library rescan.

### Philosophy

The scoring system is designed to stay flexible and fully customizable.
You can adapt it to your preferences while keeping robust behavior with incomplete metadata (default fallback values are used).
Technical inconsistencies are no longer handled with score malus and can be surfaced later through dedicated recommendations.

### Score filter (0–100 slider, when enabled)

The score filter is not a dropdown anymore: it is a **dual-handle slider** with two bounds:
- `min`
- `max`

Filtering rule:

```text
score >= min && score <= max
```

The slider updates displayed values in real-time while dragging, then applies filtering when released (smooth UX without expensive continuous re-filtering).

### Items without score

Dedicated option: **Include items without score**.

Behavior:
- enabled by default (range 0–100)
- automatically disabled when the range is narrowed from default
- can be manually re-enabled at any time

### Score colors (visual consistency)

Score colors follow a consistent gradient across the app:

```text
red → orange → yellow → light green → dark green
```

Used for:
- score badges
- slider visual markers
- consistent quality-level visuals in stats/UI

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

### Final score

```text
Final Score = Component sum
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

### Full score disable (`score.enabled`)

The `score.enabled` setting in `config.json` can disable the feature entirely.

When disabled:
- backend scan fully bypasses quality score computation
- score fields are removed from `library.json` (no mixed score/no-score dataset after a scan)
- score UI is hidden (badges, score column, score tooltip)
- score filter slider is hidden
- score-based sorting and score statistics are disabled
- score columns are excluded from CSV export

When re-enabled:
- score UI controls become available again immediately
- a new scan is required to regenerate score data in `library.json`

### Key behaviors

- filters persist and restore after reload
- zero-count options are hidden (except active ones)
- empty filter sections are automatically hidden
- option order updates dynamically by counts
- UI reacts immediately to configuration changes (for example score OFF)

### Stats

Statistics include score distribution views to provide a global quality analysis of the library.

---

## 12. Statistics

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

## 13. Settings

Accessible via the ⚙️ icon at the bottom of the sidebar.

### Library tab

- Library path (`LIBRARY_PATH`, read-only if set via compose.yaml)
- Show/hide Movies or Series
- Table of detected folders: type (Movies/Series/Ignore) + individual visibility

### Seerr tab

- Enable/disable enrichment
- URL + API key + connection test
- Visibility for displayed providers (mapped providers; `Autres` is handled automatically)

### System tab

- Language (FR/EN)
- Accent color (picker + reset)
- Synopsis on hover (on/off, **disabled by default**)
- Quality score (on/off, **disabled by default**)
- Raw inventory `library_inventory.json` (on/off, **disabled by default**)
- Auto-scan (cron)
- Log level
- Version

> Synopsis on hover, quality scoring, and raw inventory are advanced features: they are opt-in and must be enabled manually in settings.

---
