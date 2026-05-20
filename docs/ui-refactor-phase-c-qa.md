# UI Refactor Phase C — QA Report

Branch : `dev-ui-refactor`
Date : 2026-05-20

---

## Périmètre Phase C

Intégration progressive du langage visuel Claude Design via `design-system.css` uniquement.
Commits : C2 → C2b → C3 → C5 → C4 → C6 → C7 → C8 → C9 → C10 → C11 + QA fixes.

---

## Résultat global

| Catégorie | Statut |
|-----------|--------|
| Périmètre fichiers respecté | ✅ |
| Tokens dark/light cohérents | ✅ |
| Shadows tokenisées | ✅ |
| Tests 94/94 | ✅ |
| Incohérences corrigées | ✅ (3 fixes QA) |

---

## Vérifications réalisées

### Périmètre des fichiers
Seuls ces fichiers ont été modifiés en Phase C :
- `app/css/design-system.css` — tous les commits C2→C11 + QA fixes
- `app/js/app.js` — C2b : 1 constante `_DEFAULT_ACCENT`
- `tests/frontend/unit/app_source_guards.test.mjs` — adaptation post-B1
- `docs/` — mockups et documentation uniquement

`app.css`, `stats.css`, `index.html` et l'ensemble du JS applicatif : **non modifiés**.

### Cohérence `--border-soft` dark/light
- Dark : `--border-soft` = `#1e2333` < `--border` = `#252b3b` → plus sombre = plus subtil ✓
- Light : `--border-soft` = `#ecedf2` > `--border` = `#e3e6ee` → plus clair = plus subtil ✓

### Override shadows opérationnel
`design-system.css` chargé après `app.css` — ses `:root` ont priorité.
Toutes les `box-shadow: rgba(0,0,0,...)` ciblées sont remplacées par les versions teintées slate.

---

## Anomalies identifiées et traitées

### 🐛 Fix 1 — `.scan-log-panel` / `.scan-log-header` (oubli C11)
**Problème** : border restait `var(--border)` alors que tous les autres panels avaient été migrés à `--border-soft`.  
**Correction** : `border-color: var(--border-soft)` + `border-bottom-color: var(--border-soft)` ajoutés dans la section QA fixes.

### 🐛 Fix 2 — `#cfgAuthBlock` border-top (oubli C9)
**Problème** : `border-top-color` de la section auth settings restait sur `var(--border)`, incohérent avec tous les autres séparateurs de la modale migrés en C9.  
**Correction** : `#cfgAuthBlock { border-top-color: var(--border-soft) }` ajouté.

### 🐛 Fix 3 — Couleurs scan hardcodées
**Problème** : `.scan-status-dot.done/.error` et `.log-ok/.log-err` utilisaient `#34d399` / `#ff6a6a` hardcodés, non adaptés au light mode.  
**Correction** : `var(--color-ok)` / `var(--color-danger)` — tokens sémantiques introduits en C2.

---

## Points d'attention (non bloquants)

### ⚠️ `--shadow-sm` très atténué
La nouvelle valeur (`0 1px 2px rgba(15,23,42,.04)`) est beaucoup plus légère que l'originale (`0 1px 4px rgba(0,0,0,.35)`). Les éléments concernés (slider thumbs) restent lisibles grâce à leur `border: 2px solid var(--accent)`. Choix design assumé.

### ⚠️ `--shadow` == `--shadow-md` (redondance)
Ces deux tokens ont la même valeur. `--shadow` est le "bare token" introduit en C2 pour les nouveaux usages ; `--shadow-md` préexistait dans `app.css`. Redondance acceptable, pas d'impact fonctionnel.

---

## Dettes techniques pré-existantes (hors scope Phase C)

Identifiées dans `readiness.md`, non introduites par la Phase C, à traiter en Phase D :

| Élément | Localisation | Impact |
|---------|-------------|--------|
| `#4ecdc4` (size-tag) | `app.css:429,448,584` | Couleur non adaptée light mode |
| `#a78bfa` (group-tag) | `app.css:431,453` | Couleur non adaptée light mode |
| `#ea580c` (badge-hdr) | `app.css:240` | Orange HDR hors tokens |
| `#34d399`, `#f97316`, `#ef4444` dans JS | `settings.js:1251,1256` | Couleurs de statut connexion non tokenisées |
| Duplication filtres desktop/mobile | `index.html` + `app.js` | Toute modif filtre = double modification |
| Machine d'état onboarding | `settings.js:1547–1565` | Compound styles inline, réfactor phase D |

---

## État de `design-system.css` post-Phase C

Taille : ~240 lignes (vs 46 lignes avant Phase C)

Sections remplies :
- **LAYOUT** : tokens `:root` complets (palette, typo, radius, shadows) + body gradient
- **SIDEBAR** : borders douces, boutons bas de sidebar
- **HEADER/TOPBAR** : backdrop blur, active tab accent-08, radius contrôles
- **CARDS** : radius 14px, shadows, border-soft, tl-card, media-table
- **FILTERS** : pills, dropdowns radius 14px, score panel, exclude token sémantique
- **STATS** : shadows blocs, mono font KPI, radius stat-kpi, chart-wrap, cross-table
- **AUTH & ONBOARDING** : shadows tokenisées, borders douces, authError couleur sémantique
- **SETTINGS** : borders douces, stab active accent-08, inputs, collapsibles
- **RESPONSIVE** : topbar/nav/filtres/sheet mobile borders douces
- **QA FIXES** : scan-log-panel, #cfgAuthBlock, scan colors

---

## Tests

```
94/94 tests passent (npm run test:frontend:unit)
```
