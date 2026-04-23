# 📼 MyMediaLibrary

<img src="docs/assets/mymedialibrary1.png" width="45%">  <img src="docs/assets/mymedialibrary2.png" width="45%">

---

**[Français](#français) | [English](#english)**

---

<a name="français"></a>
## 🇫🇷 Français

Tableau de bord auto-hébergé pour visualiser votre bibliothèque de films et séries. Scanne les fichiers `.nfo` (Kodi/Jellyfin/Emby), affiche une interface web filtrée, tourne dans un unique conteneur Docker. _Projet développé en vibe-coding avec l’aide de l’IA._

**→ [Documentation complète](docs/fr.md)**

### Fonctionnalités

- **Bibliothèque unifiée** : visualisation de vos films et séries en vue grille ou tableau, avec posters, métadonnées et informations techniques enrichies depuis les NFO (résolution, codecs, HDR, genres, channels audio, langues de sous-titres, bitrate vidéo)
- **Filtres avancés** : système cohérent de dropdowns multi-sélection (type, dossier, genre, streaming, langue audio, score) avec mode inclure/exclure, plus un bloc technique repliable (résolution, codecs, channels audio)
- **Disponibilités streaming** : enrichissement via Seerr pour afficher les plateformes sur lesquelles chaque titre est disponible (Netflix, Canal+, etc.)
- **Statistiques** : page organisée en sous-onglets (Générales / Techniques / Évolution), avec graphes existants réutilisés et nouveaux graphes Genres + Channels audio
- **Scan configurable** : scan rapide (local uniquement) ou scan complet (avec Seerr), planifiable via cron, configurable depuis l'interface
- **Score qualité (optionnel)** : système configurable (poids + règles) où l’audio combine désormais codec + channels, avec détail `video_details` et `audio_details` dans `library.json`
- **Interface bilingue** : interface entièrement disponible en français et en anglais, thème clair/sombre, responsive

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
      TZ: Europe/Paris
      # SEERR_URL: "http://seerr:5055"
      # SEERR_API_KEY: "your-seerr-api-key"
      # APP_PASSWORD: ""
    restart: unless-stopped
```

```bash
mkdir mymedialibrary && cd mymedialibrary && mkdir data
# créer compose.yaml ci-dessus, puis :
docker compose up -d
```

Accéder à `http://localhost:8094` — un assistant de configuration s'affiche au premier démarrage.

> Le cron de scan automatique et le niveau de log se configurent dans **Paramètres > Système**.

### Mise à jour

```bash
docker compose pull && docker compose up -d
```

### Scan sécurité (Grype)

```bash
docker build -t mymedialibrary:local -f docker/Dockerfile .
grype mymedialibrary:local
```

> Workflow CI optionnel: **Security Scan (Grype)** s’exécute chaque semaine (et en manuel) puis publie les rapports table/JSON en artifacts.

### Contribution & Licence

Contributions bienvenues — ouvrez une issue ou une PR. Licence MIT.

---

<a name="english"></a>
## 🇬🇧 English

Self-hosted dashboard for visualizing your movie and TV library. Scans `.nfo` files (Kodi/Jellyfin/Emby), serves a filterable web interface, runs in a single Docker container. _Built using vibe coding with AI assistance._

**→ [Full documentation](docs/en.md)**

### Features

- **Unified library**: browse your movies and TV shows in grid or table view, with posters, metadata, and enriched NFO technical fields (resolution, codecs, HDR, genres, audio channels, subtitle languages, video bitrate)
- **Advanced filters**: consistent multi-select dropdown system (type, folder, genre, streaming, audio language, score) with include/exclude mode, plus a dedicated collapsible technical group (resolution, codecs, audio channels)
- **Streaming availability**: Seerr enrichment to show on which platforms each title is available (Netflix, Canal+, etc.)
- **Statistics**: page split into subtabs (General / Technical / Evolution), reusing existing charts and adding Genres + Audio channels charts
- **Configurable scan**: quick scan (local only) or full scan (with Seerr), schedulable via cron, configurable from the UI
- **Quality score (optional)**: configurable scoring system where audio now combines codec + channels, with detailed `video_details` and `audio_details` stored in `library.json`
- **Bilingual interface**: fully available in French and English, light/dark theme, responsive

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
      TZ: Europe/Paris
      # SEERR_URL: "http://seerr:5055"
      # SEERR_API_KEY: "your-seerr-api-key"
      # APP_PASSWORD: ""
    restart: unless-stopped
```

```bash
mkdir mymedialibrary && cd mymedialibrary && mkdir data
# create compose.yaml above, then:
docker compose up -d
```

Open `http://localhost:8094` — a setup wizard appears on first launch.

> Auto-scan schedule and log level are configured in **Settings > System**.

### Updating

```bash
docker compose pull && docker compose up -d
```

### Security scan (Grype)

```bash
docker build -t mymedialibrary:local -f docker/Dockerfile .
grype mymedialibrary:local
```

> Optional CI workflow: **Security Scan (Grype)** runs weekly and on manual trigger, then publishes table/JSON reports as artifacts.

### Contributing & License

Contributions welcome — open an issue or PR. MIT licensed.
