# analyse_pnb_ampm

> Voir aussi le `CLAUDE.md` à la racine du repo pour les principes généraux de collaboration (rôles, priorité à la clarté, documentation, ne pas avancer seul en cas de doute).

## Objectif

Identifier et analyser les **Points Noirs du Bruit (PNB)** sur le territoire d'**Aix-Marseille-Provence Métropole (AMPM)**, dans le cadre du PPBE (Plan de Prévention du Bruit dans l'Environnement) du projet diagBruit.

*(Statut : ce projet démarre. Les détails ci-dessous seront précisés et complétés au fur et à mesure des échanges avec Martin.)*

## Données

Deux types de sources sont attendus :

- **Fichiers fournis par Martin** (CSV, Excel, GeoJSON...), déposés dans ce dossier ou un sous-dossier `data/` à créer.
- **Récupération via API / web** (ex. data.gouv.fr, ou autres sources ouvertes), selon les besoins de l'analyse — voir `budget/grist.py` à la racine pour un exemple de pattern d'appel API existant dans ce repo.

Les données brutes volumineuses ou sensibles ne doivent pas être commitées sans vérification (voir `.gitignore` à la racine).

## Livrables attendus

- Un **module Python réutilisable** (fonctions documentées, typées) pour les traitements (chargement, nettoyage, calculs sur les PNB).
- Des **notebooks Jupyter** qui utilisent ce module pour l'exploration, l'analyse et la restitution (visualisations, probablement avec `altair` comme dans `notebooks/budget.ipynb`).

## À faire préciser avec Martin

- Définition précise et critères d'un "Point Noir du Bruit" pour cette analyse.
- Sources de données exactes (fichiers à fournir, jeux de données data.gouv pertinents).
- Format et destinataire final des résultats (rapport, carte, tableau de bord...).
