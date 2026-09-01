"""Construit l'échantillon témoin de parcelles pour l'étape 3 (volet 2).

Voir plan_action.md, section "Étape 3 - Volet 2", pour le détail des critères de
sélection (groupe A : parcelles exposées au bruit routier/ferroviaire, tous niveaux
confondus ; groupe B : parcelles à moins de 50 m d'un objet routier/ferroviaire sans
le toucher).
"""

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

CRS_LAMBERT93 = "EPSG:2154"
BUFFER_M = 50

FICHIERS_CBS_ROUTIER_FERROVIAIRE = [
    "data/CBS_AGGLO/N_BRUIT_ISOPHONE_ROUTIER_A_LDEN.shp",
    "data/CBS_AGGLO/N_BRUIT_ISOPHONE_ROUTIER_A_LN.shp",
    "data/CBS_AGGLO/observatoire-du-bruit-n_bruit_isophone_ferroviaire_a_lden.shp",
    "data/CBS_AGGLO/fr-observatoire-du-bruit-bruit_isophone_ferroviaire_a_ln.shp",
]

FICHIERS_CBS_AERIEN = [
    "data/CBS_AGGLO/bruit-aerien-type-a-lden-sur-24h-etude-de-bruit-impedance-ingenierie.shp",
    "data/CBS_AGGLO/bruit-aerien-type-a-ln-22h-6h-etude-de-bruit-impedance-ingenierie.shp",
]


def charger_couches_cbs(chemins: list[str]) -> gpd.GeoDataFrame:
    """Charge et empile plusieurs couches CBS, harmonisées en Lambert-93.

    Les rares géométries invalides (auto-intersections) sont corrigées avec
    `make_valid()` plutôt que laissées telles quelles, pour ne pas fausser les
    jointures spatiales qui suivent.
    """
    couches = []
    for chemin in chemins:
        gdf = gpd.read_file(chemin)
        if gdf.crs != CRS_LAMBERT93:
            gdf = gdf.to_crs(CRS_LAMBERT93)
        gdf["geometry"] = gdf.geometry.make_valid()
        couches.append(gdf)
    return gpd.GeoDataFrame(pd.concat(couches, ignore_index=True), crs=CRS_LAMBERT93)


def diagnostiquer_couche(gdf: gpd.GeoDataFrame, nom: str) -> list[str]:
    """Contrôle qualité minimal (diagnostic OGC) d'une couche isolée."""
    anomalies = []
    if gdf.crs is None:
        anomalies.append(f"{nom} : CRS non défini.")
    nb_invalides = int((~gdf.geometry.is_valid).sum())
    if nb_invalides:
        anomalies.append(f"{nom} : {nb_invalides} géométrie(s) invalide(s).")
    nb_vides = int(gdf.geometry.is_empty.sum())
    if nb_vides:
        anomalies.append(f"{nom} : {nb_vides} géométrie(s) vide(s).")
    return anomalies


def charger_batiments_bdnb(chemin: str, emprise: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    """Charge les bâtiments BDNB filtrés sur une emprise, en excluant les géométries fictives (champ `fictive_ge`)."""
    gdf = gpd.read_file(chemin, bbox=emprise)
    return gdf[~gdf["fictive_ge"]].reset_index(drop=True)


def corriger_geometries_invalides(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Corrige les géométries invalides avec `make_valid()`.

    Des géométries invalides (auto-intersections) glissées dans une jointure spatiale
    peuvent la ralentir énormément, voire la bloquer, sur de gros volumes — d'où cette
    correction systématique avant toute jointure, plutôt qu'un simple signalement.
    """
    gdf = gdf.copy()
    gdf["geometry"] = gdf.geometry.make_valid()
    return gdf


def ids_parcelles_intersectant(parcelles: gpd.GeoDataFrame, couche: gpd.GeoDataFrame, verbose: bool = False) -> set:
    """Identifiants de parcelles qui intersectent au moins un objet de la couche donnée.

    Boucle sur les objets de `couche` avec des géométries préparées (`shapely.prepare`)
    plutôt qu'un `sjoin` classique. Les couches CBS contiennent quelques objets à la
    géométrie extrêmement complexe (jusqu'à plus de 2 millions de sommets pour l'un
    d'eux) : leur emprise (bounding box) couvre une si grande partie du territoire que
    l'index spatial d'un `sjoin` standard ne filtre plus rien, et le test d'intersection
    exact est alors relancé pour la quasi-totalité des parcelles — un blocage de plusieurs
    heures a été observé en pratique avec `gpd.sjoin` sur ces couches. Une géométrie
    préparée reste rapide même dans ce cas (quelques dizaines de secondes pour le plus
    gros objet, contre un blocage total avec l'approche standard).
    """
    geoms_couche = couche.geometry.values
    shapely.prepare(geoms_couche)
    geoms_parcelles = parcelles.geometry.values
    touche = np.zeros(len(geoms_parcelles), dtype=bool)
    for i, geom in enumerate(geoms_couche):
        touche |= shapely.intersects(geom, geoms_parcelles)
        if verbose and (i + 1) % 2000 == 0:
            print(f"    ... {i + 1}/{len(geoms_couche)} objets traités", flush=True)
    return set(parcelles["id"].values[touche])


def isophone_max_par_parcelle(parcelles: gpd.GeoDataFrame, routier_ferroviaire: gpd.GeoDataFrame, verbose: bool = False) -> pd.Series:
    """Palier ISOPHONE (dB) le plus élevé touchant chaque parcelle, indexé par `id_parcelle`.

    Les couches routier (`ISOPHONE`) et ferroviaire (`isophone`) ont le même champ dans une
    casse différente une fois empilées par `charger_couches_cbs` : unifiées ici. Même
    technique de géométries préparées que `ids_parcelles_intersectant` (voir sa docstring)
    pour éviter le blocage lié aux objets à géométrie extrêmement complexe.
    """
    isophone_unifie = routier_ferroviaire["ISOPHONE"].fillna(routier_ferroviaire["isophone"]).to_numpy(dtype=float)
    geoms_couche = routier_ferroviaire.geometry.values
    shapely.prepare(geoms_couche)
    geoms_parcelles = parcelles.geometry.values

    isophone_max = np.full(len(geoms_parcelles), np.nan)
    for i, (geom, isophone) in enumerate(zip(geoms_couche, isophone_unifie)):
        touche = shapely.intersects(geom, geoms_parcelles)
        if touche.any():
            isophone_max = np.fmax(isophone_max, np.where(touche, isophone, np.nan))
        if verbose and (i + 1) % 5000 == 0:
            print(f"    ... {i + 1}/{len(geoms_couche)} objets traités", flush=True)

    return pd.Series(isophone_max, index=parcelles["id_parcelle"].values, name="isophone_max")


def ids_parcelles_avec_batiment(parcelles: gpd.GeoDataFrame, batiments: gpd.GeoDataFrame) -> set:
    """Identifiants de parcelles qui contiennent au moins un bâtiment (BDNB)."""
    jointure = gpd.sjoin(parcelles[["id", "geometry"]], batiments[["geometry"]], predicate="intersects")
    return set(jointure["id"])


def construire_echantillon_temoin(
    parcelles: gpd.GeoDataFrame,
    routier_ferroviaire: gpd.GeoDataFrame,
    aerien: gpd.GeoDataFrame,
    batiments: gpd.GeoDataFrame,
    ids_parcelles_pnb: set,
    buffer_m: int = BUFFER_M,
) -> gpd.GeoDataFrame:
    """Construit l'échantillon témoin (groupe A : exposé routier/ferroviaire ; groupe B : à proximité sans exposition).

    Toutes les couches doivent déjà être dans le même CRS (Lambert-93) et `parcelles`
    doit contenir au moins les colonnes `id`, `commune`, `prefixe`, `section`, `numero`,
    `contenance`, `geometry`.
    """
    parcelles = corriger_geometries_invalides(parcelles)

    print("  jointure parcelles x routier/ferroviaire...", flush=True)
    ids_expose_route_fer = ids_parcelles_intersectant(parcelles, routier_ferroviaire, verbose=True)
    print("  jointure parcelles x aerien...", flush=True)
    ids_expose_aerien = ids_parcelles_intersectant(parcelles, aerien)
    print("  jointure parcelles x batiments BDNB...", flush=True)
    ids_avec_batiment = ids_parcelles_avec_batiment(parcelles, batiments)

    print("  buffer 50 m routier/ferroviaire...", flush=True)
    routier_ferroviaire_buffer = routier_ferroviaire.assign(geometry=routier_ferroviaire.geometry.buffer(buffer_m))
    print("  jointure parcelles x buffer routier/ferroviaire...", flush=True)
    ids_proche_route_fer = ids_parcelles_intersectant(parcelles, routier_ferroviaire_buffer, verbose=True)

    exclusions = ids_expose_aerien | ids_parcelles_pnb

    ids_groupe_a = (ids_expose_route_fer - exclusions) & ids_avec_batiment
    ids_groupe_b = (ids_proche_route_fer - ids_expose_route_fer - exclusions) & ids_avec_batiment

    temoin = parcelles[parcelles["id"].isin(ids_groupe_a | ids_groupe_b)].copy()
    temoin["groupe"] = temoin["id"].apply(lambda i: "A" if i in ids_groupe_a else "B")

    return temoin.rename(
        columns={"id": "id_parcelle", "contenance": "surface_parcelle_m2"}
    )[["id_parcelle", "commune", "prefixe", "section", "numero", "surface_parcelle_m2", "groupe", "geometry"]].reset_index(
        drop=True
    )
