# 📼 MyMediaLibrary

**[Français](#français) | [English](#english)**

---

<a name="français"></a>
## 🇫🇷 Français

**MyMediaLibrary** est un tableau de bord auto-hébergé pour visualiser votre bibliothèque de films et séries. Il scanne vos fichiers vidéo locaux, lit les métadonnées depuis les fichiers `.nfo` (format Kodi/Jellyfin), et affiche une interface web filtrée dans un unique conteneur Docker.

### ✨ Fonctionnalités

- **Bibliothèque** — vue tuiles et tableau, filtres (type, dossier, résolution, codec, provider streaming), recherche, tri
- **Métadonnées** — parsing `.nfo` Kodi/Jellyfin : titre, année, résolution, codec, HDR, durée, synopsis, affiches locales
- **Providers streaming** — enrichissement optionnel via [Jellyseerr](https://github.com/Fallenbagel/jellyseerr) avec normalisation configurable
- **Statistiques** — camemberts, histogramme par année/décennie, courbe d'évolution mensuelle
- **Interface bilingue** — FR/EN, sélection à la première ouverture et depuis les paramètres, sans rechargement
- **Zéro configuration** — assistant au premier démarrage, tout persisté dans `config.json`, aucune base de données

---

### 🚀 Installation

**Prérequis :** Docker + Docker Compose, bibliothèque avec fichiers `.nfo` Kodi/Jellyfin.

```bash
mkdir mymedialibrary && cd mymedialibrary && mkdir data
curl -O https://raw.githubusercontent.com/MyMediaLibrary/MyMediaLibrary/main/compose.yaml
```

Éditer `compose.yaml`, remplacer `/chemin/vers/ta/mediatheque` par le chemin réel, puis :

```bash
docker compose up -d
```

Accéder à `http://localhost:8094`. Un assistant de configuration s'affiche au premier démarrage.

**`compose.yaml`**
```yaml
services:
  mymedialibrary:
    image: ghcr.io/mymedialibrary/mymedialibrary:latest
    container_name: mymedialibrary
    ports:
      - "8094:80"
    volumes:
      - ./data:/data                             # config.json, library.json, scanner.log
      - /chemin/vers/ta/mediatheque:/library:ro  # ta médiathèque en lecture seule
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
├── library.json   # index de la bibliothèque (généré par le scanner)
├── config.json    # configuration (dossiers, Jellyseerr, UI, langue)
└── scanner.log    # logs rotatifs (5 Mo max, 3 sauvegardes)
```

---

### ⚙️ Variables d'environnement

| Variable | Obligatoire | Défaut | Description |
|---|---|---|---|
| `LIBRARY_PATH` | ✅ | — | Chemin racine de la bibliothèque |
| `SCAN_CRON` | ❌ | `0 3 * * *` | Planification du scan automatique (format cron) |
| `LOG_LEVEL` | ❌ | `INFO` | Niveau de log (`INFO` / `DEBUG`) |
| `APP_PASSWORD` | ❌ | — | Mot de passe optionnel (active l'écran de connexion) |

Tous les autres paramètres (dossiers, Jellyseerr, UI) sont configurables depuis l'interface web et persistés dans `config.json`.

---

### 📂 Structure de la bibliothèque

Le scanner lit directement les sous-dossiers de `LIBRARY_PATH`. Chaque sous-dossier correspond à un **dossier** configurable (Films, Séries, Anime…).

**Exemple de structure recommandée :**

```
/mnt/media/library/          ← LIBRARY_PATH
├── movies/
│   ├── The Dark Knight (2008)/
│   │   ├── The Dark Knight (2008).mkv
│   │   └── The Dark Knight (2008).nfo
│   └── Inception (2010)/
│       └── Inception (2010).mkv
├── tv/
│   └── Breaking Bad/
│       ├── Season 01/
│       │   └── Breaking.Bad.S01E01.mkv
│       └── tvshow.nfo
└── anime/
    └── Demon Slayer/
```

**Options de montage Docker :**

```yaml
# Option A — bibliothèque sur le même hôte
volumes:
  - /mnt/media/library:/library:ro
  - ./data:/data

# Option B — montage réseau (NFS, SMB)
volumes:
  - /mnt/nas/media:/library:ro
  - ./data:/data
```

Les fichiers `.nfo` (format Kodi/Jellyfin) sont lus automatiquement pour extraire titre, année, synopsis, résolution, codec et durée. Sans `.nfo`, le titre est extrait du nom de dossier.

---

### 🗂️ Providers streaming

La normalisation des noms de providers (ex. `"Amazon Prime Video"` → `"Prime Video"`) et les logos associés sont définis dans `app/providers.json`, inclus dans l'image Docker.

Pour contribuer une correction au fichier de référence : ouvrir une PR sur le dépôt GitHub.

---

### 🔒 Authentification

Si `APP_PASSWORD` est défini, le mot de passe est demandé avant l'affichage de l'interface, y compris lors de la configuration initiale.

Sans `APP_PASSWORD`, l'interface est accessible sans authentification — utilisez un reverse proxy (NPM, Traefik) ou un VPN/Tailscale pour une protection réseau.

---

### 🤝 Contribution & Licence

Contributions bienvenues — ouvrez une issue ou une PR. Licence MIT.

---

<a name="english"></a>
## 🇬🇧 English

**MyMediaLibrary** is a self-hosted dashboard for visualizing your movie and TV library. It scans local video files, reads metadata from `.nfo` files (Kodi/Jellyfin format), and serves a filterable web interface in a single Docker container.

### ✨ Features

- **Library** — grid and table views, filters (type, folder, resolution, codec, streaming provider), search, sort
- **Metadata** — Kodi/Jellyfin `.nfo` parsing: title, year, resolution, codec, HDR, runtime, synopsis, local posters
- **Streaming providers** — optional enrichment via [Jellyseerr](https://github.com/Fallenbagel/jellyseerr) with configurable normalization
- **Statistics** — pie charts, year/decade bar chart, monthly growth timeline
- **Bilingual UI** — FR/EN, selected at first launch and from settings, no page reload required
- **Zero config** — setup wizard on first launch, everything persisted in `config.json`, no database

---

### 🚀 Installation

**Requirements:** Docker + Docker Compose, library with Kodi/Jellyfin `.nfo` files.

```bash
mkdir mymedialibrary && cd mymedialibrary && mkdir data
curl -O https://raw.githubusercontent.com/MyMediaLibrary/MyMediaLibrary/main/compose.yaml
```

Edit `compose.yaml`, replace `/path/to/your/library` with your actual path, then:

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
      - ./data:/data                        # config.json, library.json, scanner.log
      - /path/to/your/library:/library:ro   # your media library, read-only
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
├── library.json   # library index (generated by the scanner)
├── config.json    # configuration (folders, Jellyseerr, UI, language)
└── scanner.log    # rotating logs (5 MB max, 3 backups)
```

---

### ⚙️ Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `LIBRARY_PATH` | ✅ | — | Root path of media library |
| `SCAN_CRON` | ❌ | `0 3 * * *` | Auto-scan schedule (cron format) |
| `LOG_LEVEL` | ❌ | `INFO` | Log level (`INFO` / `DEBUG`) |
| `APP_PASSWORD` | ❌ | — | Optional password (enables login screen) |

All other settings (folders, Jellyseerr, UI preferences) are configurable from the web interface and persisted in `config.json`.

---

### 📂 Library structure

The scanner reads the subdirectories of `LIBRARY_PATH` directly. Each subdirectory is a configurable **folder** (Movies, Series, Anime…).

**Recommended structure:**

```
/mnt/media/library/          ← LIBRARY_PATH
├── movies/
│   ├── The Dark Knight (2008)/
│   │   ├── The Dark Knight (2008).mkv
│   │   └── The Dark Knight (2008).nfo
│   └── Inception (2010)/
│       └── Inception (2010).mkv
├── tv/
│   └── Breaking Bad/
│       ├── Season 01/
│       │   └── Breaking.Bad.S01E01.mkv
│       └── tvshow.nfo
└── anime/
    └── Demon Slayer/
```

**Docker volume options:**

```yaml
# Option A — library on the same host
volumes:
  - /mnt/media/library:/library:ro
  - ./data:/data

# Option B — network mount (NFS, SMB)
volumes:
  - /mnt/nas/media:/library:ro
  - ./data:/data
```

`.nfo` files (Kodi/Jellyfin format) are read automatically to extract title, year, synopsis, resolution, codec, and runtime. Without `.nfo`, the title is derived from the folder name.

---

### 🗂️ Streaming providers

Provider name normalization (e.g. `"Amazon Prime Video"` → `"Prime Video"`) and logos are defined in `app/providers.json`, bundled in the Docker image.

To contribute a correction to the reference file: open a PR on the GitHub repository.

---

### 🔒 Authentication

If `APP_PASSWORD` is set, the password is prompted before the interface is shown, including during the initial setup wizard.

Without `APP_PASSWORD`, the interface is accessible without authentication — use a reverse proxy (NPM, Traefik) or VPN/Tailscale for network-level protection.

---

### 🤝 Contributing & License

Contributions welcome — open an issue or PR. MIT licensed.
