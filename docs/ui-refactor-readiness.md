# UI Refactor — Readiness Report

État de préparation avant intégration du design Claude Design.
Branch : `dev-ui-refactor`

---

## Phases terminées

| Phase | Commit | Résultat |
|-------|--------|----------|
| **A1** — Tokens CSS | `css: add missing design tokens` | 17 `--z-*`, 5 `--shadow-*`, 10 `--space-*` ajoutés dans `:root` |
| **A2.1** — z-index | `css: replace hardcoded z-index` | 14 valeurs hardcodées → `var(--z-*)` dans `app.css` |
| **A2.2** — shadows | `css: replace matching box-shadow` | 6 valeurs → `var(--shadow-*)` dans `app.css` |
| **A2.3.1** — spacing | `css: replace simple spacing values` | 43 `gap/padding/margin` → `var(--space-*)` hors `@media` |
| **A2.3.2** — spacing | `css: replace 20/32px spacing values` | 2 valeurs `gap/padding-right` supplémentaires |
| **C1** — design-system.css | `css: introduce design-system.css` | Fichier de surcharges créé, chargé en 3e position dans `index.html` |
| **B1** — inline styles HTML | `html+css: extract all static inline styles` | 112 → 33 `style=` (tous `display:none` JS) ; 34 règles CSS + 13 classes extraites |
| **B2** — styles JS | `css: migrate 2 predictable JS interaction states` | Inventaire 154 occurrences ; 2 règles CSS ajoutées (`#authInput:focus`, `#authBtn:hover`) |
| **B3** — checklist | `docs: add UI refactor validation checklist` | `docs/ui-refactor-validation.md` — commandes auto + 10 sections manuelles |

---

## Fichiers préparés

### `app/css/app.css`
- Tokens `--z-*`, `--shadow-*`, `--space-*` définis dans `:root`
- Z-index, box-shadows et spacings tokenisés dans les règles existantes
- Section finale **"INLINE STYLES EXTRACTED — Phase B1"** : 34 règles ID + classes extraites du HTML
- Règles existantes augmentées : `.scan-info`, `.sidebar-brand`, `.sidebar-section`, `.tab-sort-select`, `.scan-btn-wrap`
- **Ne pas modifier directement** pour le redesign — utiliser `design-system.css`

### `app/css/design-system.css`
- Chargé **après** `app.css` et `stats.css` → toutes les règles ont priorité
- Contient actuellement : `#authInput:focus` et `#authBtn:hover` (B2)
- **C'est ici que vont tous les overrides du nouveau design** (phases C2–C7)
- Structure en sections vides prête : Layout, Sidebar, Header, Cards, Filters, Stats, Settings, Responsive

### `app/index.html`
- 33 `style="display:none"` restants — tous légitimes (contrôlés par JS)
- Aucun style statique inline subsistant
- Classes extraites ajoutées : `.auth-*`, `.sidebar-brand-inner`, `.sidebar-actions-row`, `.settings-row--mb`, `.mobile-filter-item`, `.onboarding-inner`, etc.
- Structure HTML intacte — IDs et classes JS non modifiés

### `docs/ui-refactor-validation.md`
- Commandes de validation automatisées (unit guards, Playwright, CI scripts)
- Checklist manuelle par section UI
- Invariants shell à vérifier après chaque commit

---

## Règles à respecter pour la phase C

**1. Overrides uniquement dans `design-system.css`**
Ne pas modifier `app.css` ni `stats.css` pour les changements visuels du nouveau design. Toute règle de redesign va dans `design-system.css` dans la section correspondante.

**2. Pas de refactor JS**
Les fichiers `app.js`, `events.js`, `settings.js`, `stats.js`, `app.logic.js` ne doivent pas être touchés. Les 33 `display:none` restants et les 115+ manipulations `.style.*` JS coexistent avec le nouveau CSS.

**3. Préserver les IDs et classes critiques utilisés par le JS**
Les sélecteurs JS font référence à des IDs (`#scanMainBtn`, `#libraryPanel`, etc.) et des classes (`.provider-pill`, `.filter-dropdown-option`, `.stab`, etc.). Ne jamais renommer sans grep complet.

Éléments particulièrement sensibles :
- `#library`, `#statsContent`, `#recommendationsContent` — innerHTML injecté par JS
- `.provider-pill`, `.filter-dropdown-option`, `.rec-filter-btn` — délégation d'événements par classe
- `.stab[data-stab]`, `.settings-collapsible[data-target]` — data-attributes lus par events.js
- `.scan-btn-wrap`, `.icon-btn` — ciblés dans la duplication desktop/mobile

**4. Commits atomiques par composant**
Un commit = un composant visuel (ex: sidebar, cards, settings). Tester avec la checklist B3 après chaque commit.

**5. Duplication desktop/mobile**
Tout changement visuel sur un filtre sidebar doit être répliqué sur son pendant `*Mobile`. Les IDs mobiles ont systématiquement le suffixe `Mobile` (ex: `#typeSection` → `#mobileTypeSection`).

---

## Dettes techniques connues

### `display:none` restants (33 occurrences)
Les `style="display:none"` dans `index.html` sont intentionnels — état initial contrôlé par JS via `el.style.display`. Ils ne peuvent pas être migrés en CSS sans modifier le JS. À documenter mais ne pas toucher.

### Styles dynamiques JS (~115 occurrences)
Les manipulations `.style.display`, `.style.color`, `.style.opacity` dans les 5 fichiers JS sont toutes KEEP_DYNAMIC. Inventaire complet dans le message du commit B2. Certains patterns pourraient bénéficier de `classList` mais nécessiteraient un refactoring JS délibéré, hors scope de la phase C.

### Machine d'état onboarding (~20 occurrences — COMPLEX)
`settings.js:1547–1565`, `1817–1824`, `1982–1984` : les boutons de choix onboarding (scan type, dossiers, auth skip) ont leur état visuel géré par 5 propriétés inline simultanées (`background`, `borderColor`, `color`, `boxShadow`, `transform`). Migration vers `data-state` + CSS possible en phase D, pas avant.

### Couleurs statut hardcodées dans le JS
`#34d399` (succès Seerr), `#f97316` (warning), `#ef4444` (erreur) sont injectées directement via `.style.color` dans `settings.js`. À tokeniser en `--color-success`, `--color-warning`, `--color-error` lors du redesign complet — tokens à ajouter dans `app.css :root` et `[data-theme="light"]`.

### Duplication filtres desktop / mobile
Tous les filtres sidebar sont dupliqués dans `#mobileFiltersPanel` avec le suffixe `Mobile` sur les IDs. La synchronisation est gérée par `syncMobileFilters()` dans `app.js`. Toute évolution des composants filtres requiert une double modification. Refactoring possible en phase D (composant unique rendu dans les deux contextes).

### Couleurs et box-shadows non tokenisées restantes
Quelques valeurs hardcodées subsistent dans `app.css` hors tokens :
- `box-shadow: 0 24px 64px rgba(0,0,0,.5)` (auth modal) — non standard
- `box-shadow: 0 -8px 24px rgba(0,0,0,.35)` (mobile sheet — y-offset négatif)
- `box-shadow: 0 8px 24px rgba(0,0,0,.4)` (tooltip — alpha .4 ≠ --shadow-lg)
- `box-shadow: 0 1px 2px rgba(0,0,0,.16)` (quality badge)
- `#ea580c`, `#4ecdc4`, `#a78bfa` (badge-hdr, size-tag, group-tag) — non overridables en light mode
