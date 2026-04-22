#!/bin/sh
# entrypoint.sh — nginx + cron + scanner + scan API server

OUTPUT_PATH="${OUTPUT_PATH:-/data/library.json}"
LOG_PATH="${LOG_PATH:-/data/scanner.log}"
TZ="${TZ:-UTC}"
export TZ

echo "=== MyMediaLibrary ==="
echo "LIBRARY_PATH : ${LIBRARY_PATH:-/mnt/media/library}"
echo "OUTPUT_PATH  : ${OUTPUT_PATH}"
echo "LOG_PATH     : ${LOG_PATH}"
echo ""

# Create /app/.secrets if missing (stores Seerr API key securely)
if [ ! -f /app/.secrets ]; then
  echo '{}' > /app/.secrets
  chmod 600 /app/.secrets
  echo "[entrypoint] Created /app/.secrets"
fi

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

# Read scan_cron from config.json — sole source of truth
SCAN_CRON=$(python3 -c "
import json
try:
    cfg = json.load(open('/data/config.json'))
    val = cfg.get('system', {}).get('scan_cron') or ''
    print(val if val else '0 3 * * *')
except Exception:
    print('0 3 * * *')
" 2>/dev/null || echo "0 3 * * *")

echo "[entrypoint] Cron schedule: ${SCAN_CRON}"

# Write env file — sourced by the cron wrapper (only essential vars)
ENV_FILE="/app/scanner_env.sh"
cat > "$ENV_FILE" << ENVEOF
export LIBRARY_PATH="${LIBRARY_PATH:-/mnt/media/library}"
export OUTPUT_PATH="${OUTPUT_PATH:-/data/library.json}"
export LOG_PATH="${LOG_PATH:-/data/scanner.log}"
export TZ="${TZ:-UTC}"
ENVEOF
chmod 600 "$ENV_FILE"

# Write cron wrapper script — sources env then runs scanner
WRAPPER="/app/scan_cron.sh"
cat > "$WRAPPER" << 'WRAPEOF'
#!/bin/sh
. /app/scanner_env.sh
exec python3 /app/scanner.py --full --origin cron
WRAPEOF
chmod +x "$WRAPPER"

# Write crontab — uses scan_cron from config.json
CRON_FILE="/etc/cron.d/mymedialibrary"
printf '%s root %s\n' "$SCAN_CRON" "$WRAPPER" > "$CRON_FILE"
chmod 0644 "$CRON_FILE"
echo "[entrypoint] Cron scheduled: ${SCAN_CRON} → ${WRAPPER}"

# Start cron in foreground (keeps container alive)
crond -f -l 6
