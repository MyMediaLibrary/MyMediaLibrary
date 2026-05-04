# Documentation — MyMediaLibrary (FR)

## Table des matières

1. [Vue d'ensemble](#1-vue-densemble)
2. [Architecture technique](#2-architecture-technique)
3. [Installation](#3-installation)
4. [Structure de la bibliothèque](#4-structure-de-la-bibliothèque)
5. [Configuration initiale](#5-configuration-initiale)
6. [Scanner](#6-scanner)
7. [Modèles de données](#7-modèles-de-données)
8. [Interface web](#8-interface-web)
9. [Filtres](#9-filtres)
10. [Plateformes de streaming](#10-plateformes-de-streaming)
11. [Score de qualité](#11-score-de-qualité)
12. [Recommandations](#12-recommandations)
13. [Statistiques](#13-statistiques)
14. [Paramètres](#14-paramètres)

---

## 1. Vue d'ensemble

**MyMediaLibrary** est un tableau de bord auto-hébergé pour visualiser une bibliothèque de films et séries. Il tourne dans un unique conteneur Docker sans base de données.

**Flux :**
1. Le scanner Python lit les sous-dossiers de `/library`, parse les fichiers `.nfo` (format Kodi/Jellyfin/Emby) et génère `data/library.json`.
2. Les phases optionnelles enrichissent les données : Seerr, score qualité, inventaire et recommandations.
3. L'interface web (vanilla JS) charge les fichiers JSON générés et affiche bibliothèque, filtres, statistiques et recommandations.
4. La configuration est persistée dans `conf/config.json` (dossiers, Seerr, préférences UI).

---

## 2. Architecture technique

### Stack

- **Conteneur** : nginx:alpine + Python 3 + dcron (image unique)
- **Frontend** : HTML/CSS + vanilla JS (aucun framework)
- **Backend** : serveur Python minimal (`backend/scanner.py`) — routes API REST + service des fichiers statiques
- **Scanner** : Python (`backend/scanner.py`) — lecture `.nfo`, calcul métadonnées, écriture `library.json`
- **Persistance** : `conf/config.json` (config), `data/library.json` (index), `localStorage` (état UI)


### Internationalisation

Fichiers `app/i18n/fr.json` et `app/i18n/en.json`. Fonction `t('namespace.key')` avec support `{n}` et pluriel `{s}`. La langue est persistée dans `config.json` côté serveur et dans `localStorage` côté client.

### Fuseau horaire (`TZ`)

Au démarrage, l'entrypoint exporte `TZ="${TZ:-UTC}"` avant de lancer les services de scan. En pratique, l'API scanner, le scan initial et les scans cron utilisent tous `TZ` (par défaut `UTC` si absent).

Impacts principaux :
- horodatages des logs (ex: `scanner.log`)
- timestamps techniques (états de scan, dates d'exécution)
- affichages UI dépendants des timestamps

---

## 3. Installation

**Prérequis :** Docker + Docker Compose, bibliothèque avec fichiers `.nfo`.

```bash
mkdir mymedialibrary && cd mymedialibrary && mkdir data conf
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
      - ./data:/data                             # library.json, inventaire, recommandations, scanner.log
      - ./conf:/conf                             # config.json, providers, règles, .secrets
      - /chemin/vers/ta/mediatheque:/library:ro  # médiathèque en lecture seule
    environment:
      TZ: Europe/Paris
    restart: unless-stopped
```

### Variables d'environnement

| Variable | Obligatoire | Défaut | Description |
|---|---|---|---|
| `TZ` | ❌ | `UTC` | Fuseau horaire du conteneur (logs et timestamps) |

Montez toujours vos médias dans `/library` en lecture seule. L'authentification par mot de passe se configure dans l'onboarding puis dans **Paramètres > Configuration** ; seul un hash est stocké dans `/conf/.secrets`. Le cron de scan automatique et le niveau de log se configurent dans **Paramètres > Système** et sont persistés dans `config.json`.

### Stockage runtime

- `/data` contient les fichiers générés : `library.json`, `library_inventory.json`, `recommendations.json`, `scanner.log`.
- `/conf` contient la configuration persistante : `config.json`, `providers_mapping.json`, `providers_logo.json`, `recommendations_rules.json`, `.secrets`.
- `/library` est le point de montage fixe des médias.
- `/tmp` est interne au conteneur et contient notamment `scan.lock`.

Au démarrage, l'application migre automatiquement les anciens fichiers de configuration :

- `/data/config.json` → `/conf/config.json`
- `/data/providers_mapping.json` → `/conf/providers_mapping.json`
- `/data/providers_logo.json` → `/conf/providers_logo.json`
- `/data/recommendations_rules.json` → `/conf/recommendations_rules.json`
- `/app/.secrets` → `/conf/.secrets`

Après migration réussie, les anciens fichiers sont supprimés. Si une source legacy et une destination existent avec un contenu différent, le démarrage est interrompu pour éviter d'écraser une configuration utilisateur.

### Mise à jour

```bash
docker compose pull && docker compose up -d
```

---

## 4. Structure de la bibliothèque

Le scanner lit les **sous-dossiers directs** de `/library`. Chaque sous-dossier est un **dossier** auquel on assigne un type (Films, Séries, Ignorer) depuis l'interface.

### Structure recommandée

```
/library/                    ← racine média fixe
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
  - ./conf:/conf
```

---

## 5. Configuration initiale

L'assistant de configuration s'affiche au premier démarrage (ou si `config.json` est absent/vide dans `./conf`).

**Étapes :**

1. **Écran d'accueil** — description de l'application, choix de la langue, bouton "Commencer".
2. **Dossiers** — liste des sous-dossiers de `/library`, assigner un type à chacun (Films / Séries / Ignorer). Les dossiers non configurés sont ignorés au scan. Le bouton "Suivant" est désactivé tant qu'aucun dossier media (Films ou Séries) n'est configuré.
3. **Seerr** (optionnel) — URL + clé API, bouton de test de connexion.
4. **Résumé + Scan** — affiche la configuration, bouton "Lancer le scan" qui démarre le scan initial et redirige vers la bibliothèque à la fin.

---

## 6. Scanner

Le scanner est le composant central de MyMediaLibrary. Il lit le filesystem, parse les fichiers `.nfo` et produit les fichiers JSON consommés par l'interface web.

### Vue d'ensemble

Le scanner (`scanner.py`) analyse le contenu de `/library` et génère :

| Fichier | Rôle |
|---|---|
| `/data/library.json` | Index principal — chargé par l'interface web |
| `/data/library_inventory.json` | Suivi présence/absence des médias (optionnel, activable dans Paramètres > Système) |
| `/data/recommendations.json` | Recommandations générées (optionnel, nécessite le score qualité) |

Le format détaillé de ces fichiers est décrit dans le chapitre [Modèles de données](#7-modèles-de-données).

### Modes de scan

#### Scan rapide (quick)

- Parcourt le filesystem et parse les fichiers `.nfo`
- Écrit `library.json` de façon incrémentale, dossier par dossier
- Conserve les données enrichies du scan précédent (providers streaming, score qualité)
- N'appelle **pas** Seerr, ne recalcule **pas** les scores, ne met **pas** à jour l'inventaire

#### Scan complet (full)

Enchaîne les phases activées dans l'ordre :

1. **Filesystem + NFO** — lecture des dossiers, parsing des `.nfo`
2. **Seerr** — récupération des plateformes de streaming FR pour chaque titre
3. **Scoring** — calcul du score de qualité (si activé dans les paramètres)
4. **Inventaire** — mise à jour de `library_inventory.json` (si activé dans les paramètres)
5. **Recommandations** — génération de `recommendations.json` (si score et recommandations sont activés)

> Chaque phase lit la sortie de la phase précédente depuis le disque. Les phases sont entièrement séparées.

### Parsing NFO enrichi (v0.3.4)

Le parsing NFO extrait désormais aussi :
- `genres`
- `audio_channels`
- `subtitle_languages`
- `video_bitrate`

Comportement :
- **Films** : champs lus directement depuis le NFO film
- **Séries** : champs techniques lus au niveau épisode puis agrégés vers saison puis série
- **Genres séries** : lus depuis `tvshow.nfo`

Les genres sont normalisés via un mapping externe : `app/mapping_genres.json`.

### Déclencheurs

| Origine | Mode | Déclenchement |
|---|---|---|
| Démarrage du conteneur | Rapide | Automatique via `entrypoint.sh` |
| Assistant de configuration | Rapide | Bouton "Lancer le scan" en fin d'onboarding |
| Bouton "Scan" dans l'UI | Complet | Via la page Scanner |
| Cron | Complet | Planification automatique (Paramètres > Système) |
| Modification des dossiers | Rapide | Automatique après une sauvegarde dans Paramètres > Bibliothèque |

### Verrou anti-concurrence

Un seul scan peut tourner à la fois. Le scanner utilise un verrou fichier inter-processus (`/tmp/scan.lock`) pour coordonner tous les modes de déclenchement (démarrage, cron, UI) et éviter des écritures simultanées corrompant `library.json`. `/tmp` reste interne au conteneur et ne doit pas être monté.

Si un scan est déjà en cours :
- Un scan déclenché via l'UI reçoit une réponse d'erreur (HTTP 409)
- Un scan planifié (cron ou démarrage) est ignoré avec un message dans les logs

### Logs

Les logs sont disponibles dans `data/scanner.log` (chemin hôte) et consultables dans Paramètres > Système.

| Niveau | Contenu |
|---|---|
| `INFO` | Progression des phases, avancement par dossier, durées, statistiques détectées (codecs vidéo/audio, langues, résolutions) |
| `DEBUG` | Détails techniques : résultats Seerr par item, parsing NFO, items non trouvés, détails inventaire |

### Préservation des données (scan rapide)

Lors d'un scan rapide, les données enrichies par les scans complets précédents sont conservées sans être recalculées :

| Champ | Source | Comportement |
|---|---|---|
| `providers` | Phase 2 (Seerr) | Copié depuis le `library.json` existant |
| `providers_fetched` | Phase 2 | Copié depuis le `library.json` existant |
| `quality` | Phase 3 (scoring) | Copié depuis le `library.json` existant |

Le `library.json` existant est chargé **une seule fois** au démarrage du scan, puis utilisé comme référence immuable pour tous les lookups. Les nouveaux items n'ayant pas d'entrée précédente sont créés sans enrichissement — leurs données seront calculées lors du prochain scan complet.

---

## 7. Modèles de données

### `library.json`

Fichier principal consommé par l'interface web. Structure globale :

```json
{
  "scanned_at": "2025-04-14T20:00:00.000000",
  "library_path": "/library",
  "total_items": 3289,
  "categories": ["Movies", "Series"],
  "items": [ ... ]
}
```

Exemple d'item :

```json
{
  "id": "movie:Movies:The.Dark.Knight.2008",
  "path": "Movies/The.Dark.Knight.2008",
  "title": "The Dark Knight",
  "year": "2008",
  "category": "Movies",
  "type": "movie",
  "size": "14.0 GB",
  "resolution": "1080p",
  "codec": "HEVC",
  "audio_codec": "TRUEHD",
  "audio_channels": "5.1",
  "audio_languages": ["fra", "eng"],
  "subtitle_languages": ["fra", "eng"],
  "video_bitrate": 18450000,
  "genres": ["Action", "Crime"],
  "providers": ["Netflix", "Canal+"],
  "quality": {
    "video_details": { "resolution": 20, "codec": 15, "hdr": 0 },
    "audio_details": { "codec": 18, "channels": 8 },
    "video": 35,
    "audio": 26,
    "languages": 15,
    "size": 8,
    "video_w": 35.0,
    "audio_w": 17.3333,
    "languages_w": 15.0,
    "size_w": 8.0,
    "score": 75
  }
}
```

Le champ `id` est la clé stable de chaque item. Format : `{type}:{category}:{nom_du_dossier}`. Il est identique dans `library.json` et `library_inventory.json` pour le même média, ce qui permet le croisement des deux fichiers.

### `library_inventory.json`

Fichier optionnel (activer dans Paramètres > Système) qui conserve l'historique de présence de chaque média et de ses fichiers vidéo à travers les scans successifs.

Champs principaux de chaque item :

| Champ | Description |
|---|---|
| `id` | Identifiant partagé avec `library.json` |
| `status` | `"present"` ou `"missing"` |
| `first_seen_at` | Date de première apparition sur le filesystem (jamais modifiée ensuite) |
| `last_seen_at` | Dernière date à laquelle l'item a été détecté sur le filesystem |
| `last_checked_at` | Date du dernier scan l'ayant évalué (mis à jour même si l'item est absent) |
| `video_files` | Liste des fichiers vidéo avec leur propre historique de présence |

**Logique présent / absent :**

```
present → last_seen_at = maintenant, last_checked_at = maintenant
missing → last_seen_at inchangé,     last_checked_at = maintenant
```

Un item passe à `"missing"` lorsque son dossier n'est plus détecté lors d'un scan complet couvrant tous les dossiers. L'historique est conservé et l'item n'est pas supprimé.

---

## 8. Interface web

### Vues

- **Bibliothèque** — grille de tuiles (poster, titre, année, résolution, codec, plateformes) + vue tableau
- **Statistiques** — graphiques détaillés
- **Recommandations** — actions proposées pour améliorer la médiathèque (si activé)
- **Scanner** — déclenchement manuel + log du dernier scan

### Barre latérale (desktop) / panneau mobile

Affiche les filtres actifs et permet de naviguer dans la bibliothèque. Sur mobile, accessible via le bouton filtre en bas de l'écran.

### Tuiles

Chaque tuile affiche :
- Poster local (si disponible) ou placeholder
- Titre + année
- Résolution (badge coloré : 4K, 1080p, 720p…)
- Logos des plateformes de streaming (si Seerr activé)
- Nombre de saisons/épisodes (séries)
- Synopsis au survol (optionnel, activable dans les paramètres)

### Thème et langue

- Thème clair/sombre, persisté via un interrupteur dans la barre latérale (icône soleil/lune)
- Langue FR/EN sélectionnable dans les paramètres système

---

## 9. Filtres

Les filtres principaux utilisent une architecture unifiée de dropdowns (même comportement desktop/mobile) pour :
- **Type**
- **Par dossier**
- **Genre**
- **Streaming (FR)**
- **Langue audio**
- **Score** (double slider, uniquement si le scoring est activé)
- **Qualité technique** (bloc repliable) :
  - **Résolution**
  - **Codec vidéo**
  - **Codec audio**
  - **Channel audio**

Fonctionnalités communes :
- multi-sélection
- mode **Inclure / Exclure** par filtre
- bouton **Tout sélectionner**
- compteurs dynamiques (logique facettée : calcul avec les autres filtres actifs)
- tri par nombre d'éléments décroissant
- options à 0 masquées
- options actives conservées visibles, même si leur compteur passe à 0
- état des filtres persisté (restauration après reload)

> Le filtre **Type** (Tous / Films / Séries) reste un contrôle rapide dédié.

### Exemple d'usage

1. Ouvrir le filtre **Langues audio**.
2. Sélectionner `Français` + `Anglais` (multi-sélection).
3. Basculer le mode sur **Exclure** pour retirer ces langues.
4. Utiliser **Tout sélectionner** pour cocher/décocher toutes les options visibles.
5. Observer que les options sont triées automatiquement selon le nombre d'éléments correspondant.

---

## 10. Plateformes de streaming

L'enrichissement streaming est optionnel et repose sur **Seerr**.

### Configuration

URL + clé API dans les paramètres (onglet Seerr) ou lors de la configuration initiale. Un bouton "Tester la connexion" valide les identifiants.

### Modèle actuel

- Chaque média contient une liste plate de providers bruts dans `library.json` (`item.providers`).
- L'application applique ensuite un mapping pour déterminer les providers affichés.
- Si un provider brut est non mappé (ou mappé à `null`), il est regroupé sous **Autres**.
- Si un média n'a aucun provider, l'UI affiche **Aucun provider** (comportement spécifique conservé).

### `providers_mapping.json` (fichier clé)

- Le mapping runtime utilisé par l'application est `/conf/providers_mapping.json`.
- Au premier démarrage, ce fichier est initialisé automatiquement depuis le fichier embarqué.
- Ensuite, il n'est **jamais écrasé** automatiquement.
- À la fin d'un enrichissement providers, les nouveaux providers bruts détectés sont ajoutés avec valeur `null`.

Exemple :

```json
{
  "Netflix": "Netflix",
  "Netflix Standard with Ads": "Netflix",
  "Premiere Max": null
}
```

Interprétation :
- mapping non `null` → provider affiché
- mapping `null` → regroupé dans `Autres`

> Point important : pour qu'un provider apparaisse dans la liste des providers activables dans les paramètres, il doit avoir un mapping **non null** dans `providers_mapping.json`.
> Si un provider est à `null`, il est regroupé dans `Autres` et n'est pas sélectionnable individuellement.

### Logos providers

- Les logos sont définis dans `providers_logo.json`.
- Résolution du logo sur le **provider affiché final** (après mapping).
- Si aucun logo n'est trouvé, fallback vers le logo **Autres**.
- Le cas **Aucun provider** garde son icône dédiée (rond rouge barré).

### Personnaliser les providers affichés

1. Ouvrir `/conf/providers_mapping.json`.
2. Modifier les mappings.
3. Recharger l'application (ou redémarrer le conteneur si nécessaire).

Exemple :

```json
{
  "Canal VOD": "Canal+",
  "OCS": "OCS",
  "Rakuten TV": null
}
```

Résultat :
- `Canal VOD` → affiché comme `Canal+`
- `OCS` → affiché comme `OCS`
- `Rakuten TV` → regroupé dans `Autres`

---

## 11. Score de qualité

### Principe

Le score de qualité est un score global **de 0 à 100**.
Il combine 4 composantes : **vidéo**, **audio**, **langues** et **taille**.

### Fonctionnalité optionnelle

Le score qualité est une fonctionnalité **bonus**, **désactivée par défaut**.
Vous pouvez l’activer à tout moment si vous souhaitez une analyse plus fine de votre bibliothèque.

### Activation

Activez le score dans **Paramètres > Configuration** avec le toggle **Activer le score qualité**.

### Configuration

La configuration détaillée se fait dans **Paramètres > Score** :
- poids
- règles vidéo
- règles audio
- langues
- taille (films / séries)

### Valeurs par défaut

Des valeurs par défaut sont fournies et utilisables immédiatement.
Vous pouvez tout modifier puis revenir à la base via le bouton **Réinitialiser**.

### Fonctionnement

Le score est calculé pendant les scans quand la fonctionnalité est activée.
Après modification des paramètres de score, un **recalcul ciblé** est lancé, sans rescanner toute la bibliothèque.

### Philosophie

Le système est volontairement flexible et personnalisable.
Vous pouvez l’adapter à vos priorités, tout en conservant un comportement robuste même avec des données incomplètes (valeurs par défaut de repli).
Les incohérences techniques ne sont plus gérées par des malus et sont traitées séparément par les recommandations.

### Filtre score (slider 0–100, si activé)

Le filtre score n'est pas un dropdown : il utilise un **double slider** avec deux bornes :
- `min`
- `max`

Règle de filtrage :

```text
score >= min && score <= max
```

Le slider met à jour l'aperçu en temps réel pendant le déplacement, puis applique le filtre au relâchement (interaction fluide, sans re-filtrage continu coûteux).

### Gestion des éléments sans score

Option dédiée : **Inclure les éléments sans score**.

Comportement :
- activée par défaut (plage 0–100)
- désactivée automatiquement quand la plage est restreinte depuis l'état par défaut
- peut être réactivée manuellement à tout moment

### Couleurs score (cohérence visuelle)

Le score suit un dégradé homogène dans l'UI :

```text
rouge → orange → jaune → vert clair → vert foncé
```

Ce dégradé est utilisé pour :
- badges score
- repères visuels du slider
- cohérence avec les niveaux statistiques

### Structure du score

| Critère | Points |
|---|---:|
| Vidéo | 50 |
| Audio | 30 |
| Langues | 15 |
| Taille | 15 |
| **Total brut** | **110** |

Le score audio est composé de deux sous-parties :
- `audio_codec_score`
- `audio_channels_score`

Puis :

```text
audio_score = audio_codec_score + audio_channels_score
```

La normalisation finale globale existante reste inchangée.

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

#### 🔊 Audio (30)

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

| Channels audio | Points |
|---|---:|
| 7.1 | 10 |
| 5.1 | 8 |
| 2.0 | 5 |
| 1.0 | 3 |
| Inconnu | 2 |

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

### Score final

```text
Score final = Somme des composantes
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

Dans `library.json`, le détail est stocké dans `quality` avec :
- `video_details` (`resolution`, `codec`, `hdr`)
- `audio_details` (`codec`, `channels`)

### Infobulle

Au survol du badge, une infobulle détaillée est affichée :
- détail complet par catégorie

### Désactivation complète du score (`score.enabled`)

Le paramètre `score.enabled` dans `config.json` permet de couper totalement la fonctionnalité.

Si désactivé :
- le backend bypass complètement le calcul de score pendant le scan
- les champs score sont retirés du `library.json` (pas de dataset mixte score/sans score après un scan)
- le score est masqué dans l'UI (badges, colonne score, infobulle score)
- le slider de filtre score disparaît
- les tris/statistiques liés au score sont désactivés
- les colonnes score sont exclues de l'export CSV

Si réactivé :
- les contrôles UI liés au score réapparaissent immédiatement
- un nouveau scan est nécessaire pour régénérer les scores dans `library.json`

### Comportements clés

- filtres persistants et restaurés après rechargement
- options à 0 masquées (sauf options actives)
- sections de filtres vides masquées automatiquement
- tri dynamique des options selon les counts
- UI réactive immédiatement aux changements de configuration (ex: `score.enabled = false`)

### Statistiques

Les statistiques incluent une distribution des scores pour analyser la qualité globale de la bibliothèque.

---

## 12. Recommandations

Les recommandations transforment l'analyse de la bibliothèque en liste d'actions concrètes : améliorer la qualité, optimiser l'espace disque, détecter les problèmes de données ou repérer des saisons incohérentes.

### Activation

- Nécessite le **score qualité**.
- Activable dans **Paramètres > Configuration**.
- Si le score est désactivé, les recommandations sont automatiquement désactivées.

### Fonctionnement

- Les recommandations sont générées en **phase 5 du scan**.
- Le scan écrit `/data/recommendations.json`.
- `library.json` n'est jamais modifié par cette phase.
- Le fichier est relié à `library.json` via l'identifiant stable du média (`media_ref.id`).

### Moteur

- Règles déterministes, sans IA générative.
- Règles métier simples configurables via `/conf/recommendations_rules.json`.
- Règles structurelles côté backend pour les données manquantes et les incohérences de séries.

### Structure

Chaque recommandation contient :
- le média concerné
- le type
- la priorité
- un message
- une action suggérée

### Types de recommandations

#### Qualité

Signale les scores faibles, codecs anciens ou pistes audio limitées.

#### Gain de place

Repère les fichiers très lourds, les bitrates élevés ou les encodages peu efficaces. La taille affichée est une taille concernée, pas un gain garanti.

#### Langues

Détecte l'absence de français, les médias uniquement en VO ou les sous-titres français manquants.

#### Séries

Repère les saisons incohérentes : résolution, codec, audio, langues, score inférieur ou taille anormalement élevée.

#### Données

Remonte les champs absents, inconnus ou non détectés (résolution, codecs, langues, taille, score).

### Page Recommandations

La page dédiée affiche :
- filtres locaux par **type** et **priorité**
- tri configurable
- affichage compact des infos média
- cartes lisibles sur mobile
- export CSV des recommandations visibles

Les filtres globaux de la bibliothèque s'appliquent aussi aux recommandations.

### Stats Recommandations

L'onglet **Stats > Recommandations** affiche :
- répartition par priorité
- répartition par type
- analyse par dossier
- distribution du nombre de recommandations par média
- distribution des scores
- taille concernée par les recommandations d'espace

Les graphes se recalculent selon les filtres globaux et les filtres locaux recommandations.

### `recommendations.json`

Fichier généré automatiquement dans `/data`. Il contient uniquement les recommandations et ne duplique pas `library.json`. Chaque entrée pointe vers le média via `media_ref.id`.

---

## 13. Statistiques

L'onglet Statistiques est organisé en sous-onglets :

- **Générales**
  - Dossiers
  - Genres (barres horizontales)
  - Fournisseurs
  - Qualité
  - Répartition par année de sortie (pleine largeur)
- **Techniques**
  - Résolution
  - Codec vidéo
  - Codec audio
  - Langues audio
  - Channels audio
- **Évolution**
  - Évolution mensuelle des ajouts (pleine largeur)
- **Recommandations** (si score + recommandations activés)
  - Répartition par priorité et type
  - Analyse par dossier
  - Médias avec recommandations par dossier
  - Nombre de recommandations par média
  - Distribution des scores

Spécificité du graphe **Genres** :
- affichage en **nombre d'éléments**
- **Top 12** + **Autres**
- `Autres` représente les éléments non couverts par le Top 12 (et non la somme brute des genres hors Top 12)

Tous les graphiques sont filtrés selon les filtres actifs de la bibliothèque.

---

## 14. Paramètres

Accessible via l'icône ⚙️ en bas de la barre latérale.

### Onglet Bibliothèque

- Afficher/masquer Films ou Séries
- Tableau des dossiers détectés : type (Films/Séries/Ignorer) + visibilité individuelle

### Onglet Seerr

- Activer/désactiver l'enrichissement
- URL + clé API + test de connexion
- Visibilité des providers affichés (providers mappés ; `Autres` reste géré automatiquement)

### Onglet Système

- Langue (FR/EN)
- Couleur d'accent (sélecteur + reset)
- Synopsis au survol (on/off, **désactivé par défaut**)
- Score de qualité (on/off, **désactivé par défaut**)
- Recommandations (on/off, nécessite le score qualité, **désactivé par défaut**)
- Inventaire brut `library_inventory.json` (on/off, **désactivé par défaut**)
- Scan automatique (cron)
- Niveau de log
- Version

> Le synopsis au survol, le score qualité et l'inventaire sont considérés comme des fonctionnalités avancées : ils sont opt-in et doivent être activés explicitement dans les paramètres.

---
