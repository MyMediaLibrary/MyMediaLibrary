# Audit runtime JSON / SQLite v0.5.0

## OK

- config: DB only via `backend.repositories.config_repository`; `/conf/config.json` is legacy import input only.
- auth settings: hash-only state in SQLite plus secrets in `/data/.secrets`; no secrets are stored in SQLite.
- score settings: DB only via config repository; built-in Python defaults are used for validation, not `/app/score_defaults.json`.
- scan settings: DB only via config repository.
- providers mapping: DB only via `backend.repositories.providers_repository`; bundled JSON is seed input only.
- providers logos: DB only via `backend.repositories.providers_repository`; bundled JSON is seed input only.
- recommendation rules: DB only via `backend.repositories.recommendations_repository`; bundled JSON is seed input only.
- library: DB only via `backend.repositories.media_repository`; UI reads `/api/library`.
- inventory: DB only via `backend.repositories.inventory_repository`.
- recommendations: DB only via `backend.repositories.recommendations_repository`.
- ffprobe cache: DB only via `backend.repositories.ffprobe_repository`.
- active sessions: in-memory signed session handling; not JSON backed.
- UI: API only for runtime data. Remaining JSON fetches are static assets (`i18n`, `version`, audio codec/language mappings).
- scanner: canonical runtime JSON writes are rejected; canonical library writes are redirected to SQLite.
- Docker/nginx: `/data`, `/conf`, dotfiles, DB files, WAL/SHM, and secrets are not served. `/library.json` returns `410` with `/api/library` as replacement.

## Occurrences JSON autorisées

- Bundled seed/default files copied into `/app/defaults/conf`:
  - `config.json`
  - `providers_mapping.json`
  - `providers_logo.json`
  - `recommendations_rules.json`
- Frontend static assets:
  - `app/i18n/*.json`
  - `version.json`
  - `audiocodec_mapping.json`
  - `audio_languages.json`
- Migration/import code in `backend/db_import.py` and path declarations in `backend/runtime_paths.py`.
- Explicit non-canonical export helpers in repositories, used by tests/import tools rather than canonical runtime paths.
- Unit/integration fixtures that intentionally create old JSON files to validate migration and guard behavior.
- Package/tooling JSON files.

## Occurrences JSON interdites trouvées

None after this audit.

The new guard script `scripts/audit-no-runtime-json.sh` fails if it finds:

- frontend fetches to legacy runtime JSON files;
- nginx static serving from `/data`;
- nginx routes for legacy runtime JSON files other than the intentional `/library.json` 410;
- `/conf` runtime mounts or documentation;
- direct scanner writes to canonical runtime JSON files;
- runtime JSON fallback wording/paths in scanner, repositories, frontend, or nginx.

## Corrections appliquées

- Added `scripts/audit-no-runtime-json.sh`.
- Added the audit script to CI before Python tests.
- Added a unit guard that executes the audit script.
- Removed obsolete Docker image copies of `/app/score_defaults.json` and `/app/recommendations_rules.json`.
- Updated provider documentation to describe SQLite-backed runtime mapping/logos instead of runtime JSON files.

## Tests ajoutés/modifiés

- `tests/python/unit/test_docker_storage_layout.py`
  - verifies the audit script exists and passes;
  - verifies obsolete runtime JSON/default paths are not copied into `/app`.

## Risques restants

- Legacy JSON import paths remain by design for one-time migration of existing installs.
- Repository helpers still support non-canonical JSON export/import paths for explicit tooling and tests; canonical runtime paths remain SQLite-only.
- `/library.json` remains as an authenticated `410 Gone` compatibility signal, not as a static JSON route.
