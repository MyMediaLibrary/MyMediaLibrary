FROM nginx:alpine3.23

# Keep runtime packages minimal:
# - python3: scanner + API
# - dcron: scheduled scans
# - gettext-envsubst: render nginx config from env vars
# - tzdata: timezone support for scanner/cron logs
RUN apk update \
    && apk upgrade --no-cache \
    && apk add --no-cache python3 dcron gettext-envsubst tzdata

WORKDIR /app

# Copier le code applicatif dans l'image
COPY app/ /usr/share/nginx/html/
COPY docs/ /usr/share/nginx/html/docs/
COPY docker/nginx.conf /etc/nginx/nginx.conf
COPY backend/scanner.py /app/scanner.py
COPY backend/scoring.py /app/scoring.py
COPY backend/inventory_helpers.py /app/inventory_helpers.py
COPY backend/nfo.py /app/nfo.py
COPY docker/entrypoint.sh /app/entrypoint.sh

RUN chmod +x /app/entrypoint.sh

# /data est le seul volume persistant — config.json, library.json, scanner.log
VOLUME ["/data"]

EXPOSE 80

ENTRYPOINT ["/app/entrypoint.sh"]
