# Documentation — MyMediaLibrary (FR)

## Table des matières

1. [Vue d'ensemble](#1-vue-densemble)
2. [Architecture technique](#2-architecture-technique)
3. [Installation](#3-installation)
4. [Structure de la bibliothèque](#4-structure-de-la-bibliothèque)
5. [Configuration initiale](#5-configuration-initiale)
6. [Interface web](#6-interface-web)
7. [Filtres](#7-filtres)
8. [Plateformes de streaming](#8-plateformes-de-streaming)
9. [Score de qualité](#9-score-de-qualité)
10. [Statistiques](#10-statistiques)
11. [Paramètres](#11-paramètres)

---

## 1. Vue d'ensemble

**MyMediaLibrary** est un tableau de bord auto-hébergé pour visualiser une bibliothèque de films et séries. Il tourne dans un unique conteneur Docker sans base de données.

**Flux :**
1. Le scanner Python lit les sous-dossiers de `LIBRARY_PATH`, parse les fichiers `.nfo` (format Kodi/Jellyfin/Emby) et génère `data/library.json`.
2. L'interface web (vanilla JS) charge `library.json` et affiche les tuiles avec filtres, tri et statistiques.
3. La configuration est persistée dans `data/config.json` (dossiers, Jellyseerr, préférences UI).

---

## 2. Architecture technique

### Stack

- **Conteneur** : nginx:alpine + Python 3 + dcron (image unique)
- **Frontend** : HTML/CSS + vanilla JS (aucun framework)
- **Backend** : serveur Python minimal (`scanner/server.py`) — routes API REST + service des fichiers statiques
- **Scanner** : Python (`scanner/scan.py`) — lecture `.nfo`, calcul métadonnées, écriture `library.json`
- **Persistance** : `data/config.json` (config), `data/library.json` (index), `localStorage` (état UI)


### Internationalisation

Fichiers `app/i18n/fr.json` et `app/i18n/en.json`. Fonction `t('namespace.key')` avec support `{n}` et pluriel `{s}`. La langue est persistée dans `config.json` côté serveur et dans `localStorage` côté client.

---

## 3. Installation

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

## 4. Structure de la bibliothèque

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

## 5. Configuration initiale

L'assistant de configuration s'affiche au premier démarrage (ou si `config.json` est absent/vide).

**Étapes :**

1. **Écran d'accueil** — description de l'application, choix de la langue, bouton "Commencer".
2. **Dossiers** — liste des sous-dossiers de `LIBRARY_PATH`, assigner un type à chacun (Films / Séries / Ignorer). Les dossiers non configurés sont ignorés au scan. Le bouton "Suivant" est désactivé tant qu'aucun dossier media (Films ou Séries) n'est configuré.
3. **Jellyseerr** (optionnel) — URL + clé API, bouton de test de connexion.
4. **Résumé + Scan** — affiche la configuration, bouton "Lancer le scan" qui démarre le scan initial et redirige vers la bibliothèque à la fin.

---

## 6. Interface web

### Vues

- **Bibliothèque** — grille de tuiles (poster, titre, année, résolution, codec, plateformes) + vue tableau
- **Statistiques** — graphiques détaillés
- **Scanner** — déclenchement manuel + log du dernier scan

### Barre latérale (desktop) / panneau mobile

Affiche les filtres actifs et permet de naviguer dans la bibliothèque. Sur mobile, accessible via le bouton filtre en bas de l'écran.

### Tuiles

Chaque tuile affiche :
- Poster local (si disponible) ou placeholder
- Titre + année
- Résolution (badge coloré : 4K, 1080p, 720p…)
- Logos des plateformes de streaming (si Jellyseerr activé)
- Nombre de saisons/épisodes (séries)
- Synopsis au survol (optionnel, activable dans les paramètres)

### Thème et langue

- Thème clair/sombre, persisté via un interrupteur dans la barre latérale (icône soleil/lune)
- Langue FR/EN sélectionnable dans les paramètres système

---

## 7. Filtres

### Filtres en pastilles (faible cardinalité)

- **Type** — Tous / Films / Séries
- **Résolution** — Toutes / 4K / 1080p / 720p / SD
- **Groupe** — par dossier configuré

Ces filtres sont rendus comme des boutons en pastille (sélection unique).

### Filtres en dropdown multi-select (haute cardinalité)

- **Streaming (FR)** — plateformes disponibles (Netflix, Prime Video…) + option "Aucune plateforme"
- **Codec vidéo** — H.264, H.265/HEVC, AV1…
- **Codec audio** — AAC, AC3, EAC3, TrueHD…

Ces filtres utilisent une liste déroulante avec cases à cocher. La sélection est multiple (logique OR : un élément passe s'il correspond à **au moins un** des codecs/plateformes sélectionnés). L'état sélectionné est persisté dans `localStorage`.

#### Compteurs dynamiques

Les compteurs affichés dans chaque dropdown correspondent aux items correspondant aux **autres filtres actifs** (logique "faceted search" — `baseItems(except)` exclut le filtre courant du calcul).

---

## 8. Plateformes de streaming

L'enrichissement streaming est optionnel et repose sur **Jellyseerr**.

### Configuration

URL + clé API dans les paramètres (onglet Jellyseerr) ou lors de la configuration initiale. Un bouton "Tester la connexion" valide les identifiants.

### Normalisation

Les noms des plateformes retournés par Jellyseerr sont normalisés via `app/providers.json` (ex. `"Amazon Prime Video"` → `"Prime Video"`). Ce fichier associe également un logo SVG à chaque plateforme.

### Visibilité

Chaque plateforme peut être masquée dans les paramètres (onglet Jellyseerr → "Visibilité des plateformes"). Les plateformes masquées n'apparaissent pas dans les tuiles ni dans le filtre.

---

## 9. Score de qualité

Chaque média reçoit un **score global de qualité sur 100**. Ce score est calculé à partir de plusieurs critères techniques pour aider à identifier les meilleurs fichiers, repérer les points faibles et prioriser les améliorations de la bibliothèque.

### Structure du score

| Critère | Points |
|---|---:|
| Vidéo | 50 |
| Audio | 20 |
| Langues | 15 |
| Taille | 15 |
| **Total** | **100** |

### Critères détaillés

#### 🎥 Vidéo (50)

| Sous-critère | Valeur | Points |
|---|---|---:|
| Résolution | 2160p | 25 |
| Résolution | 1080p | 20 |
| Résolution | 720p | 10 |
| Résolution | SD | 5 |
| Résolution | Inconnue | 8 |
| Codec | AV1 / HEVC / H.265 | 15 |
| Codec | H.264 / AVC | 10 |
| Codec | Ancien (MPEG-2, VC-1, Xvid, DivX) | 3 |
| Codec | Inconnu | 6 |
| HDR | Dolby Vision | 10 |
| HDR | HDR10+ | 8 |
| HDR | HDR10 / HLG | 5 |
| HDR | SDR | 0 |
| HDR | Inconnu | 0 |

#### 🔊 Audio (20)

| Codec audio | Points |
|---|---:|
| TrueHD / Atmos | 20 |
| DTS-HD | 18 |
| DTS | 15 |
| EAC3 | 12 |
| AC3 | 10 |
| AAC | 6 |
| MP3 / MP2 | 3 |
| Inconnu | 8 |

#### 🌍 Langues (15)

| Profil linguistique | Points |
|---|---:|
| MULTI (français + autres) | 15 |
| Français uniquement | 10 |
| Version originale uniquement (VO) | 5 |
| Inconnu | 3 |

#### 💾 Taille (15)

| État de cohérence | Points |
|---|---:|
| Cohérente | 15 |
| Trop grande | 8 |
| Trop petite | 5 |
| Inconnue | 5 |

##### Repères de taille (zone optimale)

| Résolution | Codec | Taille optimale |
|---|---|---|
| 1080p | H.265 | 2–10 GB |
| 1080p | H.264 | 4–15 GB |
| 4K | H.265 | 8–25 GB |
| 720p | Tous | 2–6 GB |
| SD | Tous | 500 MB – 2 GB |

### Pénalités

Des pénalités sont appliquées pour corriger les incohérences et éviter qu'un profil technique faible conserve un score trop élevé.

| Situation | Pénalité | Explication |
|---|---|---|
| Vidéo excellente + audio faible | -10 / -5 | Un très bon rendu visuel avec un son faible crée un déséquilibre perceptible à l'usage. |
| Haute résolution + codec ancien | -8 / -4 | Une vidéo HD/4K encodée avec un codec ancien indique souvent une compression moins efficace. |
| Bonne vidéo + peu de langues | -5 | Le fichier est de bonne qualité, mais reste moins accessible pour plusieurs profils d'utilisateurs. |
| Taille incohérente | -5 | Une taille trop faible ou trop élevée pour le profil attendu peut signaler une qualité irrégulière. |

> Pénalité maximale appliquée : 20 points.

### Score final

```text
Score final = Score de base - Pénalités
Borné entre 0 et 100
```

### Niveaux de qualité

```text
0–20   → Level 1
21–40  → Level 2
41–60  → Level 3
61–80  → Level 4
81–100 → Level 5
```

### Intégration UI

Le score qualité est visible dans toute l'interface :
- badge sur les tuiles
- colonne tableau
- export CSV
- statistiques

### Infobulle

Au survol du badge, une infobulle détaillée est affichée :
- détail complet par catégorie
- pénalités appliquées

### Filtres

Le scoring s'intègre à des filtres dédiés :
- pastilles par niveaux
- couleurs cohérentes entre niveaux
- multi-sélection
- logique inclure / exclure

### Statistiques

Les statistiques incluent une distribution des scores pour analyser la qualité globale de la bibliothèque.

---

## 10. Statistiques

L'onglet Statistiques affiche :

- **Résumé global** — nombre total d'items, fichiers, taille disque
- **Par type** — répartition Films / Séries
- **Résolution** — camembert
- **Codec vidéo** — camembert
- **Codec audio** — camembert
- **Années de sortie** — histogramme par année ou par décennie
- **Évolution mensuelle** — courbe des ajouts par mois (taille et/ou nombre d'items), périodes : tout / 12 mois / 30 jours
- **Répartition par groupe / dossier** — taille ou nombre
- **Streaming** — disponibilité par plateforme, répartition par groupe

Tous les graphiques sont filtrés selon les filtres actifs de la bibliothèque.

---

## 11. Paramètres

Accessible via l'icône ⚙️ en bas de la barre latérale.

### Onglet Bibliothèque

- Chemin de la bibliothèque (`LIBRARY_PATH`, lecture seule si défini via compose.yaml)
- Afficher/masquer Films ou Séries
- Tableau des dossiers détectés : type (Films/Séries/Ignorer) + visibilité individuelle

### Onglet Jellyseerr

- Activer/désactiver l'enrichissement
- URL + clé API + test de connexion
- Visibilité de chaque plateforme (visible/masqué)

### Onglet Système

- Langue (FR/EN)
- Couleur d'accent (sélecteur + reset)
- Synopsis au survol (on/off)
- Scan automatique (cron)
- Niveau de log
- Version

---
