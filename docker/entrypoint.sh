#!/bin/sh
# entrypoint.sh — nginx + scanner + scan API server

OUTPUT_PATH="${OUTPUT_PATH:-/data/library.json}"
LOG_PATH="${LOG_PATH:-/data/scanner.log}"
TZ="${TZ:-UTC}"
export TZ

echo "=== MyMediaLibrary ==="
echo "LIBRARY_PATH : ${LIBRARY_PATH:-/mnt/media/library}"
echo "OUTPUT_PATH  : ${OUTPUT_PATH}"
echo "LOG_PATH     : ${LOG_PATH}"
echo ""

# Migrate legacy runtime files before any service starts.
PYTHONPATH=/app python3 -m backend.storage_migration || exit 1

# Generate nginx.conf with env vars substituted
envsubst '${LIBRARY_PATH}' < /etc/nginx/nginx.conf > /tmp/nginx_rendered.conf
cp /tmp/nginx_rendered.conf /etc/nginx/nginx.conf

# Keep persisted JSON artifacts readable by nginx worker (fix legacy 0600 files).
if [ -f "$OUTPUT_PATH" ]; then
  chmod 644 "$OUTPUT_PATH" || true
fi
if [ -f "/data/library_inventory.json" ]; then
  chmod 644 "/data/library_inventory.json" || true
fi

# Start nginx in background
nginx -g "daemon off;" &
NGINX_PID=$!
echo "[entrypoint] Nginx started (pid $NGINX_PID)"

# Start scan API server in background
python3 /app/scanner.py --serve &
SCANSERVER_PID=$!
echo "[entrypoint] Scan server started (pid $SCANSERVER_PID)"

# Bootstrap editable providers mapping in /data (copy-once, never overwrite)
PROVIDERS_MAPPING_SRC="${PROVIDERS_MAPPING_SOURCE_PATH:-/usr/share/nginx/html/providers_mapping.json}"
PROVIDERS_MAPPING_DST="${PROVIDERS_MAPPING_RUNTIME_PATH:-/data/providers_mapping.json}"
if [ ! -f "$PROVIDERS_MAPPING_DST" ]; then
  if [ -f "$PROVIDERS_MAPPING_SRC" ]; then
    cp "$PROVIDERS_MAPPING_SRC" "$PROVIDERS_MAPPING_DST"
  else
    echo '{}' > "$PROVIDERS_MAPPING_DST"
  fi
  echo "[entrypoint] Bootstrapped providers mapping: $PROVIDERS_MAPPING_DST"
fi

# Initial scan on startup (phases decided by scanner startup rules)
echo "[entrypoint] Running initial scan..."
python3 /app/scanner.py --origin startup

# The scan API server owns the user scheduler and reloads it on config saves.
# Keep the container alive by waiting on that foreground service.
wait "$SCANSERVER_PID"
