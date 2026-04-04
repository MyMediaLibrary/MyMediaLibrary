# 📼 MyMediaLibrary

**[Français](#français) | [English](#english)**

---

<a name="français"></a>
## 🇫🇷 Français

**MyMediaLibrary** est un tableau de bord auto-hébergé pour visualiser votre bibliothèque de films et séries. Il scanne vos fichiers vidéo locaux, lit les métadonnées depuis les fichiers `.nfo` (format Kodi/Jellyfin), et affiche une interface web filtrée dans un unique conteneur Docker.

### ✨ Fonctionnalités

- Vue tuiles et tableau, tri, recherche en temps réel, export CSV
- Filtres par type, catégorie, résolution, codec, provider streaming
- Parsing `.nfo` : titre, année, résolution, codec, HDR, durée, synopsis, affiches locales
- Enrichissement streaming via [Jellyseerr](https://github.com/Fallenbagel/jellyseerr) (Netflix, Prime, Disney+…)
- Statistiques : camemberts, histogramme par année/décennie, courbe d'évolution mensuelle
- Configuration par l'interface, persistée dans `config.json` (pas de base de données)
- Scan déclenchable depuis l'UI avec logs en temps réel, endpoint `/health`
- Thème clair/sombre, couleur d'accent, mot de passe optionnel
- Layout responsive avec navigation mobile

---

### 🚀 Installation

**Prérequis :** Docker + Docker Compose, bibliothèque avec fichiers `.nfo` Kodi/Jellyfin.

```bash
mkdir mymedialibrary && cd mymedialibrary && mkdir data
curl -O https://raw.githubusercontent.com/MyMediaLibrary/MyMediaLibrary/main/compose.yaml
```

Éditer `compose.yaml` et remplacer `/chemin/vers/ta/mediatheque` par le chemin réel de ta bibliothèque, puis :

```bash
docker compose up -d
```

Accéder à `http://localhost:8094`. Une modale de configuration s'affiche au premier démarrage.

**`compose.yaml`**
```yaml
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

> `LIBRARY_PATH` est fixé à `/library` dans le conteneur — seul le chemin source du volume est à adapter.

---

### 🔄 Mise à jour

```bash
docker compose pull && docker compose up -d
```

---

### 📁 Fichiers persistants

```
data/
├── library.json   # index de la bibliothèque
├── config.json    # configuration (dossiers, Jellyseerr, UI)
└── scanner.log    # logs rotatifs (5 Mo max, 3 sauvegardes)
```

---

### 🤝 Contribution & Licence

Contributions bienvenues — ouvrez une issue ou une PR. Licence MIT.

---

<a name="english"></a>
## 🇬🇧 English

**MyMediaLibrary** is a self-hosted dashboard for visualizing your movie and TV library. It scans local video files, reads metadata from `.nfo` files (Kodi/Jellyfin format), and serves a filterable web interface in a single Docker container.

### ✨ Features

- Grid and table views, sorting, real-time search, CSV export
- Filters by type, category, resolution, codec, streaming provider
- `.nfo` parsing: title, year, resolution, codec, HDR, runtime, synopsis, local posters
- Streaming enrichment via [Jellyseerr](https://github.com/Fallenbagel/jellyseerr) (Netflix, Prime, Disney+…)
- Statistics: pie charts, year/decade bar chart, monthly growth timeline
- UI-driven configuration persisted in `config.json` (no database)
- Scan triggered from the UI with real-time logs, `/health` endpoint
- Light/dark theme, custom accent color, optional password
- Responsive layout with mobile navigation

---

### 🚀 Installation

**Requirements:** Docker + Docker Compose, library with Kodi/Jellyfin `.nfo` files.

```bash
mkdir mymedialibrary && cd mymedialibrary && mkdir data
curl -O https://raw.githubusercontent.com/MyMediaLibrary/MyMediaLibrary/main/compose.yaml
```

Edit `compose.yaml` and replace `/chemin/vers/ta/mediatheque` with your actual library path, then:

```bash
docker compose up -d
```

Open `http://localhost:8094`. A setup wizard appears on first launch.

**`compose.yaml`**
```yaml
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

> `LIBRARY_PATH` is fixed to `/library` inside the container — only the volume source path needs to be updated.

---

### 🔄 Updating

```bash
docker compose pull && docker compose up -d
```

---

### 📁 Persistent files

```
data/
├── library.json   # library index
├── config.json    # configuration (folders, Jellyseerr, UI)
└── scanner.log    # rotating logs (5 MB max, 3 backups)
```

---

### 🤝 Contributing & License

Contributions welcome — open an issue or PR. MIT licensed.
