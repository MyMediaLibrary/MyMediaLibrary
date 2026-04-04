# 📼 Mediatheque

**[Français](#français) | [English](#english)**

---

<a name="français"></a>
## 🇫🇷 Français

**Mediatheque** est un tableau de bord auto-hébergé pour visualiser et explorer votre bibliothèque de films et séries. Il scanne vos fichiers vidéo locaux, lit les métadonnées depuis les fichiers `.nfo` (format Kodi/Jellyfin), et affiche une interface web filtrée dans un unique conteneur Docker.

<!-- screenshot -->

### ✨ Fonctionnalités

**Bibliothèque**
- Vue tuiles et tableau, tri multi-colonnes, recherche en temps réel
- Lazy loading par lots de 100 éléments
- Export CSV de la sélection courante

**Filtres**
- Type (Films / Séries), catégorie, résolution, codec, provider streaming
- Persistance des filtres entre sessions (localStorage)

**Métadonnées**
- Parsing automatique des `.nfo` Kodi/Jellyfin : titre, année, résolution, codec, HDR, durée, synopsis
- Affiches locales (`poster.jpg` / `poster.png`)
- Détection automatique de la résolution, codec et HDR depuis le NFO vidéo

**Providers streaming**
- Enrichissement via [Jellyseerr](https://github.com/Fallenbagel/jellyseerr) : disponibilité sur Netflix, Prime Video, Disney+, etc.
- Logos TMDB, filtre par provider, indicateur "non disponible sur les plateformes"

**Statistiques**
- Camemberts switchables taille/nombre : groupes, catégories, résolution, codec, providers
- Histogramme des ajouts par année ou décennie
- Courbe d'évolution mensuelle de la collection

**Configuration**
- Découverte automatique des dossiers au premier démarrage
- Typage Films / Séries / Ignorer directement depuis l'interface
- Configuration persistée dans `config.json` (pas de base de données)
- Visibilité par dossier paramétrable

**Paramètres**
- Thème clair / sombre, couleur d'accent personnalisable
- Synopsis au survol (activable / désactivable)
- Niveau de log, planification cron du scan automatique

**Authentification**
- Mot de passe optionnel via variable d'environnement (`APP_PASSWORD`)

**Opérations**
- Déclenchement de scan depuis l'interface avec panneau de logs en temps réel
- Modes `--quick` (sans réseau), `--full` (forcer tous les providers), `--enrich` (défaut)
- Logs rotatifs dans `./data/scanner.log`, endpoint `/health`

**Mobile**
- Layout responsive, bottom navigation, panneau filtres slide-down
- Vue tableau adaptée mobile avec colonne info condensée

---

### 🚀 Démarrage rapide

**Prérequis**
- Docker + Docker Compose
- Bibliothèque organisée en dossiers avec fichiers `.nfo` Kodi ou Jellyfin

**`compose.yaml` minimal**
```yaml
services:
  mediatheque:
    image: ghcr.io/magicgg91/mediatheque:latest
    container_name: mediatheque
    restart: unless-stopped
    ports:
      - "8094:80"
    volumes:
      - ./data:/data
      - /chemin/vers/ma/bibliotheque:/mnt/media/library:ro
    environment:
      LIBRARY_PATH: /mnt/media/library
```

```bash
docker compose up -d
```

Accédez à `http://localhost:8094`. Une modale de configuration s'affiche au premier démarrage pour assigner un type à chaque dossier et configurer Jellyseerr.

---

### ⚙️ Variables d'environnement

| Variable | Obligatoire | Défaut | Description |
|----------|-------------|--------|-------------|
| `LIBRARY_PATH` | ✅ | — | Chemin racine de la bibliothèque |
| `SCAN_CRON` | Non | `0 3 * * *` | Planification cron du scan automatique |
| `LOG_LEVEL` | Non | `INFO` | Niveau de log : `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `APP_PASSWORD` | Non | — | Active la protection par mot de passe |

> Les autres paramètres (Jellyseerr, dossiers, UI) sont configurables directement depuis l'interface et persistés dans `config.json`.

---

### 📁 Fichiers persistants

```
data/
├── library.json      # Index de la bibliothèque (généré par le scanner)
├── config.json       # Configuration de l'application (dossiers, Jellyseerr, UI)
└── scanner.log       # Logs du scanner (rotatif, 5 Mo max, 3 sauvegardes)
```

---

### 🤝 Contribution & Licence

Les contributions sont les bienvenues — ouvrez une issue ou une pull request.

Projet sous licence MIT.

---

<a name="english"></a>
## 🇬🇧 English

**Mediatheque** is a self-hosted dashboard for visualizing and browsing your movie and TV library. It scans local video files, reads metadata from `.nfo` files (Kodi/Jellyfin format), and serves a filterable web interface in a single Docker container.

<!-- screenshot -->

### ✨ Features

**Library**
- Grid and table views, multi-column sorting, real-time search
- Lazy loading in batches of 100 items
- CSV export of the current filtered selection

**Filters**
- Type (Movies / Series), category, resolution, codec, streaming provider
- Filter state persisted across sessions (localStorage)

**Metadata**
- Automatic `.nfo` parsing (Kodi/Jellyfin): title, year, resolution, codec, HDR, runtime, synopsis
- Local poster display (`poster.jpg` / `poster.png`)
- Resolution, codec, and HDR auto-detected from video NFO

**Streaming providers**
- Enrichment via [Jellyseerr](https://github.com/Fallenbagel/jellyseerr): availability on Netflix, Prime Video, Disney+, etc.
- TMDB logos, per-provider filter, "not available" indicator

**Statistics**
- Switchable size/count pie charts: groups, categories, resolution, codec, providers
- Bar chart of additions by year or decade
- Monthly collection growth timeline

**Configuration**
- Automatic folder discovery on first launch
- Assign Films / Series / Ignore types directly from the UI
- Settings persisted in `config.json` (no database)
- Per-folder visibility control

**Settings**
- Light / dark theme, custom accent color
- Synopsis on hover (toggle)
- Log level, automatic scan cron schedule

**Authentication**
- Optional password protection via `APP_PASSWORD` environment variable

**Operations**
- Scan triggered from the UI with real-time log panel
- Modes `--quick` (no network), `--full` (force all providers), `--enrich` (default)
- Rotating logs at `./data/scanner.log`, `/health` endpoint

**Mobile**
- Responsive layout, bottom navigation, slide-down filter panel
- Mobile-optimized table view with condensed info column

---

### 🚀 Quick start

**Requirements**
- Docker + Docker Compose
- Video library organized in folders with Kodi or Jellyfin `.nfo` files

**Minimal `compose.yaml`**
```yaml
services:
  mediatheque:
    image: ghcr.io/magicgg91/mediatheque:latest
    container_name: mediatheque
    restart: unless-stopped
    ports:
      - "8094:80"
    volumes:
      - ./data:/data
      - /path/to/my/library:/mnt/media/library:ro
    environment:
      LIBRARY_PATH: /mnt/media/library
```

```bash
docker compose up -d
```

Open `http://localhost:8094`. A setup wizard appears on first launch to assign a type to each folder and optionally configure Jellyseerr.

---

### ⚙️ Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LIBRARY_PATH` | ✅ | — | Root path of the media library |
| `SCAN_CRON` | No | `0 3 * * *` | Cron schedule for automatic scans |
| `LOG_LEVEL` | No | `INFO` | Log level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `APP_PASSWORD` | No | — | Enables password protection |

> All other settings (Jellyseerr, folders, UI preferences) are configurable from the web interface and persisted in `config.json`.

---

### 📁 Persistent files

```
data/
├── library.json      # Library index (generated by the scanner)
├── config.json       # Application configuration (folders, Jellyseerr, UI)
└── scanner.log       # Scanner logs (rotating, 5 MB max, 3 backups)
```

---

### 🤝 Contributing & License

Contributions are welcome — open an issue or pull request.

This project is MIT licensed.
