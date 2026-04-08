# 📼 MyMediaLibrary

**[Français](#français) | [English](#english)**

---

<a name="français"></a>
## 🇫🇷 Français

Tableau de bord auto-hébergé pour visualiser votre bibliothèque de films et séries. Scanne les fichiers `.nfo` (Kodi/Jellyfin), affiche une interface web filtrée, tourne dans un unique conteneur Docker.

**→ [Documentation complète](docs/fr.md)**

### Démarrage rapide

```yaml
# compose.yaml
services:
  mymedialibrary:
    image: ghcr.io/mymedialibrary/mymedialibrary:latest
    container_name: mymedialibrary
    ports:
      - "8094:80"
    volumes:
      - ./data:/data
      - /chemin/vers/ta/mediatheque:/library:ro
    environment:
      LIBRARY_PATH: /library
      # SCAN_CRON: "0 3 * * *"
      # LOG_LEVEL: INFO
      # APP_PASSWORD: ""
    restart: unless-stopped
```

```bash
mkdir mymedialibrary && cd mymedialibrary && mkdir data
# créer compose.yaml ci-dessus, puis :
docker compose up -d
```

Accéder à `http://localhost:8094` — un assistant de configuration s'affiche au premier démarrage.

### Mise à jour

```bash
docker compose pull && docker compose up -d
```

### Contribution & Licence

Contributions bienvenues — ouvrez une issue ou une PR. Licence MIT.

---

<a name="english"></a>
## 🇬🇧 English

Self-hosted dashboard for visualizing your movie and TV library. Scans `.nfo` files (Kodi/Jellyfin), serves a filterable web interface, runs in a single Docker container.

**→ [Full documentation](docs/en.md)**

### Quick start

```yaml
# compose.yaml
services:
  mymedialibrary:
    image: ghcr.io/mymedialibrary/mymedialibrary:latest
    container_name: mymedialibrary
    ports:
      - "8094:80"
    volumes:
      - ./data:/data
      - /path/to/your/library:/library:ro
    environment:
      LIBRARY_PATH: /library
      # SCAN_CRON: "0 3 * * *"
      # LOG_LEVEL: INFO
      # APP_PASSWORD: ""
    restart: unless-stopped
```

```bash
mkdir mymedialibrary && cd mymedialibrary && mkdir data
# create compose.yaml above, then:
docker compose up -d
```

Open `http://localhost:8094` — a setup wizard appears on first launch.

### Updating

```bash
docker compose pull && docker compose up -d
```

### Contributing & License

Contributions welcome — open an issue or PR. MIT licensed.
