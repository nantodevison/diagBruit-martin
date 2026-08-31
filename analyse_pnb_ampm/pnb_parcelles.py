"""Rattache les bâtiments PNB (points noirs du bruit) aux parcelles cadastrales de l'AMPM.

Voir plan_action.md, section "Étape 1", pour le détail des choix (surface de recouvrement
maximale en cas de bâtiment à cheval sur plusieurs parcelles, bâtiments non rattachés isolés
plutôt qu'exclus...).
"""

import geopandas as gpd
import pandas as pd


def charger_batiments_pnb(chemin_gpkg: str) -> gpd.GeoDataFrame:
    """Charge les bâtiments PNB depuis le fichier GeoPackage fourni par Martin."""
    return gpd.read_file(chemin_gpkg)


def charger_parcelles_ampm(chemin: str, emprise: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    """Charge les parcelles cadastrales, filtrées sur une emprise (bbox) pour éviter de charger le fichier entier.

    L'emprise doit être exprimée dans le CRS natif du fichier source (le fichier n'étant pas
    encore chargé, on ne peut pas la reprojeter automatiquement à ce stade).
    """
    return gpd.read_file(chemin, bbox=emprise)


def diagnostiquer_couches(batiments: gpd.GeoDataFrame, parcelles: gpd.GeoDataFrame) -> list[str]:
    """Contrôle qualité (diagnostic OGC) des deux couches avant la jointure spatiale.

    Retourne la liste des anomalies détectées (liste vide si tout est cohérent).
    """
    anomalies = []

    if batiments.crs is None or parcelles.crs is None:
        anomalies.append("CRS non défini sur au moins une des deux couches.")
    elif batiments.crs != parcelles.crs:
        anomalies.append(f"CRS différents : bâtiments={batiments.crs}, parcelles={parcelles.crs}.")

    for nom, gdf in [("bâtiments", batiments), ("parcelles", parcelles)]:
        nb_invalides = int((~gdf.geometry.is_valid).sum())
        if nb_invalides:
            anomalies.append(f"{nb_invalides} géométrie(s) invalide(s) dans la couche {nom}.")
        nb_vides = int(gdf.geometry.is_empty.sum())
        if nb_vides:
            anomalies.append(f"{nb_vides} géométrie(s) vide(s) dans la couche {nom}.")

    # comparer les emprises n'a de sens que si les deux couches sont dans le même CRS
    if not batiments.empty and not parcelles.empty and batiments.crs == parcelles.crs:
        xmin_b, ymin_b, xmax_b, ymax_b = batiments.total_bounds
        xmin_p, ymin_p, xmax_p, ymax_p = parcelles.total_bounds
        chevauchement = not (xmax_b < xmin_p or xmin_b > xmax_p or ymax_b < ymin_p or ymin_b > ymax_p)
        if not chevauchement:
            anomalies.append(
                "Les emprises des bâtiments et des parcelles ne se chevauchent pas du tout "
                "(possible décalage de projection)."
            )

    return anomalies


def rattacher_batiments_parcelles(
    batiments: gpd.GeoDataFrame, parcelles: gpd.GeoDataFrame
) -> tuple[gpd.GeoDataFrame, pd.DataFrame, gpd.GeoDataFrame]:
    """Rattache chaque bâtiment PNB à une parcelle cadastrale.

    Un bâtiment à cheval sur plusieurs parcelles est rattaché à celle avec la plus grande
    surface de recouvrement. Les bâtiments sans parcelle correspondante (ex. domaine public)
    sont isolés dans une table séparée plutôt qu'exclus silencieusement.

    Retourne (parcelles_pnb, rattachements_batiments_parcelles, batiments_non_rattaches).
    """
    if parcelles.crs != batiments.crs:
        # les deux fichiers viennent de sources indépendantes (BD TOPO vs cadastre DGFiP),
        # rien ne garantit qu'ils soient dans le même CRS au départ
        parcelles = parcelles.to_crs(batiments.crs)

    intersections = gpd.overlay(
        batiments[["ID", "geometry"]].rename(columns={"ID": "id_batiment"}),
        parcelles[["id", "commune", "contenance", "geometry"]].rename(columns={"id": "id_parcelle"}),
        how="intersection",
    )
    intersections["surface_recouvrement_m2"] = intersections.geometry.area

    idx_meilleur_recouvrement = intersections.groupby("id_batiment")["surface_recouvrement_m2"].idxmax()
    rattachements = intersections.loc[idx_meilleur_recouvrement].copy()

    surface_batiments = batiments.set_index("ID").geometry.area
    rattachements["part_recouvrement_pct"] = (
        rattachements["surface_recouvrement_m2"] / rattachements["id_batiment"].map(surface_batiments) * 100
    )

    rattachements_batiments_parcelles = rattachements[
        ["id_batiment", "id_parcelle", "surface_recouvrement_m2", "part_recouvrement_pct"]
    ].reset_index(drop=True)

    nb_batiments_par_parcelle = rattachements_batiments_parcelles.groupby("id_parcelle").size()

    parcelles_pnb = (
        parcelles[parcelles["id"].isin(nb_batiments_par_parcelle.index)]
        .rename(columns={"id": "id_parcelle", "contenance": "surface_parcelle_m2"})[
            ["id_parcelle", "commune", "surface_parcelle_m2", "geometry"]
        ]
        .copy()
    )
    parcelles_pnb["nb_batiments_pnb"] = parcelles_pnb["id_parcelle"].map(nb_batiments_par_parcelle)

    batiments_rattaches = set(rattachements_batiments_parcelles["id_batiment"])
    batiments_non_rattaches = (
        batiments[~batiments["ID"].isin(batiments_rattaches)].rename(columns={"ID": "id_batiment"}).reset_index(drop=True)
    )

    return parcelles_pnb.reset_index(drop=True), rattachements_batiments_parcelles, batiments_non_rattaches
