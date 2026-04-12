FROM nginx:alpine3.22

# Keep runtime packages minimal:
# - python3: scanner + API
# - dcron: scheduled scans
# - gettext-envsubst: render nginx config from env vars
# - tzdata: timezone support for scanner/cron logs
RUN apk upgrade --no-cache \
    && apk add --no-cache python3 dcron gettext-envsubst tzdata

WORKDIR /app

# Copier le code applicatif dans l'image
COPY app/ /usr/share/nginx/html/
COPY docs/ /usr/share/nginx/html/docs/
COPY conf/nginx.conf /etc/nginx/nginx.conf
COPY conf/scanner.py /app/scanner.py
COPY conf/scoring.py /app/scoring.py
COPY conf/inventory_helpers.py /app/inventory_helpers.py
COPY conf/entrypoint.sh /app/entrypoint.sh

RUN chmod +x /app/entrypoint.sh

# /data est le seul volume persistant — config.json, library.json, scanner.log
VOLUME ["/data"]

EXPOSE 80

ENTRYPOINT ["/app/entrypoint.sh"]
