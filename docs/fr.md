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
12. [Statistiques](#12-statistiques)
13. [Paramètres](#13-paramètres)

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
- **Backend** : serveur Python minimal (`backend/scanner.py`) — routes API REST + service des fichiers statiques
- **Scanner** : Python (`backend/scanner.py`) — lecture `.nfo`, calcul métadonnées, écriture `library.json`
- **Persistance** : `data/config.json` (config), `data/library.json` (index), `localStorage` (état UI)


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
| `TZ` | ❌ | `UTC` | Fuseau horaire du conteneur (logs et timestamps) |
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

## 6. Scanner

Le scanner est le composant central de MyMediaLibrary. Il lit le filesystem, parse les fichiers `.nfo` et produit les fichiers JSON consommés par l'interface web.

### Vue d'ensemble

Le scanner (`scanner.py`) analyse le contenu de `LIBRARY_PATH` et génère :

| Fichier | Rôle |
|---|---|
| `/data/library.json` | Index principal — chargé par l'interface web |
| `/data/library_inventory.json` | Suivi présence/absence des médias (optionnel, activable dans Paramètres > Système) |

Le format détaillé de ces fichiers est décrit dans le chapitre [Modèles de données](#7-modèles-de-données).

### Modes de scan

#### Scan rapide (quick)

- Parcourt le filesystem et parse les fichiers `.nfo`
- Écrit `library.json` de façon incrémentale, dossier par dossier
- Conserve les données enrichies du scan précédent (providers streaming, score qualité)
- N'appelle **pas** Jellyseerr, ne recalcule **pas** les scores, ne met **pas** à jour l'inventaire

#### Scan complet (full)

Enchaîne 4 phases dans l'ordre :

1. **Filesystem + NFO** — lecture des dossiers, parsing des `.nfo`
2. **Jellyseerr** — récupération des plateformes de streaming FR pour chaque titre
3. **Scoring** — calcul du score de qualité (si activé dans les paramètres)
4. **Inventaire** — mise à jour de `library_inventory.json` (si activé dans les paramètres)

> Chaque phase lit la sortie de la phase précédente depuis le disque. Les phases sont entièrement séparées.

### Déclencheurs

| Origine | Mode | Déclenchement |
|---|---|---|
| Démarrage du conteneur | Rapide | Automatique via `entrypoint.sh` |
| Assistant de configuration | Rapide | Bouton "Lancer le scan" en fin d'onboarding |
| Bouton "Scan" dans l'UI | Complet | Via la page Scanner |
| Cron | Complet | Planification automatique (Paramètres > Système) |
| Modification des dossiers | Rapide | Automatique après une sauvegarde dans Paramètres > Bibliothèque |

### Verrou anti-concurrence

Un seul scan peut tourner à la fois. Le scanner utilise un verrou fichier inter-processus (`/data/.scan.lock`) pour coordonner tous les modes de déclenchement (démarrage, cron, UI) et éviter des écritures simultanées corrompant `library.json`.

Si un scan est déjà en cours :
- Un scan déclenché via l'UI reçoit une réponse d'erreur (HTTP 409)
- Un scan planifié (cron ou démarrage) est ignoré avec un message dans les logs

### Logs

Les logs sont disponibles dans `data/scanner.log` (chemin hôte) et consultables dans Paramètres > Système.

| Niveau | Contenu |
|---|---|
| `INFO` | Progression des phases, avancement par dossier, durées, statistiques détectées (codecs vidéo/audio, langues, résolutions) |
| `DEBUG` | Détails techniques : résultats Jellyseerr par item, parsing NFO, items non trouvés, détails inventaire |

### Préservation des données (scan rapide)

Lors d'un scan rapide, les données enrichies par les scans complets précédents sont conservées sans être recalculées :

| Champ | Source | Comportement |
|---|---|---|
| `providers` | Phase 2 (Jellyseerr) | Copié depuis le `library.json` existant |
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
  "library_path": "/mnt/media/library",
  "total_items": 3289,
  "items": [ ... ],
  "meta": { "score_enabled": true }
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
  "audio_languages": ["fra", "eng"],
  "providers": ["Netflix", "Canal+"],
  "quality": { "score": 87, "level": 5 }
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

## 9. Filtres

Les filtres principaux utilisent une architecture unifiée de dropdowns (même comportement desktop/mobile) pour :
- **Dossiers**
- **Résolution**
- **Langues audio**
- **Codecs vidéo**
- **Codecs audio**
- **Plateformes streaming**
- **Score** (double slider, uniquement si le scoring est activé)

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

L'enrichissement streaming est optionnel et repose sur **Jellyseerr**.

### Configuration

URL + clé API dans les paramètres (onglet Jellyseerr) ou lors de la configuration initiale. Un bouton "Tester la connexion" valide les identifiants.

### Modèle actuel

- Chaque média contient une liste plate de providers bruts dans `library.json` (`item.providers`).
- L'application applique ensuite un mapping pour déterminer les providers affichés.
- Si un provider brut est non mappé (ou mappé à `null`), il est regroupé sous **Autres**.
- Si un média n'a aucun provider, l'UI affiche **Aucun provider** (comportement spécifique conservé).

### `providers_mapping.json` (fichier clé)

- Le mapping runtime utilisé par l'application est `/data/providers_mapping.json`.
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

1. Ouvrir `/data/providers_mapping.json`.
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

Le score de qualité est une fonctionnalité **optionnelle** pilotée par `system.enable_score` (valeur par défaut : `false`).
Quand il est activé, chaque média reçoit un **score global de qualité sur 100**. Ce score est calculé à partir de plusieurs critères techniques pour aider à identifier les meilleurs fichiers, repérer les points faibles et prioriser les améliorations de la bibliothèque.

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

### Désactivation complète du score (`enable_score`)

Le paramètre système `enable_score` permet de couper totalement la fonctionnalité.

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
- UI réactive immédiatement aux changements de configuration (ex: `enable_score` OFF)

### Statistiques

Les statistiques incluent une distribution des scores pour analyser la qualité globale de la bibliothèque.

---

## 12. Statistiques

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

## 13. Paramètres

Accessible via l'icône ⚙️ en bas de la barre latérale.

### Onglet Bibliothèque

- Chemin de la bibliothèque (`LIBRARY_PATH`, lecture seule si défini via compose.yaml)
- Afficher/masquer Films ou Séries
- Tableau des dossiers détectés : type (Films/Séries/Ignorer) + visibilité individuelle

### Onglet Jellyseerr

- Activer/désactiver l'enrichissement
- URL + clé API + test de connexion
- Visibilité des providers affichés (providers mappés ; `Autres` reste géré automatiquement)

### Onglet Système

- Langue (FR/EN)
- Couleur d'accent (sélecteur + reset)
- Synopsis au survol (on/off, **désactivé par défaut**)
- Score de qualité (on/off, **désactivé par défaut**)
- Inventaire brut `library_inventory.json` (on/off, **désactivé par défaut**)
- Scan automatique (cron)
- Niveau de log
- Version

> Le synopsis au survol, le score qualité et l'inventaire sont considérés comme des fonctionnalités avancées : ils sont opt-in et doivent être activés explicitement dans les paramètres.

---
