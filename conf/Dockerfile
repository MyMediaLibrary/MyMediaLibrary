FROM nginx:alpine

ENV TZ=Europe/Paris

RUN apk add --no-cache python3 dcron gettext tzdata

WORKDIR /app

COPY conf/scanner.py /app/scanner.py
COPY conf/entrypoint.sh /app/entrypoint.sh
COPY conf/nginx.conf /etc/nginx/conf.d/default.conf
COPY data/ /data/

RUN chmod +x /app/entrypoint.sh \
 && touch /var/log/scanner.log \
 && touch /data/library.json

CMD ["/app/entrypoint.sh"]
