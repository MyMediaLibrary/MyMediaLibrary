FROM nginx:alpine3.23

# Keep runtime packages minimal:
# - python3: scanner + API
# - gettext-envsubst: render nginx config from env vars
# - tzdata: timezone support for scanner scheduler logs
RUN apk update \
    && apk upgrade --no-cache \
    && apk add --no-cache python3 gettext-envsubst tzdata

WORKDIR /app

# Copier le code applicatif dans l'image
COPY app/ /usr/share/nginx/html/
COPY docs/ /usr/share/nginx/html/docs/
COPY docker/nginx.conf /etc/nginx/nginx.conf
COPY backend/scanner.py /app/scanner.py
COPY backend/scoring.py /app/scoring.py
COPY backend/score_defaults.json /app/score_defaults.json
COPY backend/recommendations.py /app/recommendations.py
COPY backend/recommendations_rules.json /app/recommendations_rules.json
COPY backend/inventory_helpers.py /app/inventory_helpers.py
COPY backend/nfo.py /app/nfo.py
COPY docker/entrypoint.sh /app/entrypoint.sh

RUN chmod +x /app/entrypoint.sh

# /data est le seul volume persistant — config.json, library.json, scanner.log
VOLUME ["/data"]

EXPOSE 80

ENTRYPOINT ["/app/entrypoint.sh"]
