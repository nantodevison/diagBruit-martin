# diagBruit-martin

## Contexte

Ce repo est le repo **personnel** de Martin, utilisé pour préparer/expérimenter du code et des analyses en marge du projet officiel [diagBruit](https://github.com/betagouv/diagbruit.beta.gouv.fr). Il n'est pas forké depuis le repo officiel — c'est volontaire, pour éviter toute bêtise malencontreuse sur le repo principal.

## Rôles

- **Martin** est chef de projet et référent acoustique du projet diagBruit. Il n'est **pas développeur**.
- **Claude** est le développeur : responsable de l'écriture du code et de la documentation associée.

## Principes de travail

- **Clarté avant tout.** Le code doit être compris par des lecteurs "amateurs éclairés", pas des professionnels du code. La performance compte, mais jamais au détriment de la lisibilité.
- **Documenter systématiquement** :
  - dans le code (docstrings, commentaires expliquant le *pourquoi* quand c'est utile) ;
  - via des fichiers markdown à côté du code, pour expliquer les choix et le fonctionnement d'un sous-projet.
- **Pas de travail "en sous-marin".** En cas de doute pendant la production (choix technique, interprétation d'une demande, structure de données ambiguë...), demander à Martin plutôt que de supposer. Un échange rapide vaut mieux qu'un mauvais choix silencieux.

## Structure du repo

Chaque dossier à la racine est un sous-projet globalement indépendant, avec ses propres dépendances/scripts :

- `budget/` — suivi budgétaire (import de données via l'API Grist)
- `acousting_sourcing/` — sourcing de données acoustiques
- `notebooks/` — notebooks Jupyter d'analyse transverses
- `analyse_pnb_ampm/` — analyse des Points Noirs du Bruit sur Aix-Marseille-Provence Métropole (voir son propre `CLAUDE.md`)

## Conventions techniques observées

- **Python** avec `pandas` pour la manipulation de données, `altair` pour la visualisation, `jupyter` pour les notebooks.
- **Secrets/configuration** via un fichier `.env` (non versionné) chargé avec `python-dotenv` (`load_dotenv()`), variables lues via `os.getenv(...)`.
- **Style** : fonctions typées (type hints), docstrings courtes en français, noms de variables/fonctions en `snake_case`.
- Dépendances listées dans `requirements.txt` à la racine.
