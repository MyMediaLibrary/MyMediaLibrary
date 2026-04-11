# 📼 MyMediaLibrary

<img src="docs/assets/mymedialibrary1.png" width="45%">  <img src="docs/assets/mymedialibrary2.png" width="45%">

---

**[Français](#français) | [English](#english)**

---

<a name="français"></a>
## 🇫🇷 Français

Tableau de bord auto-hébergé pour visualiser votre bibliothèque de films et séries. Scanne les fichiers `.nfo` (Kodi/Jellyfin), affiche une interface web filtrée, tourne dans un unique conteneur Docker. _Projet développé en vibe-coding avec l’aide de l’IA._

**→ [Documentation complète](docs/fr.md)**

### Fonctionnalités

- **Bibliothèque unifiée** : visualisation de vos films et séries en vue grille ou tableau, avec posters, métadonnées et informations techniques (résolution, codec vidéo/audio, HDR)
- **Filtres avancés** : filtrage multi-critères par dossier, type, résolution, provider streaming, codec vidéo, codec audio et langue audio — avec persistance entre sessions
- **Disponibilités streaming** : enrichissement via Jellyseerr pour afficher les plateformes sur lesquelles chaque titre est disponible (Netflix, Canal+, etc.)
- **Statistiques** : camemberts et courbe temporelle sur la composition de la bibliothèque (groupes, résolution, codecs, providers, langues audio)
- **Scan configurable** : scan rapide (local uniquement) ou scan complet (avec Jellyseerr), planifiable via cron, configurable depuis l'interface
- **Scoring qualité** : système de score qualité (0–100) avec niveaux visuels, filtres et analyse détaillée
- **Interface bilingue** : UI entièrement disponible en français et en anglais, thème clair/sombre, sidebar redimensionnable

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

### Contribution & Licence

Contributions bienvenues — ouvrez une issue ou une PR. Licence MIT.

---

<a name="english"></a>
## 🇬🇧 English

Self-hosted dashboard for visualizing your movie and TV library. Scans `.nfo` files (Kodi/Jellyfin), serves a filterable web interface, runs in a single Docker container. _Built using vibe coding with AI assistance._

**→ [Full documentation](docs/en.md)**

### Features

- **Unified library**: browse your movies and TV shows in grid or table view, with posters, metadata, and technical details (resolution, video/audio codec, HDR)
- **Advanced filters**: multi-criteria filtering by folder, type, resolution, streaming provider, video codec, audio codec, and audio language — persisted between sessions
- **Streaming availability**: Jellyseerr enrichment to show on which platforms each title is available (Netflix, Canal+, etc.)
- **Statistics**: pie charts and timeline on library composition (groups, resolution, codecs, providers, audio languages)
- **Configurable scan**: quick scan (local only) or full scan (with Jellyseerr), schedulable via cron, configurable from the UI
- **Quality scoring**: quality scoring system (0–100) with visual levels, filters, and detailed analysis
- **Bilingual interface**: fully available in French and English, light/dark theme, resizable sidebar

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

### Contributing & License

Contributions welcome — open an issue or PR. MIT licensed.
