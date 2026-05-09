#!/bin/sh
# entrypoint.sh — nginx + scanner + scan API server

LOG_PATH="${LOG_PATH:-/data/scanner.log}"
TZ="${TZ:-UTC}"
export TZ

echo "=== MyMediaLibrary ==="
echo "LIBRARY_DIR  : /library"
echo "LOG_PATH     : ${LOG_PATH}"
echo ""

# Migrate legacy runtime files before any service starts.
PYTHONPATH=/app python3 -m backend.storage_migration || exit 1

# Start nginx in background
nginx -g "daemon off;" &
NGINX_PID=$!
echo "[entrypoint] Nginx started (pid $NGINX_PID)"

# Start scan API server in background
python3 /app/scanner.py --serve &
SCANSERVER_PID=$!
echo "[entrypoint] Scan server started (pid $SCANSERVER_PID)"

# Initial scan on startup (phases decided by scanner startup rules)
echo "[entrypoint] Running initial scan..."
python3 /app/scanner.py --origin startup

# The scan API server owns the user scheduler and reloads it on config saves.
# Keep the container alive by waiting on that foreground service.
wait "$SCANSERVER_PID"
