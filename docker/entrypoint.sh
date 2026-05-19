#!/bin/sh
# entrypoint.sh — nginx + scanner + scan API server

LOG_PATH="${LOG_PATH:-/data/scanner.log}"
TZ="${TZ:-UTC}"
export TZ

echo "=== MyMediaLibrary ==="
echo "LIBRARY_DIR  : /library"
echo "LOG_PATH     : ${LOG_PATH}"
echo ""

# 1. Migrate legacy runtime files (idempotent).
PYTHONPATH=/app python3 -m backend.storage_migration || exit 1

# 2. Bootstrap SQLite DB: run schema migrations + seed defaults + import legacy JSON.
#    Runs sequentially here so both services below start with a fully migrated DB.
#    On first boot this may take a few seconds if legacy JSON files exist.
#    On subsequent boots the DB is already at SCHEMA_VERSION and this is a fast no-op.
echo "[entrypoint] Bootstrapping database..."
PYTHONPATH=/app python3 -m backend.db || { echo "[entrypoint] DB bootstrap failed — aborting"; exit 1; }

# 3. Start nginx in background
nginx -g "daemon off;" &
NGINX_PID=$!
echo "[entrypoint] Nginx started (pid $NGINX_PID)"

# 4. Start scan API server in background.
#    DB is already bootstrapped; skip redundant seed/JSON migration.
MML_SKIP_DB_STARTUP_TASKS=1 python3 /app/scanner.py --serve &
SCANSERVER_PID=$!
echo "[entrypoint] Scan server started (pid $SCANSERVER_PID)"

# 5. Run initial scan (phases decided by scanner startup rules).
#    DB is already bootstrapped; skip redundant seed/JSON migration.
echo "[entrypoint] Running initial scan..."
MML_SKIP_DB_STARTUP_TASKS=1 python3 /app/scanner.py --origin startup

# The scan API server owns the user scheduler and reloads it on config saves.
# Keep the container alive by waiting on that foreground service.
wait "$SCANSERVER_PID"
