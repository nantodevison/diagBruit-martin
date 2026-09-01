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
    ├── Bati_isophone_Aurélie_06_2026.gpkg  (bâtiments PNB reçus de Martin, ~25 Mo)
    ├── cadastre-13-parcelles.json           (parcelles cadastrales du département 13, ~680 Mo, non pré-filtré sur l'AMPM)
    ├── parcelles_pnb.gpkg                   (sortie étape 1)
    ├── rattachements_batiments_parcelles.csv (sortie étape 1)
    ├── batiments_non_rattaches.gpkg          (sortie étape 1, à examiner)
    ├── sonoscores_parcelles.csv              (sortie étape 2, registre idempotent)
    ├── classement_sonore_parcelles.csv       (sortie étape 2)
    ├── cartes_bruit_parcelles.csv            (sortie étape 2)
    ├── CBS_AGGLO/                            (cartes de bruit stratégiques AMPM, pour l'échantillon témoin étape 3)
    └── BDNB/                                 (Base Nationale des Bâtiments dept. 13, pour l'échantillon témoin étape 3)
notebooks/
└── analyse_pnb_ampm.ipynb  # étape 4 : orchestration des 3 modules + restitution (altair, carte)
```

Trois modules distincts (plutôt qu'un seul fichier) pour suivre la logique des 4 étapes, garder chaque fichier court et lisible, et pouvoir livrer/tester le module 1 dès que le fichier PNB est validé, sans attendre l'accès à l'API diagBruit. Les conventions du repo reprises viennent de `budget/` (seul autre sous-projet avec appel API) : voir `budget/grist.py` (pattern d'appel API) et `notebooks/budget.ipynb` (pattern notebook + altair).

## Étape 1 — Rattacher les bâtiments PNB aux parcelles (`pnb_parcelles.py`)

**Objectif de cette étape** : isoler uniquement les parcelles cadastrales concernées par au moins un bâtiment PNB. C'est ce sous-ensemble réduit (et non l'ensemble du cadastre AMPM) qui sera ensuite interrogé via l'API diagBruit à l'étape 2 — l'étape 1 sert donc aussi à limiter le nombre d'appels API.

**Fichiers reçus de Martin** : bâtiments PNB en polygones/multipolygones, format GeoPackage (`.gpkg`, ~25 Mo, CRS Lambert-93/EPSG:2154) ; parcelles cadastrales, format GeoJSON (`cadastre-13-parcelles.json`, ~680 Mo, CRS **WGS84/EPSG:4326**, échelle **département 13 entier** — non pré-filtré sur l'AMPM, 962 410 parcelles). Un premier envoi (shapefile, Lambert-93, ~465 Mo) s'est révélé corrompu (voir "Résultats obtenus" ci-dessous) et a été remplacé par ce fichier.

**Point d'attention — taille du fichier parcelles (~680 Mo, département entier)** : charger l'intégralité du fichier en mémoire avec geopandas serait lent et gourmand, alors qu'on n'a besoin que des parcelles proches des bâtiments PNB. Approche retenue :
- Charger d'abord les bâtiments PNB (fichier léger, 25 Mo) et calculer leur emprise globale (bounding box), reprojetée en WGS84 pour correspondre au CRS natif du fichier parcelles
- Charger les parcelles avec un filtre `bbox` sur cette emprise (`geopandas.read_file(..., bbox=...)`), pour ne matérialiser que la portion utile du fichier plutôt que les 680 Mo — en pratique ~700k parcelles chargées en ~35s, largement suffisant, la solution de repli (conversion GeoPackage) ne s'est pas avérée nécessaire
- `pyogrio` ajouté à `requirements.txt` — moteur de lecture recommandé par geopandas pour les gros fichiers
- La reprojection WGS84 → Lambert-93 des parcelles chargées est gérée automatiquement dans `rattacher_batiments_parcelles` (les deux couches viennent de sources indépendantes, rien ne garantit qu'elles partagent le même CRS)

**Schéma du fichier PNB confirmé** (via le fichier de définition de couche QGIS fourni par Martin, couche `Bati_isophone_Aurélie_06_2026`) :
- CRS : **Lambert-93 (EPSG:2154)**
- Identifiant bâtiment retenu : **`ID`** (champ BD TOPO local au fichier), plutôt que `IDS_RNB` qui peut être absent pour certains bâtiments
- **Présence dans le fichier = bâtiment PNB confirmé** (décidé avec Martin) : le fichier a déjà été filtré en amont, pas de filtre supplémentaire à appliquer sur `Lden_C`/`Iso_Jour`/`Iso_Nuit`/`Sensible` de notre côté
- Champs utiles repérés pour la suite : `an_constru`/`annee_min`/`annee_max` (année de construction — clé pour l'étape 3, permet de vérifier si le bâtiment a été construit après l'existence du classement sonore), `Lden_C`, `Iso_Jour`/`Iso_Nuit`, `Pop_bat`/`Pop_Ratio`, `Sensible`, `CAT_Bat`

**Schéma du fichier parcelles confirmé** : `id` (identifiant cadastral), `commune` (code INSEE), `prefixe`, `section`, `numero`, `contenance` (surface en m², utilisée directement pour `surface_parcelle_m2`), `arpente` (booléen), `created`/`updated` (dates).

**Phase 0 — diagnostic OGC des couches géo (avant toute jointure)** : contrôle qualité des fichiers PNB et cadastre avant de les croiser, pour éviter de découvrir un problème seulement au moment de la jointure spatiale.
- CRS défini et cohérent entre les deux fichiers (sinon la jointure donne des résultats faux silencieusement)
- Validité géométrique (`geometry.is_valid` via geopandas/shapely) — géométries vides, auto-intersections, polygones mal fermés
- Types de géométrie attendus (points/polygones pour les bâtiments, polygones pour les parcelles)
- Cohérence des emprises (bounding box) — les bâtiments PNB tombent bien dans l'emprise du cadastre AMPM (détecter un décalage de projection)
- Rapport d'anomalies détectées, pour décision de Martin (correction, exclusion, retour à la source)

**Jointure spatiale** (« quelle parcelle contient ce bâtiment PNB ? ») avec **geopandas** (`gpd.overlay(..., how="intersection")`) plutôt que `sjoin` — `overlay` calcule directement la géométrie et l'aire de chaque intersection bâtiment/parcelle, nécessaires pour départager les bâtiments à cheval sur plusieurs parcelles (voir ci-dessous). Solution plus lisible qu'un calcul géométrique manuel (cohérent avec le principe « clarté avant tout »).

**Bâtiment à cheval sur plusieurs parcelles (décidé avec Martin)** : rattachement à la parcelle ayant la **surface de recouvrement maximale** avec le bâtiment (calcul de l'aire d'intersection bâtiment/parcelle pour chaque parcelle candidate, on garde la plus grande) — plus précis qu'un simple centroïde dans les cas limites.

**Bâtiment sans parcelle correspondante (ex. domaine public — décidé avec Martin)** : ces bâtiments ne sont **pas exclus silencieusement**. Le module `pnb_parcelles.py` produit deux résultats distincts : (1) les bâtiments rattachés à une parcelle, utilisés pour la suite de l'analyse, et (2) une liste séparée des bâtiments non rattachés, pour examen manuel par Martin (légitime domaine public, ou anomalie de données à corriger).

**Format de sortie retenu** (structure relationnelle, plutôt qu'une seule table avec des listes imbriquées) :

| Table | Grain | Colonnes principales |
|---|---|---|
| `parcelles_pnb` | 1 ligne / parcelle | `id_parcelle`, `geometry`, `commune`, `prefixe`, `section`, `numero`, `surface_parcelle_m2`, `nb_batiments_pnb` |
| `rattachements_batiments_parcelles` | 1 ligne / bâtiment rattaché | `id_batiment`, `id_parcelle`, `surface_recouvrement_m2`, `part_recouvrement_pct` |
| `batiments_non_rattaches` | 1 ligne / bâtiment sans parcelle | `id_batiment`, `geometry`, attributs bruts du fichier PNB |

**Résultats obtenus** (module `pnb_parcelles.py`, exécuté sur les données réelles) :

- **1er essai** (fichier parcelles shapefile, Lambert-93) : 16 074 parcelles PNB, 26 886 bâtiments rattachés, **5 136 bâtiments non rattachés (16 %)**. Investigation : `PREC_PLANI`, `ACQU_PLANI`, `SOURCE` et `DATE_CREAT` ont des distributions quasi identiques entre bâtiments rattachés et non rattachés (pas de lien avec la précision ou l'ancienneté des données) ; tous les non-rattachés sont à moins de 100 m d'une parcelle (médiane ~6 m). Conclusion à ce stade : écart géométrique entre sources indépendantes (BD TOPO vs cadastre DGFiP), pas une anomalie corrigible.
- Martin a identifié que ce fichier parcelles était en réalité **corrompu** et l'a remplacé par `cadastre-13-parcelles.json` (département entier, WGS84).
- **2e essai** (fichier corrigé) : **21 705 parcelles PNB**, **31 825 bâtiments rattachés**, **197 bâtiments non rattachés (0,6 %)** — confirme que l'essentiel de l'écart du 1er essai venait bien de la corruption du fichier, pas d'un écart structurel entre sources.
- Diagnostic OGC (Phase 0) : 23 géométries de parcelles invalides détectées (auto-intersections), aucune parmi les parcelles PNB retenues — sans impact sur le résultat actuel, mais à garder en tête pour la constitution de l'échantillon témoin (étape 3).
- Un export `data/bbox_batiments_non_rattaches.geojson` (WGS84, boîtes englobantes avec marge de 15 m) a été généré pour que Martin examine les bâtiments non rattachés sous QGIS. **Vérifié par Martin : les 197 bâtiments non rattachés sont bien sur le domaine public** — aucun rattachement par tolérance de distance n'est donc nécessaire, la règle d'intersection stricte est confirmée comme suffisante. Étape 1 considérée close.
- `prefixe`/`section`/`numero` ajoutés à la table `parcelles_pnb` (en plus de `commune`) : nécessaires pour remplir l'objet `parcelle` du corps de requête diagBruit à l'étape 2 (référence cadastrale, même si le calcul se fait sur la géométrie fournie).

## Étape 2 — Interroger l'API diagBruit par parcelle (`diagbruit_api.py`)

**Contrat de l'API confirmé** (vérifié via le schéma OpenAPI `https://api.diagbruit.beta.gouv.fr/openapi.json` et un test réel sur le Swagger) :
- Endpoint : `POST /diag/generate/from-geometries` — on lui fournit directement la géométrie de chaque parcelle (déjà disponible depuis notre propre cadastre, étape 1), plutôt que `from-parcelles` (référence cadastrale), pour éviter de dépendre d'une résolution de géométrie côté diagBruit via une API cadastre externe soumise à rate limit.
- Corps de requête : `{"items": [{"parcelle": {...}, "populate": {"zones": bool, "isolation": bool}, "geometry": [...]}]}` — l'endpoint accepte plusieurs `items` en un seul appel (donc un "bloc de 100 parcelles" = 1 appel avec 100 items, pas 100 appels séparés).
- Authentification : aucune — API libre, confirmé par Martin et par l'absence de schéma de sécurité dans l'OpenAPI.
- Cadence : pas d'appel en masse illimité — les développeurs diagBruit recommandent de cascader par blocs raisonnables (proposition à tester : ~100 parcelles/appel), **avec une pause d'environ 200 ms entre deux appels** (recommandation confirmée par les développeurs diagBruit à Martin). Implémenté via `time.sleep(0.2)` entre chaque appel de bloc dans la fonction d'orchestration ; la valeur est une constante nommée en haut du module (`DELAI_ENTRE_APPELS_S = 0.2`) plutôt qu'un nombre en dur, pour rester facilement ajustable.
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

**Idempotence — ne jamais réinterroger une parcelle déjà traitée (décidé avec Martin)** : en production, si une parcelle a déjà obtenu ses caractéristiques diagBruit lors d'un run précédent, elle ne doit pas être réinterrogée lors des runs suivants (nouvelles parcelles PNB ajoutées, script relancé...). `data/sonoscores_parcelles.csv` sert de registre de référence : avant tout appel API, le module charge ce fichier s'il existe et exclut de la liste à traiter les `id_parcelle` déjà présents. Les nouveaux résultats sont ajoutés à ce registre (pas de réécriture qui perdrait l'historique) après chaque run. Cela économise des appels API et rend le traitement idempotent : relancer le script sur une liste de parcelles inchangée n'appelle l'API pour aucune d'entre elles.

**Module** : reprend le pattern de `budget/grist.py` (`load_dotenv()`, constante `URL_DIAGBRUIT_API` en haut du fichier — pas de clé API nécessaire), fonction typée d'appel par bloc de géométries, `response.raise_for_status()`. Fonction d'orchestration qui filtre d'abord les parcelles déjà traitées (voir idempotence ci-dessus), découpe le reste en blocs (~100), appelle l'API bloc par bloc, capture les erreurs par bloc sans interrompre le traitement global, et sauvegarde les résultats progressivement dans `data/`.

**Résultats obtenus** (module `diagbruit_api.py`, exécuté sur un premier échantillon réel) :

- Test sur 503 parcelles (1 bloc de 3 + 5 blocs de 100) : **aucune erreur**, toutes les requêtes ont abouti, aucune valeur manquante dans les tables produites.
- Idempotence vérifiée : relancer sur les 3 premières parcelles déjà traitées donne `nb_deja_traitees=3, nb_traitees=0` sans appel API.
- Données reçues cohérentes : scores entre 3 et 11, sources `routier` **et** `fer` bien présentes dans `classement_sonore_parcelles` (confirme que le périmètre routier/ferroviaire du projet est bien couvert par les données).
- **Temps mesuré : ~0,22 s/parcelle en moyenne** (110 s pour 500 parcelles, pause de 200 ms comprise).

**Traitement complet (21 705 parcelles)** : lancé en arrière-plan, terminé en **85,5 min**, **0 erreur** sur l'ensemble des appels. Registres finaux : `data/sonoscores_parcelles.csv` (21 705 lignes), `data/classement_sonore_parcelles.csv` (58 450 lignes), `data/cartes_bruit_parcelles.csv` (247 273 lignes) — aucun doublon, `id_parcelle` unique dans `sonoscores_parcelles`.

**Anomalie détectée à la réception, résolue** : 158 parcelles (0,7 %) avaient un `score = 0` et le flag `isMultiExposedLandSources` manquant — toutes dans la commune **84089** (département 84, Vaucluse). Explication de Martin : **AMPM s'étend aussi sur le département 84, mais diagBruit ne couvre que le département 13** — ce ne sont donc pas des données PNB erronées, juste hors de la zone couverte par l'API. Décision : ces 158 parcelles (177 bâtiments PNB concernés) sont **retirées de l'étude** plutôt que silencieusement laissées dans les tables. Elles sont archivées avec leur raison dans `data/parcelles_hors_couverture_diagbruit.gpkg` et `data/batiments_hors_couverture_diagbruit.csv` avant suppression des tables de travail.

**Chiffres finaux après nettoyage** : `parcelles_pnb` = 21 547 (au lieu de 21 705), `rattachements_batiments_parcelles` = 31 648 (au lieu de 31 825), `sonoscores_parcelles` = 21 547. Les tables `classement_sonore_parcelles` (58 450) et `cartes_bruit_parcelles` (247 273) étaient déjà vides pour ces 158 parcelles (cohérent avec une réponse diagBruit dégradée/sans données), donc inchangées.

## Étape 3 — Analyser les résultats obtenus (`analyse_pnb.py`)

**Approche simplifiée (décidée avec Martin)** : l'idée initiale d'un échantillon témoin de parcelles non-PNB pour comparaison a été jugée trop complexe pour une première passe. On se concentre d'abord sur une **analyse descriptive directe** des scores obtenus sur les parcelles PNB elles-mêmes, sans groupe de comparaison.

1. **Statistiques globales du score** : moyenne, médiane, quartiles, min/max sur l'ensemble des parcelles PNB traitées (table `sonoscores_parcelles`, étape 2).
2. **Distribution des scores** : répartition du nombre de parcelles par valeur de score — sert de base à un histogramme à l'étape 4.
3. **Analyse des 7 flags sur les parcelles à score faible** : parmi les parcelles avec un **score ≤ 6** (score faible = diagBruit les considère peu risquées en termes sonores, alors qu'il s'agit de PNB confirmés — cas potentiellement intéressants où diagBruit sous-estimerait le risque), calculer la prévalence (% à `True`) de chacun des 7 flags, et la comparer à leur prévalence dans le reste des parcelles (score > 6). Un flag nettement sur-représenté dans le groupe "score faible" ("dominant") est un indice de ce qui explique le score bas (ex. avertissement sur la qualité de la carte de bruit source à cet endroit).

Outils simples et lisibles : statistiques descriptives pandas + visualisations altair (histogramme des scores, barres de prévalence des flags), plutôt que des tests statistiques complexes.

**Implémenté** (`analyse_pnb.py` + `notebooks/analyse_pnb_ampm.ipynb`) :
- `statistiques_scores`, `distribution_scores`, `repartition_score_eleve_faible`, `prevalence_flags_par_groupe` (seuil `SEUIL_SCORE_FAIBLE = 6`).
- Notebook avec 3 graphiques : histogramme des scores, camembert (2 parts seulement — score élevé/faible, pas une part par valeur de score) et barres comparatives des 7 flags. Palette catégorielle bleu (`#2a78d6`, score élevé) / orange (`#eb6834`, score faible) validée CVD-safe (skill `dataviz`, `validate_palette.js`), réutilisée de façon cohérente sur les 3 graphiques.

**Résultats sur les 21 547 parcelles (données complètes, après nettoyage du hors-périmètre dept. 84)** :
- Score moyen 8,46, médian 9, min 1, max 11.
- Distribution : un pic principal entre 7 et 10 (89 % des parcelles, score > 6), et un groupe secondaire isolé autour de 3-6 (11 %, 2 335 parcelles) — le palier à 3 déjà repéré sur l'échantillon partiel est confirmé (2 095 parcelles), avec un vrai trou entre 0 et 3 (seulement 8 parcelles à 1, aucune à 0 ou 2).
- Flags : `isMultiExposedLdenLn` est quasi systématique dans les deux groupes (~98-100 %), donc pas discriminant. `isPriorityZone` et `isMultiExposedLandSources` sont au contraire **moins fréquents** dans le groupe à score faible (69 % vs 93 % ; 38 % vs 58 %) — pas de "domination" nette. Le signal le plus net : `hasNoisemapWarning` est rare (8 parcelles) mais **exclusivement présent dans le groupe à score faible** (0,34 % vs 0 %) — piste à creuser : ces quelques scores bas pourraient être dus à une carte de bruit source de moins bonne qualité à cet endroit plutôt qu'à une vraie absence de risque.

### Volet 2 — Échantillon témoin (planifié, à construire après le volet 1)

**Objectif du témoin (clarifié avec Martin)** : démontrer qu'une parcelle faiblement exposée reçoit un score diagBruit faible — ce qui validerait que les scores élevés obtenus sur les parcelles PNB reflètent une vraie pertinence de diagBruit, et pas un biais "toujours haut". Pour ça, on veut confronter diagBruit à **toute la gamme de niveaux de bruit cartographiés** (du plus faible au plus fort), pas seulement à des parcelles "calmes" — d'où l'absence volontaire de seuil minimal dans les critères ci-dessous.

**Sources mobilisées** (en plus des couches déjà utilisées aux étapes 1-2) :
- `data/CBS_AGGLO/` : 6 fichiers (routier/ferroviaire/aérien × Lden/Ln). Champ `ISOPHONE` = palier de dB (55/60/65/70/75 pour le routier). CRS hétérogènes : routier en Lambert-93 (millésime 2021), ferroviaire et aérien en WGS84 (millésime 2025).
- `data/BDNB/batiment-construction.shp` (Base Nationale des Bâtiments, département 13, 996 959 bâtiments, Lambert-93) : sert uniquement à vérifier qu'une parcelle témoin porte au moins un bâtiment, pour rester comparable aux parcelles PNB (toutes bâties par construction).

**Critères de sélection retenus** :
1. **Groupe A (parcelles exposées, tous niveaux)** : croise ≥ 1 objet routier ou ferroviaire (CBS Lden ou Ln), **sans seuil de dB minimal** — décision volontaire de Martin, pour couvrir toute la gamme 55-75 dB et tester si le score diagBruit suit une gradation cohérente avec le niveau de bruit cartographié.
2. Ne croise aucun objet aérien (CBS) — sur les 3 sources de bruit, seule la combinaison routier/ferroviaire est dans le périmètre du projet.
3. N'est pas une parcelle déjà traitée à l'étape 2 (PNB).
4. Contient au moins un bâtiment (BDNB) — pour rester comparable aux parcelles PNB.
5. **Groupe B (aucune exposition cartographiée)** : dans un buffer de 50 m autour d'un objet **routier ou ferroviaire uniquement** (pas aérien), sans en intersecter aucun. Mêmes critères 2/3/4 appliqués.

**Contrôle qualité** : diagnostic OGC appliqué sur les couches routier+ferroviaire+aérien (CRS, géométries invalides/vides) — 1 seule géométrie invalide détectée (auto-intersection mineure), corrigée avec `make_valid()`. Le souci d'emprise BDNB anticipé (bâtiments "fictifs") était bien réel : 4 065 bâtiments sur 996 959 ont `fictive_ge = True` (géométrie non relevée) — exclus systématiquement dans `charger_batiments_bdnb`.

**Millésimes/CRS hétérogènes entre couches** : accepté comme limite par Martin (pas de blocage) ; harmonisation Lambert-93 appliquée dans `charger_couches_cbs`.

**Implémenté** (`echantillon_temoin.py`) : `charger_couches_cbs`, `diagnostiquer_couche`, `charger_batiments_bdnb`, `corriger_geometries_invalides`, `ids_parcelles_intersectant`, `ids_parcelles_avec_batiment`, `construire_echantillon_temoin`.

**Problème de performance rencontré et résolu** : la construction s'est d'abord bloquée **plus de 15h sans terminer** avec un `gpd.sjoin` classique. Cause identifiée : certains objets de la couche routier/ferroviaire ont une géométrie extrêmement complexe (jusqu'à **2,3 millions de sommets** pour le plus gros, 1 591 objets sur 52 169 dépassant 1 000 sommets et représentant à eux seuls 92 % de la surface totale de la couche). Leur emprise (bounding box) couvre une si grande partie du territoire que l'index spatial d'un `sjoin` standard ne filtre plus rien : le test d'intersection exact est relancé pour la quasi-totalité des 836 749 parcelles à chaque fois. Solution : `ids_parcelles_intersectant` boucle sur les objets de la couche avec des géométries **préparées** (`shapely.prepare`) et un test vectorisé (`shapely.intersects`), plutôt qu'un `sjoin` — le pire objet (2,3M sommets) contre les 836 749 parcelles ne prend alors que 39 secondes, contre un blocage total avec l'approche standard. La jointure `parcelles x bâtiments BDNB` (géométries simples, pas de cas pathologique) reste en `gpd.sjoin` classique, très rapide (~20s pour 836k x 890k).

**Résultat de la construction complète** (84,7 min au total avec le correctif) :
- Groupe A (exposé routier/ferroviaire, tous niveaux) : **363 578 parcelles**
- Groupe B (à moins de 50 m, non exposé) : **57 168 parcelles**
- **Total témoin : 420 746 parcelles** — sauvegardé dans `data/parcelles_temoin.gpkg`

**Volume trop important, filtre de proximité appliqué (comme anticipé par Martin)** : ~20 fois le volume des 21 547 parcelles PNB, impossible à interroger intégralement via diagBruit (~1 jour d'appels). Volumes testés avec un buffer de proximité autour des parcelles PNB :

| Distance aux parcelles PNB | Parcelles témoin retenues (A / B) |
|---|---|
| 100 m | 81 762 (75 618 / 6 144) |
| 250 m | 119 276 (109 172 / 10 104) |
| 500 m | 151 988 (137 993 / 13 995) |
| 1000 m | 190 038 (170 631 / 19 407) |

Même à 100 m, le volume reste trop important pour un appel exhaustif.

**Échantillonnage stratifié retenu (proposition de Martin, pour garantir la représentativité)** : plutôt qu'un tirage aléatoire global sur un buffer unique (qui sur-représenterait mécaniquement les parcelles les plus proches), tirage de **5 000 parcelles par bande de distance** à la parcelle PNB la plus proche (distance minimale exacte calculée via `gpd.sjoin_nearest`, pas une simple différence de buffers cumulés) :

| Bande de distance | Candidats disponibles | Tirés (A / B) |
|---|---|---|
| 0-50 m | 59 118 | 5 000 (4 646 A / 354 B) |
| 50-100 m | 22 659 | 5 000 (4 498 A / 502 B) |
| 100-250 m | 37 522 | 5 000 (4 481 A / 519 B) |

**Total échantillon témoin : 15 000 parcelles** (même ordre de grandeur que les 21 547 parcelles PNB), sauvegardé dans `data/parcelles_temoin_echantillon.gpkg`. La composition A/B (~90 % A / ~10 % B) est stable d'une bande à l'autre.

**Appels diagBruit sur le témoin** : lancés avec les mêmes registres que l'étape 2 mais des fichiers séparés (`data/sonoscores_temoin.csv`, `data/classement_sonore_temoin.csv`, `data/cartes_bruit_temoin.csv`), pour ne pas mélanger avec les résultats PNB.

**Résultats** (52,1 min pour le run principal + 2 relances idempotentes) :
- 14 999 parcelles traitées avec succès sur 15 000.
- **1 parcelle en échec systématique** (`13005000BM0176`, commune 13005, groupe A, 12 m d'une parcelle PNB) : erreur 500 reproductible à chaque appel, isolée par dichotomie (élimination progressive des lots). Exclue de l'étude et archivée dans `data/parcelles_temoin_hors_service_diagbruit.gpkg` plutôt que silencieusement ignorée — cause probablement une géométrie particulière que diagBruit ne sait pas traiter, à signaler à l'équipe diagBruit si besoin.
- **Score moyen 3,83, médian 3** sur le témoin — nettement plus bas que les parcelles PNB (moyenne 8,46, médiane 9, voir volet 1). C'est un signal encourageant pour la pertinence de diagBruit : les parcelles PNB confirmées ressortent bien avec des scores nettement plus élevés que ce témoin plus large et plus diversifié.

**Point d'interprétation, résolu avec Martin** : 1 174 parcelles témoin (7,8 %) ont un `score = 0` accompagné du même flag manquant (`isMultiExposedLandSources`) que l'anomalie dept. 84 de l'étape 2 — mais cette fois **toutes en département 13**. Confirmé par Martin : `score = 0` signifie que **diagBruit n'a aucune donnée à cet endroit** (pas une vraie zone de calme mesurée). Décision : ce n'est pas strictement identique à une zone calme, mais on peut l'assimiler à un **score bas légitime** pour l'analyse — ces 1 174 parcelles sont conservées telles quelles, pas isolées à part.

**Parcelle en échec diagBruit, référence détaillée** :

| Champ | Valeur |
|---|---|
| Code INSEE (commune) | 13005 |
| Préfixe (feuille) | 000 |
| Section | BM |
| Numéro | 176 |
| Identifiant complet | `13005000BM0176` |
| Groupe | A |
| Distance à la parcelle PNB la plus proche | 12 m |

### Comparaison PNB vs témoin (points 1 et 2, implémentés)

**Implémenté** (`analyse_pnb.py` + notebook) : `charger_temoin`, `comparer_pnb_temoin`, `statistiques_par_groupe`. Deux boîtes à moustaches ajoutées au notebook (couleurs bleu/orange pour PNB/Témoin, aqua/jaune — validées CVD-safe avec avertissement de contraste géré par les étiquettes directes — pour groupe A/B), avec `alt.data_transformers.disable_max_rows()` nécessaire vu le volume (36 546 lignes cumulées).

**Résultats — chaîne de validation cohérente sur les trois niveaux** :

| Ensemble | Nombre | Score moyen | Score médian |
|---|---|---|---|
| Parcelles PNB | 21 547 | **8,46** | 9 |
| Témoin — groupe A (exposé routier/ferroviaire) | 13 624 | **4,10** | 3 |
| Témoin — groupe B (non exposé, à proximité) | 1 375 | **1,16** | 1 |

Le score décroît strictement dans l'ordre attendu (PNB > témoin exposé > témoin non exposé), ce qui valide directement l'hypothèse de départ de Martin : diagBruit ne donne pas systématiquement un score élevé, il distingue bien les niveaux de risque réels.

### Gradation du score selon le niveau de bruit (point 3, implémenté)

**Implémenté** (`echantillon_temoin.isophone_max_par_parcelle`, `analyse_pnb.gradation_score_isophone`) : pour chaque parcelle du groupe A du témoin, calcul du palier `ISOPHONE` (dB) le plus élevé parmi les objets routier/ferroviaire qui la touchent (même technique de géométries préparées que pour la construction du témoin — 29 s pour 13 625 parcelles, aucune valeur manquante). Champ unifié entre la couche routière (`ISOPHONE`, majuscules) et ferroviaire (`isophone`, minuscules), fusionnées en une seule colonne différente selon la source lors de l'empilement.

**Résultat — gradation nette et quasi monotone** :

| Niveau de bruit (dB) | Nb parcelles | Score moyen | Score médian |
|---|---|---|---|
| 50 | 9 | 2,78 | 3 |
| 55 | 8 854 | 3,27 | 3 |
| 60 | 2 753 | 4,64 | 5 |
| 65 | 1 594 | 6,58 | 7 |
| 70 | 345 | 8,49 | 9 |
| 75 | 69 | 10,16 | 10 |

**Corrélation de Pearson score / niveau de bruit : 0,66** (positive et forte). Le score diagBruit suit bien le niveau de bruit cartographié — pas de seuil brutal ni de plafonnement prématuré, une progression régulière du calme (2,8) au très exposé (10,2).

**À trancher/discuter avec Martin** : cette 1ère série de résultats (points 1, 2, 3) est prête à être revue ensemble avant de poursuivre — notamment décider si on formalise une restitution (étape 4) ou si d'autres analyses sont à ajouter avant.

### Traduction opérationnelle : alerte avant construction (point 4, implémenté)

**Retour de Martin sur les points 1-3** : les résultats sont cohérents avec le comportement attendu, mais les comparaisons PNB/témoin et la gradation ne démontrent que la fiabilité interne de diagBruit ("on a testé, ça marche sans bug"). Ce qui doit être mis en avant maintenant : diagBruit, puisqu'il se comporte bien, doit pouvoir servir à **alerter un porteur de projet** travaillant sur une parcelle à score élevé (≥ 7), en le signalant explicitement comme présentant les caractéristiques acoustiques d'un point noir du bruit, avant même que le bâtiment ne soit construit.

**Traduction visuelle retenue** : le seuil "score élevé/faible" (déjà utilisé aux points 1-3, `SEUIL_SCORE_FAIBLE = 6`) est réutilisé tel quel — un score entier de 0 à 12 rend "≤6/>6" strictement équivalent à "≥7" (confirmé par Martin), donc aucun nouveau seuil à définir.

- **Chiffre clé** : `taux_alerte(sonoscores, seuil)` — pourcentage de parcelles PNB dont le score aurait déclenché une alerte (score > seuil).
- **Carte** : `parcelles_avec_alerte(parcelles_pnb, sonoscores, seuil)` — fusionne géométrie et score, ajoute la colonne `alerte`. Centroïdes calculés en Lambert-93 (CRS projeté, plus fiable) puis reprojetés en WGS84 pour un scatter géographique altair (`mark_circle` + `longitude`/`latitude` + `.project(type="mercator")`), plutôt qu'un géoshape des polygones complets (trop lourd à l'échelle de l'AMPM pour 21 547 parcelles, un point par parcelle suffit à montrer la répartition spatiale).
- **Palette** : rouge/vert du **statut** (`#d03b3b` alerte / `#0ca30c` pas d'alerte, skill `dataviz`), volontairement différente du bleu/orange utilisé aux points 1-3 — ce graphique change de registre, de la description vers l'action.

**Implémenté** (`analyse_pnb.py` : `taux_alerte`, `parcelles_avec_alerte` + notebook, section "4. Traduction opérationnelle").

**Résultat** : **89 % des 21 547 parcelles PNB** auraient déclenché une alerte diagBruit (score > 6) avant la construction du bâtiment qui en a fait un point noir du bruit. La carte confirme que ces parcelles à alerte sont réparties sur l'ensemble de l'AMPM, pas concentrées sur un secteur particulier.

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

- L'analyse comparative de l'étape 3 (dépend des résultats de l'étape 2, en cours de planification)

~~Étape 1 (traitement du fichier PNB, rattachement aux parcelles)~~ → **terminée et validée par Martin** (21 705 parcelles PNB identifiées). ~~Contrat de l'API diagBruit~~ → **connu**, l'étape 2 peut démarrer.

## Points encore ouverts

- Format final du livrable et destinataire précis (étape 4)
- Méthode de constitution de l'échantillon témoin non-PNB — repoussé après cette première analyse descriptive (voir étape 3)

## Fichiers concernés

- `budget/grist.py` — modèle du pattern d'appel API
- `notebooks/budget.ipynb` — modèle du pattern notebook + altair
- `requirements.txt` — ajout de `geopandas`, `shapely`, `pyproj`, `pyogrio`
- `.gitignore` — `analyse_pnb_ampm/data/` déjà exclu du versioning

## Vérification (une fois l'implémentation démarrée)

- Les modules squelettes s'importent sans erreur (`python -c "import analyse_pnb_ampm.pnb_parcelles"`, etc.)
- Le notebook s'ouvre et exécute ses cellules d'import sans erreur (même sans données réelles, avec des données factices/vides)
- Une fois le fichier PNB validé par Martin : la jointure spatiale de l'étape 1 produit une liste de parcelles avec un identifiant exploitable pour l'étape 2
