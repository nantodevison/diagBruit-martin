# Plan d'action — analyse_pnb_ampm

> Voir aussi [CLAUDE.md](CLAUDE.md) pour l'objectif du sous-projet et les règles de collaboration.

Ce document rassemble les décisions techniques prises avec Martin pour les 4 grandes étapes du projet, avant le démarrage effectif de l'implémentation (le jeu de données PNB étant en cours de finalisation par Martin).

## Structure cible

```
analyse_pnb_ampm/
├── CLAUDE.md              (objectif et méthode de travail)
├── plan_action.md         (ce document)
├── __init__.py            (vide, comme budget/)
├── pnb_parcelles.py       # étape 1 : rattachement bâtiments PNB → parcelles cadastrales
├── diagbruit_api.py       # étape 2 : appels API diagBruit (sonoscore + niveaux sonores)
├── analyse_pnb.py         # étape 3 : comparaison PNB vs parcelles témoins
└── data/                  (non versionné, voir .gitignore)
    ├── pnb_batiments_ampm.gpkg          (bâtiments PNB reçus de Martin, ~25 Mo)
    └── cadastre_parcelles_ampm.geojson  (parcelles cadastrales AMPM, ~400 Mo)
notebooks/
└── analyse_pnb_ampm.ipynb  # étape 4 : orchestration des 3 modules + restitution (altair, carte)
```

Trois modules distincts (plutôt qu'un seul fichier) pour suivre la logique des 4 étapes, garder chaque fichier court et lisible, et pouvoir livrer/tester le module 1 dès que le fichier PNB est validé, sans attendre l'accès à l'API diagBruit. Les conventions du repo reprises viennent de `budget/` (seul autre sous-projet avec appel API) : voir `budget/grist.py` (pattern d'appel API) et `notebooks/budget.ipynb` (pattern notebook + altair).

## Étape 1 — Rattacher les bâtiments PNB aux parcelles (`pnb_parcelles.py`)

**Objectif de cette étape** : isoler uniquement les parcelles cadastrales concernées par au moins un bâtiment PNB. C'est ce sous-ensemble réduit (et non l'ensemble du cadastre AMPM) qui sera ensuite interrogé via l'API diagBruit à l'étape 2 — l'étape 1 sert donc aussi à limiter le nombre d'appels API.

**Fichiers reçus de Martin** : bâtiments PNB en polygones/multipolygones, format GeoPackage (`.gpkg`, ~25 Mo) ; parcelles cadastrales AMPM en polygones/multipolygones, format GeoJSON (~400 Mo).

**Point d'attention — taille du fichier parcelles (400 Mo GeoJSON)** : charger l'intégralité du fichier en mémoire avec geopandas serait lent et gourmand, alors qu'on n'a besoin que des parcelles proches des bâtiments PNB. Approche retenue :
- Charger d'abord les bâtiments PNB (fichier léger, 25 Mo) et calculer leur emprise globale (bounding box)
- Charger les parcelles avec un filtre `bbox` sur cette emprise (`geopandas.read_file(..., bbox=...)`), pour ne matérialiser que la portion utile du fichier plutôt que les 400 Mo
- Ajout de `pyogrio` à `requirements.txt` — moteur de lecture recommandé par geopandas pour les gros fichiers, sans changement de code
- **Solution de repli** (seulement si le bbox ne suffit pas à réduire suffisamment le volume, ex. bâtiments PNB très dispersés sur toute la métropole) : convertir une fois le fichier parcelles en GeoPackage avec index spatial, plutôt que de le relire en GeoJSON à chaque fois. À ne mettre en place que si un test révèle un vrai problème de performance, pour ne pas complexifier inutilement.

**Schéma du fichier PNB confirmé** (via le fichier de définition de couche QGIS fourni par Martin, couche `Bati_isophone_Aurélie_06_2026`) :
- CRS : **Lambert-93 (EPSG:2154)** — à harmoniser avec le CRS du fichier parcelles lors du diagnostic OGC (Phase 0)
- Identifiant bâtiment retenu : **`ID`** (champ BD TOPO local au fichier), plutôt que `IDS_RNB` qui peut être absent pour certains bâtiments
- **Présence dans le fichier = bâtiment PNB confirmé** (décidé avec Martin) : le fichier a déjà été filtré en amont, pas de filtre supplémentaire à appliquer sur `Lden_C`/`Iso_Jour`/`Iso_Nuit`/`Sensible` de notre côté
- Champs utiles repérés pour la suite : `an_constru`/`annee_min`/`annee_max` (année de construction — clé pour l'étape 3, permet de vérifier si le bâtiment a été construit après l'existence du classement sonore), `Lden_C`, `Iso_Jour`/`Iso_Nuit`, `Pop_bat`/`Pop_Ratio`, `Sensible`, `CAT_Bat`

**Phase 0 — diagnostic OGC des couches géo (avant toute jointure)** : contrôle qualité des fichiers PNB et cadastre avant de les croiser, pour éviter de découvrir un problème seulement au moment de la jointure spatiale.
- CRS défini et cohérent entre les deux fichiers (sinon la jointure donne des résultats faux silencieusement)
- Validité géométrique (`geometry.is_valid` via geopandas/shapely) — géométries vides, auto-intersections, polygones mal fermés
- Types de géométrie attendus (points/polygones pour les bâtiments, polygones pour les parcelles)
- Cohérence des emprises (bounding box) — les bâtiments PNB tombent bien dans l'emprise du cadastre AMPM (détecter un décalage de projection)
- Rapport d'anomalies détectées, pour décision de Martin (correction, exclusion, retour à la source)

**Jointure spatiale** (« quelle parcelle contient ce bâtiment PNB ? ») avec **geopandas** (`sjoin`) — solution standard et la plus lisible pour ce type d'opération, à privilégier plutôt que du calcul géométrique manuel (cohérent avec le principe « clarté avant tout »). Sous-tâches : charger le fichier PNB, charger les parcelles cadastrales AMPM, harmoniser le CRS, jointure spatiale, dédoublonnage si plusieurs bâtiments PNB tombent sur la même parcelle.

**Bâtiment à cheval sur plusieurs parcelles (décidé avec Martin)** : rattachement à la parcelle ayant la **surface de recouvrement maximale** avec le bâtiment (calcul de l'aire d'intersection bâtiment/parcelle pour chaque parcelle candidate, on garde la plus grande) — plus précis qu'un simple centroïde dans les cas limites.

**Bâtiment sans parcelle correspondante (ex. domaine public — décidé avec Martin)** : ces bâtiments ne sont **pas exclus silencieusement**. Le module `pnb_parcelles.py` produit deux résultats distincts : (1) les bâtiments rattachés à une parcelle, utilisés pour la suite de l'analyse, et (2) une liste séparée des bâtiments non rattachés, pour examen manuel par Martin (légitime domaine public, ou anomalie de données à corriger).

**Format de sortie retenu** (structure relationnelle, plutôt qu'une seule table avec des listes imbriquées) :

| Table | Grain | Colonnes principales |
|---|---|---|
| `parcelles_pnb` | 1 ligne / parcelle | `id_parcelle`, `geometry`, `commune`/`code_insee`, `surface_parcelle_m2`, `nb_batiments_pnb` |
| `rattachements_batiments_parcelles` | 1 ligne / bâtiment rattaché | `id_batiment`, `id_parcelle`, `surface_recouvrement_m2`, `part_recouvrement_pct` |
| `batiments_non_rattaches` | 1 ligne / bâtiment sans parcelle | `id_batiment`, `geometry`, attributs bruts du fichier PNB |

## Étape 2 — Interroger l'API diagBruit par parcelle (`diagbruit_api.py`)

**Contrat de l'API confirmé** (vérifié via le schéma OpenAPI `https://api.diagbruit.beta.gouv.fr/openapi.json` et un test réel sur le Swagger) :
- Endpoint : `POST /diag/generate/from-geometries` — on lui fournit directement la géométrie de chaque parcelle (déjà disponible depuis notre propre cadastre, étape 1), plutôt que `from-parcelles` (référence cadastrale), pour éviter de dépendre d'une résolution de géométrie côté diagBruit via une API cadastre externe soumise à rate limit.
- Corps de requête : `{"items": [{"parcelle": {...}, "populate": {"zones": bool, "isolation": bool}, "geometry": [...]}]}` — l'endpoint accepte plusieurs `items` en un seul appel (donc un "bloc de 100 parcelles" = 1 appel avec 100 items, pas 100 appels séparés).
- Authentification : aucune — API libre, confirmé par Martin et par l'absence de schéma de sécurité dans l'OpenAPI.
- Cadence : pas d'appel en masse illimité — les développeurs diagBruit recommandent de cascader par blocs raisonnables (proposition à tester : ~100 parcelles/appel).
- Coordonnées attendues en entrée : WGS84 (lon/lat) — une **reprojection est nécessaire** avant l'appel, les géométries sources étant en Lambert-93 (EPSG:2154).

**Format de réponse observé** (exemple réel testé par Martin sur le Swagger) — structure `diagnostics[].diagnostic` avec, entre autres :
- `score` (le sonoscore — peut légèrement dépasser 10 dans certains cas, ex. 11 observé ; diagBruit le ramène à 10 dans son propre front, mais **on garde la valeur brute** pour notre analyse, confirmé par Martin)
- `max_db_lden` / `min_db_lden` (bornes de niveau sonore en dB)
- `flags` (7 indicateurs booléens : alertes qualité, zone prioritaire, multi-exposition...)
- `equivalent_ambiences` (comparaisons sonores pédagogiques, utile pour l'étape 4)
- `soundclassification_intersections[]` : proximité des voies classées, avec `source` (routier/ferroviaire/...), `label`, `acoustic_category` (1 à 5), distances, `percent_impacted` — **champ clé pour filtrer sur le périmètre routier/ferroviaire du projet**
- `land_intersections_ld[]` / `land_intersections_ln[]` : détail des cartes de bruit intersectant la parcelle (jour-soir / nuit), avec niveau dB, type de producteur, direction
- `air_intersections[]`, `noisesource_intersections[]`, `noisezone_intersections[]`, `zones[]`, `isolation_min/max`, `recommendations[]` : présents dans la réponse mais hors périmètre de cette première analyse (bruit aérien, POI ambiants, options avancées non activées)

**Format de sortie du module** — même logique relationnelle qu'à l'étape 1 :

| Table | Grain | Colonnes principales |
|---|---|---|
| `sonoscores_parcelles` | 1 ligne / parcelle | `id_parcelle`, `score`, `max_db_lden`, `min_db_lden`, les 7 flags |
| `classement_sonore_parcelles` | 1 ligne / intersection voie classée | `id_parcelle`, `source`, `label`, `acoustic_category`, `min_distance`, `max_distance`, `percent_impacted` (table principale pour l'étape 3) |
| `cartes_bruit_parcelles` | 1 ligne / intersection carte de bruit (LD+LN, colonne `periode`) | `id_parcelle`, `periode`, `acoustic_producer_kind`, `acoustic_db_value`, `percent_impacted`, `direction` |

**Module** : reprend le pattern de `budget/grist.py` (`load_dotenv()`, constante `URL_DIAGBRUIT_API` en haut du fichier — pas de clé API nécessaire), fonction typée d'appel par bloc de géométries, `response.raise_for_status()`. Fonction d'orchestration qui découpe la liste des parcelles concernées en blocs (~100), appelle l'API bloc par bloc, capture les erreurs par bloc sans interrompre le traitement global, et sauvegarde les résultats progressivement dans `data/`.

**À faire** : lancer quelques appels réels sur des parcelles de Marseille (bloc de 1, puis bloc de ~100) pour mesurer le temps de réponse et en déduire une estimation du temps total nécessaire une fois le volume réel de parcelles PNB connu (étape 1).

## Étape 3 — Analyser le pouvoir prédictif (`analyse_pnb.py`)

Comparer la distribution du sonoscore et des niveaux sonores des parcelles PNB confirmées à celle d'un **échantillon témoin de parcelles non-PNB** (même métropole, exposition routière/ferroviaire comparable pour une comparaison honnête). Un sonoscore significativement plus bas / des niveaux sonores plus élevés sur les parcelles PNB validerait le pouvoir d'anticipation de diagBruit.

Outils simples et lisibles : statistiques descriptives (médiane, quartiles) + visualisations altair (histogrammes ou boîtes à moustaches), plutôt que des tests statistiques complexes.

**Point ouvert à trancher avec Martin** : comment constituer l'échantillon témoin (parcelles voisines ? tirage aléatoire ? même période de construction ?).

## Étape 4 — Restitution (`notebooks/analyse_pnb_ampm.ipynb`)

Suit le pattern `budget.ipynb` : `%load_ext autoreload` / `%autoreload 2`, `sys.path.append("..")`, import des 3 modules, une cellule par graphique altair, éventuellement une carte simple (points colorés par sonoscore).

**Point ouvert à trancher avec Martin** : format final exact du livrable (notebook, export, carte interactive) et destinataire précis — la brique technique reste la même quel que soit le format retenu.

## Ce qui peut démarrer sans attendre le fichier PNB finalisé

- Créer la structure de dossiers/fichiers ci-dessus (squelettes de fonctions typées + docstrings, sans logique métier)
- Ajouter `geopandas`, `shapely`, `pyproj`, `pyogrio` à `requirements.txt`
- Rechercher/confirmer la source des parcelles cadastrales AMPM (ex. cadastre.data.gouv.fr)
- Documenter la structure `.env` attendue (`URL_DIAGBRUIT_API`)
- Esquisser la logique de jointure spatiale (étape 1) avec un jeu de données factice
- Test exploratoire de l'API diagBruit sur des parcelles de Marseille (contrat déjà connu, indépendant du fichier PNB)

## Ce qui reste bloqué

- Le traitement réel du fichier PNB final (Martin complète actuellement la couverture des parcelles, un trou ayant été identifié sur Marseille)
- L'appel à l'API diagBruit sur les vraies parcelles PNB (dépend du résultat de l'étape 1)
- L'analyse comparative de l'étape 3 (dépend des résultats des étapes 1 et 2)

## Points encore ouverts

- Méthode de constitution de l'échantillon témoin non-PNB (étape 3)
- Format final du livrable et destinataire précis (étape 4)

## Fichiers concernés

- `budget/grist.py` — modèle du pattern d'appel API
- `notebooks/budget.ipynb` — modèle du pattern notebook + altair
- `requirements.txt` — ajout de `geopandas`, `shapely`, `pyproj`, `pyogrio`
- `.gitignore` — `analyse_pnb_ampm/data/` déjà exclu du versioning

## Vérification (une fois l'implémentation démarrée)

- Les modules squelettes s'importent sans erreur (`python -c "import analyse_pnb_ampm.pnb_parcelles"`, etc.)
- Le notebook s'ouvre et exécute ses cellules d'import sans erreur (même sans données réelles, avec des données factices/vides)
- Une fois le fichier PNB validé par Martin : la jointure spatiale de l'étape 1 produit une liste de parcelles avec un identifiant exploitable pour l'étape 2
