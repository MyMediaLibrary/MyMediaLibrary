# Documentation — MyMediaLibrary (EN)

## Table of contents

1. [Overview](#1-overview)
2. [Technical architecture](#2-technical-architecture)
3. [Installation](#3-installation)
4. [Library structure](#4-library-structure)
5. [Onboarding](#5-onboarding)
6. [Scanner](#6-scanner)
7. [Item format](#7-item-format)
8. [Web interface](#8-web-interface)
9. [Filters](#9-filters)
10. [Streaming providers](#10-streaming-providers)
11. [Quality Scoring](#11-quality-scoring)
12. [Recommendations](#12-recommendations)
13. [Statistics](#13-statistics)
14. [Settings](#14-settings)

---

## 1. Overview

**MyMediaLibrary** is a self-hosted dashboard to visualize a movie and TV show library. It runs in a single Docker container backed by an SQLite database.

**Flow:**
1. The Python scanner reads subdirectories of `/library`, parses `.nfo` files (Kodi/Jellyfin/Emby format), and probes video files with ffprobe to collect accurate technical metadata.
2. Optional enrichment phases add streaming provider data (Seerr), quality scores, inventory tracking, and recommendations.
3. The web interface reads from REST API endpoints (`/api/library`, `/api/recommendations`, etc.) and renders the library, filters, statistics, and recommendations.

---

## 2. Technical architecture

### Stack

- **Container**: nginx:alpine + Python 3 + dcron (single image)
- **Frontend**: HTML/CSS + vanilla JS (no framework)
- **Backend**: minimal Python server (`backend/scanner.py`) — REST API routes + static file serving
- **Scanner**: Python (`backend/scanner.py`) — `.nfo` parsing, metadata computation, SQLite persistence
- **Persistence**: SQLite in `data/mymedialibrary.db`, `data/.secrets` for secrets outside the DB, `localStorage` (UI state)

### Internationalisation

Files `app/i18n/fr.json` and `app/i18n/en.json`. Function `t('namespace.key')` with `{n}` substitution and `{s}` plural support. Language is persisted in SQLite server-side and in `localStorage` client-side.

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
      - ./data:/data                        # SQLite DB, scanner.log, .secrets
      - /path/to/your/library:/library:ro   # your media library, read-only
    environment:
      TZ: Europe/Paris
    restart: unless-stopped
```

### Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `TZ` | ❌ | `UTC` | Container timezone (logs and timestamps) |

Always mount your media to `/library` read-only. Password authentication is configured during onboarding and later in **Settings > Configuration**; only a hash is stored in `/data/.secrets`. Auto-scan schedule and log level are configured in **Settings > System** and persisted in SQLite.

### Runtime storage

- `/data` contains the SQLite database `mymedialibrary.db`, `scanner.log`, and `.secrets`.
- `/library` is the fixed media mount point.
- `/tmp` is internal to the container and contains `scan.lock`.

### Updating

```bash
docker compose pull && docker compose up -d
```

---

## 4. Library structure

The scanner reads the **direct subdirectories** of `/library`. Each subdirectory is a **folder** that you assign a type to (Movies, Series, Ignore) from the interface.

### Recommended structure

```
/library/                    ← fixed media root
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
```

---

## 5. Onboarding

The setup wizard appears on first launch when the SQLite configuration is empty.

**Steps:**

1. **Welcome screen** — app description, language selection, "Get started" button
2. **Folders** — lists subdirectories of `/library`, assign a type to each (Movies / Series / Ignore). Unconfigured folders are skipped during scan. The "Next" button is disabled until at least 1 folder is configured.
3. **Seerr** (optional) — URL + API key, connection test button
4. **Summary + Scan** — shows the configuration, "Launch scan" button that starts the initial scan and redirects to the library when done

---

## 6. Scanner

The scanner is the core component of MyMediaLibrary. It reads the filesystem, parses `.nfo` files, and persists all data to SQLite.

### Overview

The scanner (`scanner.py`) analyses the content of `/library` and writes results to `data/mymedialibrary.db`:

| SQLite table | Content |
|---|---|
| `media`, `seasons`, `episodes`, `files`, `streams` | Library items with all metadata |
| `inventory_items` | Media presence/absence tracking (optional, enable in Settings > System) |
| `recommendations` | Generated recommendations (optional, requires quality scoring) |
| `ffprobe_cache` | Technical probe results cache |

### Dynamic scan pipeline

MyMediaLibrary uses a dynamic scan pipeline composed of sequential phases. Only the phases related to enabled features are executed.

1. **Phase 1 — Filesystem + NFO**: always executed. It analyzes media folders and parses `.nfo` files.
2. **Phase 1B — FFprobe**: executed when ffprobe analysis is enabled. It makes technical metadata more reliable by reading media files directly.
3. **Phase 2 — Seerr enrichment**: executed when Seerr is configured and enabled. It fetches streaming providers and additional metadata.
4. **Phase 3 — Scoring**: executed when quality scoring is enabled.
5. **Phase 4 — Inventory**: executed when inventory is enabled.
6. **Phase 5 — Recommendations**: executed when recommendations are enabled.

> Phases are sequential and independent — each produces output consumed by later phases.

### NFO parsing

NFO files (Kodi/Jellyfin/Emby format) are the primary metadata source. The scanner extracts:
- Title, year, synopsis, runtime
- Resolution, video codec, audio codec, HDR, audio channels, audio languages, subtitle languages, video bitrate, genres

Behavior by type:
- **Movies**: all fields read directly from the movie NFO
- **Series**: technical fields read at episode level, then aggregated to season and series; genres read from `tvshow.nfo`

Genres are normalized through a bundled mapping file.

### Technical media probing (ffprobe)

When NFO data is missing or incomplete, the scanner probes the video file directly with **ffprobe** to extract accurate technical metadata: resolution, video and audio codecs, audio channels, audio languages, video bitrate, and HDR type.

ffprobe results are cached between scans so unchanged files are never re-probed.

### Scan triggers

| Origin | How |
|---|---|
| Container startup | Automatic via `entrypoint.sh` |
| Onboarding wizard | "Launch scan" button at the end of onboarding |
| "Scan" button in the UI | Via the Scanner page |
| Cron | Automatic schedule (Settings > System) |
| Folder configuration change | Automatic after saving in Settings > Library |

### Anti-concurrency lock

Only one scan can run at a time. The scanner uses an inter-process file lock (`/tmp/scan.lock`) to coordinate all trigger origins (startup, cron, UI). `/tmp` stays internal to the container and should not be mounted.

If a scan is already running:
- A UI-triggered scan receives an error response (HTTP 409)
- A scheduled scan (cron or startup) is silently skipped with a log message

### Logs

Logs are available in `data/scanner.log` (host path) and viewable in Settings > System.

| Level | Content |
|---|---|
| `INFO` | Phase progression, per-folder progress, durations, detected statistics (video/audio codecs, languages, resolutions) |
| `DEBUG` | Technical details: Seerr results per item, NFO parsing, not-found items, inventory details |

### Data preservation between phases

The pipeline preserves existing data until an enabled phase replaces it. This lets the filesystem/NFO phase keep previous enrichments when the related features are not executed:

| Field | Source | Behavior |
|---|---|---|
| `providers` | Phase 2 (Seerr) | Carried forward from the previous scan |
| `providers_fetched` | Phase 2 | Carried forward from the previous scan |
| `quality` | Phase 3 (scoring) | Carried forward from the previous scan |

Enriched data is loaded from SQLite at pipeline startup. New items with no previous entry are created without enrichment — their data will be computed when the related phases are enabled.

---

## 7. Item format

The `/api/library` endpoint returns items in the following structure:

```json
{
  "scanned_at": "2025-04-14T20:00:00.000000",
  "total_items": 3289,
  "items": [ ... ]
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
  "audio_channels": "5.1",
  "audio_languages": ["fra", "eng"],
  "subtitle_languages": ["fra", "eng"],
  "video_bitrate": 18450000,
  "genres": ["Action", "Crime"],
  "providers": ["Netflix", "Canal+"],
  "quality": {
    "video_details": { "resolution": 20, "codec": 15, "hdr": 0 },
    "audio_details": { "codec": 18, "channels": 8 },
    "video": 35,
    "audio": 26,
    "languages": 15,
    "size": 8,
    "score": 75
  }
}
```

The `id` field is the stable key for each item. Format: `{type}:{category}:{folder_name}`.

### Inventory tracking

When the inventory feature is enabled (Settings > System), the scanner tracks the presence history of each item across successive scans:

| Field | Description |
|---|---|
| `status` | `"present"` or `"missing"` |
| `first_seen_at` | Date first detected on filesystem (never updated afterwards) |
| `last_seen_at` | Last date the item was found on the filesystem |
| `last_checked_at` | Date of the last scan that evaluated this item (updated even when missing) |

An item becomes `"missing"` when its folder is no longer detected during a pipeline run with inventory enabled. History is preserved and the item is not deleted.

---

## 8. Web interface

### Views

- **Library** — card grid (poster, title, year, resolution, codec, providers) + table view
- **Statistics** — detailed charts
- **Recommendations** — suggested actions to improve the library (when enabled)
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
- **Type**
- **By folder**
- **Genre**
- **Streaming (FR)**
- **Audio language**
- **Score** (dual-handle slider, only when scoring is enabled)
- **Technical quality** (collapsible group):
  - **Resolution**
  - **Video codec**
  - **Audio codec**
  - **Audio channels**

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

- Each media item stores a flat list of raw providers returned by Seerr.
- The app applies a mapping to compute displayed providers.
- If a raw provider is unmapped (or mapped to `null`), it is grouped under **Autres**.
- If a media item has no providers, the UI shows **No provider** (dedicated behavior kept).

### Provider mapping

- Runtime mapping used by the app is stored in SQLite.
- On first startup, the table is initialized from bundled defaults.
- After that, DB customizations are **never auto-overwritten**.
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

> Important: for a provider to appear in the selectable provider list in settings, it must have a **non-null** mapping in DB.
> If a provider is set to `null`, it is grouped into `Autres` and is not individually selectable.

### Provider logos

- Runtime provider logos are stored in SQLite and seeded from bundled defaults.
- Logo lookup is done on the **final displayed provider** (after mapping).
- If no logo is found, fallback uses the **Autres** logo.
- **No provider** keeps its dedicated icon (red blocked circle).

### Customize displayed providers

1. Edit the mapping from the UI or through a future controlled migration/import.
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
After changing score settings, the backend runs a **targeted score recomputation** without rescanning the media library.

### Philosophy

The scoring system is designed to stay flexible and fully customizable.
You can adapt it to your preferences while keeping robust behavior with incomplete metadata (default fallback values are used).
Technical inconsistencies are no longer handled with score malus and are surfaced through dedicated recommendations.

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
| Audio | 30 |
| Languages | 15 |
| Size | 15 |
| **Raw total** | **110** |

Audio scoring is now composed of:
- `audio_codec_score`
- `audio_channels_score`

Then:

```text
audio_score = audio_codec_score + audio_channels_score
```

The existing final global normalization logic remains unchanged.

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

#### 🔊 Audio (30)

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

| Audio channels | Points |
|---|---:|
| 7.1 | 10 |
| 5.1 | 8 |
| 2.0 | 5 |
| 1.0 | 3 |
| Unknown | 2 |

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

The `score.enabled` setting stored in SQLite can disable the feature entirely.

When disabled:
- backend scan fully bypasses quality score computation
- score fields are cleared (no mixed score/no-score dataset after a scan)
- score UI is hidden (badges, score column, score tooltip)
- score filter slider is hidden
- score-based sorting and score statistics are disabled
- score columns are excluded from CSV export

When re-enabled:
- score UI controls become available again immediately
- a new scan is required to regenerate scores

### Key behaviors

- filters persist and restore after reload
- zero-count options are hidden (except active ones)
- empty filter sections are automatically hidden
- option order updates dynamically by counts
- UI reacts immediately to configuration changes (for example score OFF)

### Stats

Statistics include score distribution views to provide a global quality analysis of the library.

---

## 12. Recommendations

Recommendations turn library analysis into concrete actions: improve quality, optimize disk usage, detect data issues, or identify inconsistent seasons.

### Activation

- Requires **quality scoring**.
- Enable it in **Settings > Configuration**.
- If quality scoring is disabled, recommendations are automatically disabled.

### Runtime behavior

- Recommendations are generated during **scan phase 5** (requires quality scoring enabled).
- Each recommendation is linked to a media item via its stable identifier.

### Engine

- Deterministic rules, no generative AI.
- Simple business rules configurable and stored in SQLite.
- Backend structural rules for missing data and series inconsistencies.

### Structure

Each recommendation contains:
- the related media item
- type
- priority
- message
- suggested action

### Recommendation types

#### Quality

Flags low scores, legacy codecs, or limited audio tracks.

#### Space saving

Identifies oversized files, high bitrates, or inefficient encodes. Displayed size is affected size, not guaranteed savings.

#### Languages

Detects missing French audio, original-version-only media, or missing French subtitles.

#### Series

Finds inconsistent seasons: resolution, codec, audio, languages, lower score, or unusually high size.

#### Data

Surfaces missing, unknown, or undetected fields (resolution, codecs, languages, size, score).

### Recommendations Page

The dedicated page provides:
- local filters by **type** and **priority**
- configurable sorting
- compact media information
- readable mobile cards
- CSV export of visible recommendations

Global library filters also apply to recommendations.

### Recommendations Statistics

The **Stats > Recommendations** tab shows:
- distribution by priority
- distribution by type
- folder analysis
- recommendations-per-media distribution
- score distribution
- size affected by space recommendations

Charts update according to global filters and local recommendation filters.

---

## 13. Statistics

The Statistics page is split into subtabs:

- **General**
  - Folders
  - Genres (horizontal bars)
  - Providers
  - Quality
  - Release years distribution (full width)
- **Technical**
  - Resolution
  - Video codec
  - Audio codec
  - Audio languages
  - Audio channels
- **Evolution**
  - Monthly additions timeline (full width)
- **Recommendations** (if score + recommendations are enabled)
  - Distribution by priority and type
  - Folder analysis
  - Media with recommendations by folder
  - Recommendations per media
  - Score distribution

Genre chart specifics:
- displayed in **item counts**
- **Top 12** + **Others**
- `Others` is based on items not covered by the Top 12 (not a raw sum of out-of-top genre occurrences)

All charts are filtered by the active library filters.

---

## 14. Settings

Accessible via the ⚙️ icon at the bottom of the sidebar.

### Library tab

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
- Recommendations (on/off, requires quality score, **disabled by default**)
- Presence inventory (on/off, **disabled by default**)
- Auto-scan (cron)
- Log level
- Version

> Synopsis on hover, quality scoring, and presence inventory are advanced features: they are opt-in and must be enabled manually in settings.

---
