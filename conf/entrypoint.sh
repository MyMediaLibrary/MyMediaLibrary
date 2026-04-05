#!/bin/sh
# entrypoint.sh — nginx + cron + scanner + scan API server

OUTPUT_PATH="${OUTPUT_PATH:-/data/library.json}"

echo "=== MyMediaLibrary ==="
echo "LIBRARY_PATH : ${LIBRARY_PATH:-/mnt/media/library}"
echo "OUTPUT_PATH  : ${OUTPUT_PATH}"
echo "SCAN_CRON    : ${SCAN_CRON:-0 3 * * *} (env fallback, overridden by config.json)"
echo ""

# Generate nginx.conf with env vars substituted
envsubst '${LIBRARY_PATH}' < /etc/nginx/nginx.conf > /tmp/nginx_rendered.conf
cp /tmp/nginx_rendered.conf /etc/nginx/nginx.conf

# Start nginx in background
nginx -g "daemon off;" &
NGINX_PID=$!
echo "[entrypoint] Nginx started (pid $NGINX_PID)"

# Start scan API server in background
python3 /app/scanner.py --serve &
SCANSERVER_PID=$!
echo "[entrypoint] Scan server started (pid $SCANSERVER_PID)"

# Copy providers_map.json from image to /data/ if absent (user customizations take priority)
if [ ! -f /data/providers_map.json ]; then
    cp /usr/share/nginx/html/providers_map.json /data/providers_map.json
    echo "[entrypoint] providers_map.json copié depuis l'image vers /data/"
fi

# Initial scan on startup — also runs migrate_env_to_config() which populates config.json
echo "[entrypoint] Running initial scan..."
python3 /app/scanner.py

# Read scan_cron from config.json (populated by initial scan via migrate_env_to_config)
# Falls back to SCAN_CRON env var, then to default
SCAN_CRON=$(python3 -c "
import json, os, sys
try:
    cfg = json.load(open('/data/config.json'))
    val = cfg.get('system', {}).get('scan_cron') or ''
    print(val if val else os.environ.get('SCAN_CRON', '0 3 * * *'))
except Exception:
    print(os.environ.get('SCAN_CRON', '0 3 * * *'))
" 2>/dev/null || echo "${SCAN_CRON:-0 3 * * *}")

echo "[entrypoint] Cron schedule: ${SCAN_CRON}"

# Write env file — sourced by the cron wrapper (only essential vars)
ENV_FILE="/app/scanner_env.sh"
cat > "$ENV_FILE" << ENVEOF
export LIBRARY_PATH="${LIBRARY_PATH:-/mnt/media/library}"
export OUTPUT_PATH="${OUTPUT_PATH:-/data/library.json}"
export LOG_LEVEL="${LOG_LEVEL:-INFO}"
ENVEOF
chmod 600 "$ENV_FILE"

# Write cron wrapper script — sources env then runs scanner
WRAPPER="/app/scan_cron.sh"
cat > "$WRAPPER" << 'WRAPEOF'
#!/bin/sh
. /app/scanner_env.sh
exec python3 /app/scanner.py >> /var/log/scanner.log 2>&1
WRAPEOF
chmod +x "$WRAPPER"

# Write crontab — uses scan_cron from config.json
CRON_FILE="/etc/cron.d/mymedialibrary"
printf '%s root %s\n' "$SCAN_CRON" "$WRAPPER" > "$CRON_FILE"
chmod 0644 "$CRON_FILE"
echo "[entrypoint] Cron scheduled: ${SCAN_CRON} → ${WRAPPER}"

# Start cron in foreground (keeps container alive)
crond -f -l 6
