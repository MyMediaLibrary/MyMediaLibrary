#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

failures=0

report_failure() {
  local title="$1"
  local matches="$2"
  if [[ -n "$matches" ]]; then
    printf '\n[audit-no-runtime-json] %s\n' "$title" >&2
    printf '%s\n' "$matches" >&2
    failures=1
  fi
}

run_rg() {
  if command -v rg >/dev/null 2>&1; then
    rg "$@" || true
  else
    grep -RInE "$*" . || true
  fi
}

run_rg_runtime() {
  local pattern="$1"
  shift
  if command -v rg >/dev/null 2>&1; then
    rg -n --hidden "$pattern" "$@" \
      --glob '!tests/**' \
      --glob '!scripts/audit-no-runtime-json.sh' \
      --glob '!docs/audit-*' || true
  else
    grep -RInE \
      --exclude='audit-no-runtime-json.sh' \
      --exclude='audit-*' \
      --exclude-dir='tests' \
      "$pattern" "$@" || true
  fi
}

legacy_json='(library|recommendations|library_inventory|media_probe_cache|providers_mapping|providers_logo|recommendations_rules|config)\.json'

# Frontend runtime must use the API. Static assets such as i18n/version/audio mappings
# are intentionally not matched here.
frontend_fetches="$(
  run_rg_runtime "fetch\\([^)]*/${legacy_json}" app/js app/*.html 2>/dev/null
)"
report_failure "Forbidden frontend fetch to legacy runtime JSON" "$frontend_fetches"

# nginx may keep a compatibility 410 for /library.json, but it must never serve
# files from /data or expose legacy JSON/SQLite/secrets as static assets.
nginx_static_storage="$(
  run_rg_runtime "alias\\s+/data|try_files\\s+[^;]*(/data|${legacy_json}|mymedialibrary\\.db|\\.secrets)|root\\s+/data" docker/nginx.conf 2>/dev/null
)"
report_failure "Forbidden nginx static serving from runtime storage" "$nginx_static_storage"

nginx_legacy_routes="$(
  run_rg_runtime "location\\s+(=|~|/).*(/recommendations\\.json|/library_inventory\\.json|/media_probe_cache\\.json|/providers_mapping\\.json|/providers_logo\\.json|/recommendations_rules\\.json|/config\\.json)" docker/nginx.conf 2>/dev/null
)"
report_failure "Forbidden nginx route for legacy runtime JSON" "$nginx_legacy_routes"

# /conf is legacy migration input only. It must not be mounted into the runtime
# container or documented as a required volume.
conf_mounts="$(
  run_rg_runtime "\\./conf:/conf|:/conf(:|$)|/conf\\s+#|/conf\\s*$" compose.yaml docker README.md docs/fr.md docs/en.md 2>/dev/null
)"
report_failure "Forbidden /conf runtime mount or documentation" "$conf_mounts"

# Scanner writes must flow through write_json(), which redirects the canonical
# library document into SQLite and rejects canonical JSON files. Direct atomic
# writes to canonical runtime JSON paths are not allowed in scanner runtime.
scanner_direct_json="$(
  run_rg_runtime "_write_json_file_atomic\\([^\\n]*(OUTPUT_PATH|runtime_paths\\.|LIBRARY_JSON|INVENTORY_JSON|RECOMMENDATIONS_JSON|MEDIA_PROBE_CACHE_JSON)" backend/scanner.py 2>/dev/null
)"
report_failure "Forbidden direct scanner write to runtime JSON" "$scanner_direct_json"

# Legacy import/seed code is allowed to mention JSON, but runtime code should not
# implement JSON fallback when the canonical SQLite path is unavailable.
runtime_fallback_phrases="$(
  run_rg_runtime "falling back to JSON|fallback JSON|JSON fallback|fallback to .*\\.json" backend/scanner.py backend/repositories app/js docker 2>/dev/null
)"
report_failure "Forbidden runtime JSON fallback wording/path" "$runtime_fallback_phrases"

if [[ "$failures" -ne 0 ]]; then
  printf '\n[audit-no-runtime-json] FAILED\n' >&2
  exit 1
fi

printf '[audit-no-runtime-json] OK — no forbidden runtime JSON usage found\n'
