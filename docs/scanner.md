# Scanner — Technical Reference

This document describes the internals of the MyMediaLibrary scanner: how it works, what it produces, how to interpret its logs, and the exact format of the JSON files it generates.

---

## Table of contents

1. [Overview](#1-overview)
2. [Scan modes](#2-scan-modes)
3. [Scan triggers](#3-scan-triggers)
4. [Phase pipeline (full scan)](#4-phase-pipeline-full-scan)
5. [Quick scan — enrichment preservation](#5-quick-scan--enrichment-preservation)
6. [Anti-concurrency lock](#6-anti-concurrency-lock)
7. [Logs](#7-logs)
8. [library.json format](#8-libraryjson-format)
9. [library_inventory.json format](#9-library_inventoryjson-format)

---

## 1. Overview

The scanner is a single Python file: `conf/scanner.py`.

It reads the filesystem under `LIBRARY_PATH`, parses `.nfo` metadata files, and produces two output files:

| File | Purpose |
|---|---|
| `/data/library.json` | Main index consumed by the web UI |
| `/data/library_inventory.json` | Raw presence/absence tracking (optional, opt-in) |

The scanner runs as a separate process and communicates with the HTTP server only through these files and the API.

---

## 2. Scan modes

There are exactly two scan modes:

### `--quick`

Runs **Phase 1 only** (filesystem + NFO).

- Scans configured folders, parses `.nfo` files
- Writes `library.json` incrementally after each folder
- Preserves enriched fields from the previous `library.json` (providers, quality)
- **No** Jellyseerr calls
- **No** scoring computation
- **No** inventory update

Use when: folder contents changed, new items added, quick refresh needed.

### `--full` (default)

Runs **all 4 phases** in sequence.

- Phase 1: filesystem + NFO
- Phase 2: Jellyseerr provider enrichment (force re-fetch all)
- Phase 3: quality scoring
- Phase 4: inventory update

Use when: first scan, providers need refreshing, scoring needed.

> **Default**: running `scanner.py` with no flag is equivalent to `--full`.

---

## 3. Scan triggers

| Origin | Mode | How |
|---|---|---|
| Container startup | `--quick` | `entrypoint.sh` → `python3 scanner.py --quick --origin startup` |
| Onboarding wizard | `quick` | UI calls `POST /api/scan/start` with `{"mode": "quick"}` |
| UI "Scan" button | `full` | UI calls `POST /api/scan/start` with `{"mode": "full"}` |
| Cron | `--full` | `scan_cron.sh` → `python3 scanner.py --full --origin cron` |
| Settings — folder change | `quick` | `POST /api/config` auto-triggers `quick` scan if `"folders"` key is in payload and no scan is currently running |

The `--origin` flag (`manual` / `startup` / `cron`) is used only for log messages and has no effect on behavior.

---

## 4. Phase pipeline (full scan)

```
┌─────────────────────────────────────────────────────────────────────┐
│ Full scan                                                           │
│                                                                     │
│  Phase 1: filesystem + NFO ──► writes library.json (per folder)    │
│  Phase 2: Jellyseerr        ──► writes library.json (per folder)    │
│  Phase 3: scoring           ──► writes library.json (per folder)    │
│  Phase 4: inventory         ──► writes library_inventory.json       │
│                                  (per folder + final pass)         │
└─────────────────────────────────────────────────────────────────────┘
```

Each phase reads the output of the previous phase from disk. Phases are fully separated — no phase calls another phase's logic inline.

### Phase 1 — Filesystem + NFO (`run_quick`)

- Loads existing `library.json` once into memory (snapshot)
- For each configured folder (type = `movie` or `tv`):
  - Iterates subdirectories
  - Parses `.nfo` files for title, year, codec, resolution, audio, etc.
  - Carries forward enriched fields from the snapshot (`providers`, `quality`)
  - Writes `library.json` immediately after each folder
- Folders without a configured type are skipped silently

### Phase 2 — Jellyseerr enrichment (`run_enrich`)

- Reads `library.json`
- For each item with a `tmdb_id`, calls the Jellyseerr API to fetch FR streaming providers
- Items without `tmdb_id` are skipped automatically
- Writes `library.json` after each folder
- Provider logos and names are normalized via `providers.json`

### Phase 3 — Scoring (`run_scoring`)

- Reads `library.json`
- Computes a quality score (0–100) for each item based on resolution, codec, audio, languages, size
- Only runs when `system.enable_score = true` in `config.json`; otherwise logs a skip and exits
- Writes `library.json` after each folder

### Phase 4 — Inventory (`run_inventory`)

- Reads `library.json` and the existing `library_inventory.json`
- Only runs when `system.inventory_enabled = true`; otherwise logs a skip and exits
- For each configured folder: builds inventory items from the filesystem
- Writes `library_inventory.json` after each folder (partial merge)
- Final pass: full merge + missing reconciliation + `last_checked_at` stamping + final write

---

## 5. Quick scan — enrichment preservation

A key design invariant of the quick scan: **enriched data accumulated by previous full scans is never discarded**.

### How it works

At the start of `run_quick`:
1. The existing `library.json` is loaded **once** into a dict keyed by `path`
2. This in-memory snapshot is the sole reference for all `prev` lookups during the scan
3. Incremental writes after each folder do **not** modify this snapshot

For each media item scanned:
- A new item is built from the filesystem and `.nfo`
- The corresponding `prev` entry (from the snapshot) is looked up by `path`
- The following fields are copied from `prev` into the new item:

| Field | Source | Description |
|---|---|---|
| `providers` | Phase 2 | Normalized provider list |
| `providers_fetched` | Phase 2 | Whether Jellyseerr was queried |
| `quality` | Phase 3 | Score object `{score, level, ...}` |
| `poster`, `tmdb_id`, `plot`, `runtime`, `resolution`, `codec`, audio fields | Phase 1/2 | Preserved as fallback when NFO is absent or incomplete |

### What happens to removed items

Items from a folder that is no longer configured are simply not scanned — they are absent from the new `library.json`. No explicit deletion step is needed.

### New items

New items that have no entry in the snapshot are built fresh with no enrichment. `providers` defaults to `[]`, `providers_fetched` to `false`, `quality` to `null`. These fields are populated on the next full scan.

---

## 6. Anti-concurrency lock

### Problem

At container startup, three processes can run concurrently:
- The scan API server (`scanner.py --serve`)
- The startup scan (`scanner.py --quick`)
- A potential UI-triggered scan or cron scan

Without coordination, two scans writing `library.json` simultaneously produce a corrupted file (JSON parse error `Extra data`).

### Solution

An **inter-process file lock** using `fcntl.flock` on `/data/.scan.lock`.

- Exclusive (`LOCK_EX | LOCK_NB`): only one holder at a time
- Non-blocking: if the lock is already held, the attempt fails immediately
- Visible across all processes on the host (shared file descriptor on the same OS)
- Released via `try/finally` — always, on success or exception

### Behavior per origin

| Origin | Lock held by another process | Behavior |
|---|---|---|
| Startup | No | Acquires lock, runs quick scan |
| Startup | Yes | Logs `Startup scan skipped — another scan is already running`, exits 1 |
| Cron | No | Acquires lock, runs full scan |
| Cron | Yes | Logs `Cron scan skipped — another scan is already running`, exits 1 |
| API / UI | No | `_is_scan_locked()` = false → subprocess launched, subprocess acquires lock |
| API / UI | Yes | Returns HTTP 409 `scan already running` |

### Log markers

```
[SCAN] Scan lock acquired — mode=quick
[SCAN] Scan lock acquired — mode=full
[SCAN] Scan lock released
[SCAN] Startup scan skipped — another scan is already running
[SCAN] Cron scan skipped — another scan is already running
[SCAN] Scan already running — refusing new scan request
```

---

## 7. Logs

### Philosophy

| Level | Content |
|---|---|
| `INFO` | Progression, phase markers, per-folder progress, summaries, durations |
| `DEBUG` | Unit-level detail, diagnostics, verbose lists |

### INFO log examples

```
[SCAN] ═══════════════════════════════════
[SCAN] Starting scan --full
[SCAN] ═══════════════════════════════════
[SCAN] Scan lock acquired — mode=full

[SCAN] ── Phase 1 : filesystem + NFO ──────────────
[SCAN] 5 configured folder(s): animation, movies, series, documentaries, concerts
[SCAN] Processing folder [movies] (1/5) — type=movie
[SCAN] Folder [movies] done — 1423 item(s) found
...
[SCAN] Audio codecs detected: 9
[SCAN] Audio languages detected: 24
[SCAN] Video codecs detected: 6
[SCAN] Resolutions detected: 4
[SCAN] Phase 1 completed in 28.3s — 3289 item(s) total (4.5 MB)

[SCAN] ── Phase 2 : Jellyseerr enrichment (force) ──
[SCAN] Jellyseerr enrichment: 3102 items to process, 187 skipped (8 workers)
[SCAN] Enriching folder [movies] (1/5) — 1423 item(s)
[SCAN] Folder [movies] done — 1423 item(s) enriched
...
[SCAN] Phase 2 completed in 47.1s — 3289 OK

[SCAN] ── Phase 3 : scoring ──────────────────────────────
[SCAN] Scoring folder [movies] (1/5) — 1423 item(s)
[SCAN] Folder [movies] scored
...
[SCAN] Phase 3 completed — 3289 item(s) scored in 1.8s

[SCAN] ── Phase 4 : inventory ─────────────────────────────
[SCAN] Inventory: processing folder [movies] (1/5) — type=movie
[SCAN] Inventory: folder [movies] done — 1423 item(s)
...
[SCAN] Inventory: no missing items
[SCAN] Phase 4 completed in 3.4s — 3289 present, 0 missing

[SCAN] Scan lock released
[SCAN] ═══════════════════════════════════
[SCAN] Scan completed in 80.6s
[SCAN] ═══════════════════════════════════
```

### DEBUG log examples

```
Written: /data/library.json
[SCAN] Skipping folder [books] — no type configured
[jellyseerr] Item not found for /movie/12345 (not in Jellyseerr/TMDB)
[SCAN] Partially parsed audio language value: 'freijoeng' in item '...' -> ...
[SCAN] Unrecognized audio language value: 'xyz' in item '...' — skipped
[SCAN] Audio codecs detail: HEVC×1823 / H.264×1201 / AAC×265
[SCAN] Audio languages detail: fra×3100 / eng×2800 / ...
[SCAN] Video codecs detail: HEVC×2100 / H.264×1100 / ...
[SCAN] Resolutions detail: 1080p×1800 / 4K×900 / 720p×400 / SD×189
[SCAN] Inventory missing: Film A, Film B … (+3 more)
```

---

## 8. `library.json` format

This file is the main data source for the web UI.

### Top-level structure

```json
{
  "scanned_at": "2025-04-14T20:00:00.000000",
  "library_path": "/mnt/media/library",
  "total_items": 3289,
  "categories": ["Animation", "Movies", "Series"],
  "items": [ ... ],
  "providers_meta": { "Netflix": { "logo": null, "logo_url": "https://..." } },
  "providers_raw_meta": { "Netflix FR": { "logo": null, "logo_url": "..." } },
  "providers_raw": ["Netflix FR", "Canal+"],
  "config": { "library_path": "/mnt/media/library" },
  "meta": { "score_enabled": true }
}
```

### Item structure

```json
{
  "id": "movie:Movies:The.Dark.Knight.2008",
  "path": "Movies/The.Dark.Knight.2008",
  "title": "The Dark Knight",
  "raw": "The.Dark.Knight.2008",
  "year": "2008",
  "category": "Movies",
  "type": "movie",
  "size_b": 15032385536,
  "size": "14.0 GB",
  "file_count": 3,
  "added_at": "2023-11-12T10:30:00",
  "added_ts": 1699784200,
  "poster": "/posters/Movies/The.Dark.Knight.2008/poster.jpg",
  "tmdb_id": "155",
  "resolution": "1080p",
  "width": 1920,
  "height": 1080,
  "plot": "When the menace known as the Joker…",
  "runtime": "152 min",
  "runtime_min": 152,
  "season_count": null,
  "episode_count": null,
  "codec": "HEVC",
  "audio_codec_raw": "truehd",
  "audio_codec": "TRUEHD",
  "audio_codec_display": "TrueHD",
  "audio_languages": ["fra", "eng"],
  "audio_languages_simple": "MULTI",
  "hdr": true,
  "hdr_type": "HDR10",
  "providers": ["Netflix", "Canal+"],
  "providers_fetched": true,
  "quality": {
    "score": 87,
    "level": 5,
    "video": 45,
    "audio": 20,
    "languages": 15,
    "size": 15,
    "penalties": []
  }
}
```

### Field reference

| Field | Type | Source | Description |
|---|---|---|---|
| `id` | string | Phase 1 | Stable identifier shared with `library_inventory.json`. Format: `"{type}:{category}:{folder_name}"`. Always the first field. |
| `path` | string | Phase 1 | Relative path from `LIBRARY_PATH` |
| `title` | string | NFO or folder name | Display title |
| `raw` | string | Filesystem | Raw folder name |
| `year` | string\|null | NFO or folder name | Release year |
| `category` | string | Config | Display name of the configured folder |
| `type` | string | Config | `"movie"` or `"tv"` |
| `size_b` | int | Filesystem | Total size in bytes |
| `size` | string | Phase 1 | Human-readable size |
| `file_count` | int | Filesystem | Number of media files |
| `added_at` | string | Filesystem mtime | ISO timestamp of the folder's last modification |
| `added_ts` | int | Filesystem mtime | Unix timestamp of same |
| `poster` | string\|null | NFO or filesystem | Poster URL or path |
| `tmdb_id` | string\|null | NFO | TMDB ID, required for Jellyseerr enrichment |
| `resolution` | string\|null | NFO | e.g. `"1080p"`, `"4K"` |
| `codec` | string\|null | NFO | Video codec, e.g. `"HEVC"`, `"H.264"` |
| `audio_codec` | string | NFO | Normalized audio codec |
| `audio_languages` | list | NFO | ISO 639-2 codes, e.g. `["fra", "eng"]` |
| `audio_languages_simple` | string | Phase 1 | `"VF"`, `"VO"`, `"MULTI"`, `"UNKNOWN"` |
| `hdr` | bool | NFO | Whether HDR is detected |
| `hdr_type` | string\|null | NFO | `"HDR10"`, `"HDR10+"`, `"Dolby Vision"`, `"HLG"`, etc. |
| `providers` | list | Phase 2 | Normalized provider names |
| `providers_fetched` | bool | Phase 2 | Whether Jellyseerr was queried |
| `quality` | object\|null | Phase 3 | Score object. `null` if scoring is disabled or a quick scan hasn't been followed by a full scan. |
| `season_count` | int\|null | NFO | Series only |
| `episode_count` | int\|null | NFO | Series only |

### ID format

```
{type}:{category}:{folder_name}
```

Examples:
- `movie:Movies:The.Dark.Knight.2008`
- `tv:Series:Breaking.Bad`
- `movie:Animation:Spirited.Away.2001`

The ID is **identical** in `library.json` and `library_inventory.json` for the same media item. It is stable as long as the folder name and the category name do not change.

---

## 9. `library_inventory.json` format

This file tracks the presence/absence history of media items and their files. It is **opt-in** (requires `system.inventory_enabled = true`).

### Top-level structure

```json
{
  "version": 1,
  "generated_at": "2025-04-14T20:00:00Z",
  "scan_mode": "full",
  "missing_reconciliation": true,
  "items": [ ... ]
}
```

| Field | Description |
|---|---|
| `version` | Schema version (currently `1`) |
| `generated_at` | UTC ISO timestamp of this scan run |
| `scan_mode` | `"full"` or `"quick"` |
| `missing_reconciliation` | `true` only when a full scan ran over all folders without `--category` filter |

### Item structure (movie)

```json
{
  "id": "movie:Movies:The.Dark.Knight.2008",
  "media_type": "movie",
  "category": "Movies",
  "title": "The Dark Knight",
  "root_folder_path": "/mnt/media/library/Movies/The.Dark.Knight.2008",
  "status": "present",
  "first_seen_at": "2024-01-15T12:00:00Z",
  "last_seen_at": "2025-04-14T20:00:00Z",
  "last_checked_at": "2025-04-14T20:00:00Z",
  "video_files": [
    {
      "name": "The.Dark.Knight.2008.mkv",
      "status": "present",
      "first_seen_at": "2024-01-15T12:00:00Z",
      "last_seen_at": "2025-04-14T20:00:00Z",
      "last_checked_at": "2025-04-14T20:00:00Z"
    }
  ]
}
```

### Item structure (TV show)

```json
{
  "id": "tv:Series:Breaking.Bad",
  "media_type": "tv",
  "category": "Series",
  "title": "Breaking Bad",
  "root_folder_path": "/mnt/media/library/Series/Breaking.Bad",
  "status": "present",
  "first_seen_at": "2023-06-01T08:00:00Z",
  "last_seen_at": "2025-04-14T20:00:00Z",
  "last_checked_at": "2025-04-14T20:00:00Z",
  "video_files": [],
  "subfolders": [
    {
      "name": "Season 01",
      "status": "present",
      "first_seen_at": "2023-06-01T08:00:00Z",
      "last_seen_at": "2025-04-14T20:00:00Z",
      "last_checked_at": "2025-04-14T20:00:00Z",
      "video_files": [
        {
          "name": "Breaking.Bad.S01E01.mkv",
          "status": "present",
          "first_seen_at": "2023-06-01T08:00:00Z",
          "last_seen_at": "2025-04-14T20:00:00Z",
          "last_checked_at": "2025-04-14T20:00:00Z"
        }
      ]
    }
  ]
}
```

### Field reference

| Field | Level | Description |
|---|---|---|
| `id` | item | Same format as `library.json`. Shared identifier for cross-file matching. |
| `media_type` | item | `"movie"` or `"tv"` |
| `category` | item | Display name of the configured folder |
| `title` | item | Title from `library.json` |
| `root_folder_path` | item | Absolute filesystem path |
| `status` | item, subfolder, file | `"present"` or `"missing"` |
| `first_seen_at` | item, subfolder, file | UTC ISO. Set on first encounter, **never updated** subsequently. |
| `last_seen_at` | item, subfolder, file | UTC ISO. Updated each time the item is seen by a scan. Unchanged when `status = missing`. |
| `last_checked_at` | item, subfolder, file | UTC ISO. Updated on **every scan**, regardless of presence/absence. Reflects when the item was last evaluated. |

### Timestamp semantics

```
present → last_seen_at = now, last_checked_at = now
missing → last_seen_at unchanged, last_checked_at = now
```

`last_checked_at` always equals the timestamp of the scan run that produced the document. It is applied uniformly to all items (present and missing) via a final pass at the end of Phase 4.

### Missing reconciliation

During a full scan (all folders, no `--category` filter), `missing_reconciliation = true` is set and items not seen in the scan are marked `status: missing` rather than deleted. This allows tracking items that disappear from the filesystem while preserving their history.

During a quick scan or a partial scan (`--category`), `missing_reconciliation = false` — only items that were actively scanned have their status updated; others retain their previous state from the inventory merge.

### Field ordering (JSON)

Python preserves dict insertion order. The fields appear in this order in the serialized JSON:

**Item level**: `id, media_type, category, title, root_folder_path, status, first_seen_at, last_seen_at, last_checked_at, video_files` (+ `subfolders` for TV)

**File level**: `name, status, first_seen_at, last_seen_at, last_checked_at`
