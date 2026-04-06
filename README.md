# 📼 MyMediaLibrary

**[Français](#français) | [English](#english)**

---

<a name="français"></a>
## 🇫🇷 Français

**MyMediaLibrary** est un tableau de bord auto-hébergé pour visualiser votre bibliothèque de films et séries. Il scanne vos fichiers vidéo locaux, lit les métadonnées depuis les fichiers `.nfo` (format Kodi/Jellyfin), et affiche une interface web filtrée dans un unique conteneur Docker.

### ✨ Fonctionnalités

- **Bibliothèque** — vue tuiles et tableau, filtres (type, résolution, codec, provider streaming), recherche, tri, export CSV
- **Métadonnées** — parsing `.nfo` Kodi/Jellyfin : titre, année, résolution, codec, HDR, durée, synopsis, affiches locales
- **Providers streaming** — enrichissement via [Jellyseerr](https://github.com/Fallenbagel/jellyseerr) avec normalisation configurable (`data/providers_map.json`)
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
├── library.json        # index de la bibliothèque (généré par le scanner)
├── config.json         # configuration (dossiers, Jellyseerr, UI, langue)
├── providers_map.json  # normalisation des noms de providers (éditable)
└── scanner.log         # logs rotatifs (5 Mo max, 3 sauvegardes)
```

---

### 🗂️ Personnaliser la normalisation des providers

Au premier démarrage, `./data/providers_map.json` est créé automatiquement à partir du fichier de référence inclus dans l'image. Ce fichier fait correspondre les noms bruts Jellyseerr (ex. `"Amazon Prime Video"`) aux noms affichés dans l'interface (ex. `"Prime Video"`).

Pour personnaliser : éditer `./data/providers_map.json` sur l'hôte, puis relancer un scan `--enrich`. Le fichier existant n'est jamais écrasé lors des mises à jour de l'image.

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

- **Library** — grid and table views, filters (type, resolution, codec, streaming provider), search, sort, CSV export
- **Metadata** — Kodi/Jellyfin `.nfo` parsing: title, year, resolution, codec, HDR, runtime, synopsis, local posters
- **Streaming providers** — enrichment via [Jellyseerr](https://github.com/Fallenbagel/jellyseerr) with configurable normalization (`data/providers_map.json`)
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
├── library.json        # library index (generated by the scanner)
├── config.json         # configuration (folders, Jellyseerr, UI, language)
├── providers_map.json  # provider name normalization (editable)
└── scanner.log         # rotating logs (5 MB max, 3 backups)
```

---

### 🗂️ Customizing provider normalization

On first start, `./data/providers_map.json` is automatically created from the reference file bundled in the image. This file maps raw Jellyseerr provider names (e.g. `"Amazon Prime Video"`) to the display names shown in the UI (e.g. `"Prime Video"`).

To customize: edit `./data/providers_map.json` on the host, then trigger an `--enrich` scan. The existing file is never overwritten when updating the image.

To contribute a correction to the reference file: open a PR on the GitHub repository.

---

### 🔒 Authentication

If `APP_PASSWORD` is set, the password is prompted before the interface is shown, including during the initial setup wizard.

Without `APP_PASSWORD`, the interface is accessible without authentication — use a reverse proxy (NPM, Traefik) or VPN/Tailscale for network-level protection.

---

### 🤝 Contributing & License

Contributions welcome — open an issue or PR. MIT licensed.
