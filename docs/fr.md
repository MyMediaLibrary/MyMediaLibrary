# Documentation — MyMediaLibrary (FR)

## Table des matières

1. [Vue d'ensemble](#1-vue-densemble)
2. [Installation](#2-installation)
3. [Structure de la bibliothèque](#3-structure-de-la-bibliothèque)
4. [Onboarding](#4-onboarding)
5. [Interface web](#5-interface-web)
6. [Filtres](#6-filtres)
7. [Providers streaming](#7-providers-streaming)
8. [Statistiques](#8-statistiques)
9. [Paramètres](#9-paramètres)
10. [Architecture technique](#10-architecture-technique)

---

## 1. Vue d'ensemble

**MyMediaLibrary** est un tableau de bord auto-hébergé pour visualiser une bibliothèque de films et séries. Il tourne dans un unique conteneur Docker sans base de données.

**Flux :**
1. Le scanner Python lit les sous-dossiers de `LIBRARY_PATH`, parse les fichiers `.nfo` (format Kodi/Jellyfin/Emby) et génère `data/library.json`.
2. L'interface web (vanilla JS) charge `library.json` et affiche les tuiles avec filtres, tri et statistiques.
3. La configuration est persistée dans `data/config.json` (dossiers, Jellyseerr, préférences UI).

---

## 2. Installation

**Prérequis :** Docker + Docker Compose, bibliothèque avec fichiers `.nfo`.

```bash
mkdir mymedialibrary && cd mymedialibrary && mkdir data
curl -O https://raw.githubusercontent.com/MyMediaLibrary/MyMediaLibrary/main/compose.yaml
# éditer compose.yaml — ajuster le chemin du volume
docker compose up -d
```

Accéder à `http://localhost:8094`.

### compose.yaml

```yaml
services:
  mymedialibrary:
    image: ghcr.io/mymedialibrary/mymedialibrary:latest
    container_name: mymedialibrary
    ports:
      - "8094:80"
    volumes:
      - ./data:/data                             # config.json, library.json, scanner.log
      - /chemin/vers/ta/mediatheque:/library:ro  # médiathèque en lecture seule
    environment:
      LIBRARY_PATH: /library
      # APP_PASSWORD: ""
    restart: unless-stopped
```

### Variables d'environnement

| Variable | Obligatoire | Défaut | Description |
|---|---|---|---|
| `LIBRARY_PATH` | ✅ | — | Chemin racine de la bibliothèque dans le conteneur |
| `APP_PASSWORD` | ❌ | — | Mot de passe (active l'écran de connexion) |

Le cron de scan automatique et le niveau de log se configurent dans **Paramètres > Système** et sont persistés dans `config.json`.

### Mise à jour

```bash
docker compose pull && docker compose up -d
```

---

## 3. Structure de la bibliothèque

Le scanner lit les **sous-dossiers directs** de `LIBRARY_PATH`. Chaque sous-dossier est un **dossier** auquel on assigne un type (Films, Séries, Ignorer) depuis l'interface.

### Structure recommandée

```
/library/                    ← LIBRARY_PATH
├── movies/
│   ├── Film (2010)/
│   │   ├── Film.mkv
│   │   └── Film.nfo
│   └── ...
├── series/
│   ├── Serie/
│   │   ├── tvshow.nfo
│   │   ├── Season 01/
│   │   │   ├── Serie - S01E01.mkv
│   │   │   └── Serie - S01E01.nfo
│   │   └── ...
│   └── ...
└── anime/
    └── ...
```

### Fichiers .nfo

Les fichiers `.nfo` (format Kodi/Jellyfin/Emby) sont lus automatiquement pour extraire :
- Titre, année, synopsis, durée
- Résolution, codec vidéo, codec audio, HDR
- Affiches locales (poster.jpg/png adjacent au .nfo)

Sans `.nfo`, le titre est extrait du nom du dossier (ex. `Film (2010)` → titre `Film`, année `2010`).

### Plusieurs sources

```yaml
volumes:
  - /nas1/movies:/library/movies:ro
  - /nas2/series:/library/series:ro
  - ./data:/data
environment:
  LIBRARY_PATH: /library
```

---

## 4. Onboarding

L'assistant de configuration s'affiche au premier démarrage (ou si `config.json` est absent/vide).

**Étapes :**

1. **Écran d'accueil** — description de l'application, choix de la langue, bouton "Commencer".
2. **Dossiers** — liste des sous-dossiers de `LIBRARY_PATH`, assigner un type à chacun (Films / Séries / Ignorer). Les dossiers non configurés sont ignorés au scan. Le bouton "Suivant" est désactivé tant qu'au moins un dossier est non configuré.
3. **Jellyseerr** (optionnel) — URL + clé API, bouton de test de connexion.
4. **Résumé + Scan** — affiche la configuration, bouton "Lancer le scan" qui démarre le scan initial et redirige vers la bibliothèque à la fin.

---

## 5. Interface web

### Vues

- **Bibliothèque** — grille de tuiles (poster, titre, année, résolution, codec, providers) + vue tableau
- **Statistiques** — graphiques détaillés
- **Scanner** — déclenchement manuel + log du dernier scan

### Barre latérale (desktop) / panneau mobile

Affiche les filtres actifs et permet de naviguer dans la bibliothèque. Sur mobile, accessible via le bouton filtre en bas de l'écran.

### Tuiles

Chaque tuile affiche :
- Poster local (si disponible) ou placeholder
- Titre + année
- Résolution (badge coloré : 4K, 1080p, 720p…)
- Logos des providers streaming (si Jellyseerr activé)
- Nombre de saisons/épisodes (séries)
- Synopsis au survol (optionnel, activable dans les paramètres)

### Thème et langue

- Thème clair/sombre, persisté via un toggle dans la sidebar (icône soleil/lune)
- Langue FR/EN sélectionnable dans les paramètres système

---

## 6. Filtres

### Filtres en pills (faible cardinalité)

- **Type** — Tous / Films / Séries
- **Résolution** — Toutes / 4K / 1080p / 720p / SD
- **Groupe** — par dossier configuré

Ces filtres sont rendus comme des boutons pills (sélection unique).

### Filtres en dropdown multi-select (haute cardinalité)

- **Streaming (FR)** — providers disponibles (Netflix, Prime Video…) + option "Aucun provider"
- **Codec vidéo** — H.264, H.265/HEVC, AV1…
- **Codec audio** — AAC, AC3, EAC3, TrueHD…

Ces filtres utilisent un dropdown avec checkboxes. La sélection est multiple (logique OR : un item passe s'il correspond à **au moins un** des codecs/providers sélectionnés). L'état sélectionné est persisté dans `localStorage`.

#### Compteurs dynamiques

Les compteurs affichés dans chaque dropdown correspondent aux items correspondant aux **autres filtres actifs** (logique "faceted search" — `baseItems(except)` exclut le filtre courant du calcul).

---

## 7. Providers streaming

L'enrichissement streaming est optionnel et repose sur **Jellyseerr**.

### Configuration

URL + clé API dans les paramètres (onglet Jellyseerr) ou lors de l'onboarding. Un bouton "Tester la connexion" valide les identifiants.

### Normalisation

Les noms de providers retournés par Jellyseerr sont normalisés via `app/providers.json` (ex. `"Amazon Prime Video"` → `"Prime Video"`). Ce fichier associe également un logo SVG à chaque provider.

### Visibilité

Chaque provider peut être masqué dans les paramètres (onglet Jellyseerr → "Visibilité des providers"). Les providers masqués n'apparaissent pas dans les tuiles ni dans le filtre.

---

## 8. Statistiques

L'onglet Statistiques affiche :

- **Résumé global** — nombre total d'items, fichiers, taille disque
- **Par type** — répartition Films / Séries
- **Résolution** — camembert
- **Codec vidéo** — camembert
- **Codec audio** — camembert
- **Années de sortie** — histogramme par année ou par décennie
- **Évolution mensuelle** — courbe des ajouts par mois (taille et/ou nombre d'items), périodes : tout / 12 mois / 30 jours
- **Répartition par groupe / dossier** — taille ou nombre
- **Streaming** — disponibilité par provider, répartition par groupe

Tous les graphiques sont filtrés selon les filtres actifs de la bibliothèque.

---

## 9. Paramètres

Accessible via l'icône ⚙️ en bas de la sidebar.

### Onglet Bibliothèque

- Chemin de la bibliothèque (`LIBRARY_PATH`, lecture seule si défini via compose.yaml)
- Afficher/masquer Films ou Séries
- Tableau des dossiers détectés : type (Films/Séries/Ignorer) + visibilité individuelle

### Onglet Jellyseerr

- Activer/désactiver l'enrichissement
- URL + clé API + test de connexion
- Visibilité de chaque provider (visible/masqué)

### Onglet Système

- Langue (FR/EN)
- Couleur d'accent (sélecteur + reset)
- Synopsis au survol (on/off)
- Scan automatique (cron)
- Niveau de log
- Version

---

## 10. Architecture technique

### Stack

- **Conteneur** : nginx:alpine + Python 3 + dcron (image unique)
- **Frontend** : HTML/CSS + vanilla JS (aucun framework)
- **Backend** : serveur Python minimal (`scanner/server.py`) — routes API REST + service des fichiers statiques
- **Scanner** : Python (`scanner/scan.py`) — lecture `.nfo`, calcul métadonnées, écriture `library.json`
- **Persistance** : `data/config.json` (config), `data/library.json` (index), `localStorage` (état UI)


### Internationalisation

Fichiers `app/i18n/fr.json` et `app/i18n/en.json`. Fonction `t('namespace.key')` avec support `{n}` et pluriel `{s}`. La langue est persistée dans `config.json` côté serveur et dans `localStorage` côté client.
