# UI Refactor — Validation Guide

Checklist à exécuter après chaque commit de refonte UI pour s'assurer qu'aucun comportement n'a régressé.

---

## Commandes automatisées

### 1. Guards CSS/source (rapide, sans serveur)

```bash
cd tests/frontend
npm install           # une seule fois
npm run test:frontend:unit
```

Vérifie : pas de handlers inline dans le HTML, pas de fichiers JSON runtime, invariants de la codebase.

### 2. Tests E2E Playwright (requiert un serveur)

```bash
# Dans un terminal : lancer le serveur statique
python3 -m http.server 4173 --directory app

# Dans un autre terminal
cd tests/frontend
npm run test:frontend:e2e
```

Couvre les flows critiques : library, filtres, scan, settings, auth, stats.

### 3. CI scripts

```bash
tests/scripts/audit-no-runtime-json.sh
tests/scripts/check-no-inline-handlers.sh
```

### 4. Build Docker (validation complète)

```bash
docker build -t mymedialibrary:local -f docker/Dockerfile .
docker compose up -d
```

---

## Checklist manuelle

À valider visuellement dans le navigateur après chaque commit CSS/HTML.

### Library
- [ ] Grille de cartes affichée correctement (dark + light)
- [ ] Vue tableau fonctionnelle
- [ ] Tri par colonne opérationnel
- [ ] Export CSV
- [ ] Badge qualité visible et tooltip au survol
- [ ] Posters chargés / placeholder correct

### Filtres — Desktop (sidebar)
- [ ] Filtre type (Tous / Films / Séries) actif
- [ ] Filtre disponibilité (Disponible / Absent / Tous)
- [ ] Filtres folder / genre / provider pills
- [ ] Section "Qualité technique" collapsible
- [ ] Filtres résolution / codec / audio codec / canaux / langue
- [ ] Double slider qualité
- [ ] Mode inclusion / exclusion (icône ⊕/⊖)
- [ ] Bouton "Réinitialiser les filtres" enable/disable
- [ ] Recherche texte + bouton ✕ clear
- [ ] Tri select

### Filtres — Mobile (overlay)
- [ ] Ouverture panel via bouton topbar
- [ ] Même filtres que desktop, synchronisés
- [ ] Recherche mobile
- [ ] Réinitialiser mobile

### Stats
- [ ] Sous-onglets : Général / Technique / Évolution / Recommandations
- [ ] Graphiques camembert (taille + nombre, switch)
- [ ] Barres horizontales genres / providers
- [ ] Courbe évolution (all / 12m / 30d)
- [ ] Graphique années / décennies

### Recommandations
- [ ] Onglet visible uniquement si activé
- [ ] Filtres priorité / type / dossier
- [ ] Tableau + vue cartes mobile
- [ ] Export CSV recommandations
- [ ] Stats recommandations dans l'onglet Stats

### Settings
- [ ] Ouverture / fermeture modal
- [ ] 5 onglets fonctionnels (Bibliothèque, Configuration, Score, Connexions, Système)
- [ ] Toggles Films / Séries / Synopsis / ffprobe / Score / Recommandations
- [ ] Dossiers détectés + sélection type
- [ ] Score : poids + sections collapsibles + reset
- [ ] Connexions : Seerr URL/key + test
- [ ] Visibilité fournisseurs (provider toggles)
- [ ] Langue FR/EN
- [ ] Couleur d'accent + reset
- [ ] Cron hint dynamique
- [ ] Auth : activation + règles mot de passe
- [ ] Boutons Fermer / Enregistrer / Déconnexion

### Onboarding
- [ ] Déclenchement au premier lancement
- [ ] Navigation étapes (Précédent / Suivant / Passer)
- [ ] Sélection langue
- [ ] Configuration dossiers
- [ ] Configuration Seerr (optionnel)
- [ ] Toggle features
- [ ] Configuration auth (optionnel)
- [ ] Lancement scan depuis onboarding
- [ ] Toggle thème dans l'onboarding

### Auth
- [ ] Overlay visible si auth activée
- [ ] Input password, bouton Entrer
- [ ] Message d'erreur sur mauvais mot de passe
- [ ] Focus input → bordure accent
- [ ] Hover bouton → brightness

### Scan
- [ ] Bouton Scanner sidebar
- [ ] Panel log scan (ouverture, lignes, statut animé)
- [ ] Poll status en temps réel
- [ ] Reload bibliothèque après scan
- [ ] Bouton scan mobile (bottom sheet)

### Responsive — Mobile (≤ 768px)
- [ ] Topbar fixe visible (logo + 3 boutons)
- [ ] Sidebar masquée
- [ ] Navigation bottom (Biblio / Stats / Recos)
- [ ] Back-to-top visible au scroll
- [ ] Panel filtres mobile slide-down
- [ ] Cards pleine largeur
- [ ] Settings en bas de page (onglets remplacés par sections collapsibles)
- [ ] Scan depuis settings mobile

### Thème dark / light
- [ ] Toggle thème fonctionne
- [ ] Toutes les sections visibles en dark ET light
- [ ] Pas de couleur hardcodée restant invisible dans un thème

---

## Invariants à ne jamais casser

```bash
# Pas de handler inline dans le HTML
tests/scripts/check-no-inline-handlers.sh

# Pas de fichiers JSON runtime dans le repo
tests/scripts/audit-no-runtime-json.sh

# Pas de style inline non-dynamique dans index.html (vérification manuelle)
grep -c 'style="' app/index.html   # doit retourner ≤ 33
grep 'style="' app/index.html | grep -v 'display:none'  # doit être vide
```
