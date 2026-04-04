FROM nginx:alpine

RUN apk add --no-cache python3 dcron gettext

WORKDIR /app

# Copier le code applicatif dans l'image
COPY app/ /usr/share/nginx/html/
COPY conf/nginx.conf /etc/nginx/nginx.conf
COPY conf/scanner.py /app/scanner.py
COPY conf/entrypoint.sh /app/entrypoint.sh

RUN chmod +x /app/entrypoint.sh

# /data est le seul volume persistant — config.json, library.json, scanner.log
VOLUME ["/data"]

EXPOSE 80

ENTRYPOINT ["/app/entrypoint.sh"]
