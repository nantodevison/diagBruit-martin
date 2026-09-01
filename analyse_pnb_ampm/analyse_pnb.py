"""Analyse descriptive des scores diagBruit obtenus sur les parcelles PNB, et comparaison
avec l'échantillon témoin.

Voir plan_action.md, section "Étape 3", pour le détail des choix (seuil de score
faible, analyse des flags, critères du témoin...).
"""

import geopandas as gpd
import pandas as pd

SEUIL_SCORE_FAIBLE = 6

FLAGS = [
    "hasClassificationWarning",
    "hasNoisemapWarning",
    "isMultiExposedSources",
    "isMultiExposedLandDistinctTypeSources",
    "isMultiExposedLdenLn",
    "isPriorityZone",
    "isMultiExposedLandSources",
]


def charger_sonoscores(chemin_csv: str) -> pd.DataFrame:
    """Charge le registre des scores diagBruit par parcelle (sortie de l'étape 2)."""
    return pd.read_csv(chemin_csv)


def statistiques_scores(sonoscores: pd.DataFrame) -> pd.Series:
    """Statistiques descriptives globales du score (moyenne, médiane, quartiles, min/max)."""
    return sonoscores["score"].describe()


def distribution_scores(sonoscores: pd.DataFrame) -> pd.DataFrame:
    """Nombre de parcelles par valeur de score, pour l'histogramme."""
    return (
        sonoscores["score"]
        .value_counts()
        .sort_index()
        .rename_axis("score")
        .reset_index(name="nb_parcelles")
    )


def _etiquette_groupe(score: int, seuil: int) -> str:
    """Étiquette du groupe (score faible/élevé) pour une valeur de score donnée."""
    return f"Score faible (≤{seuil})" if score <= seuil else f"Score élevé (>{seuil})"


def repartition_score_eleve_faible(sonoscores: pd.DataFrame, seuil: int = SEUIL_SCORE_FAIBLE) -> pd.DataFrame:
    """Répartit les parcelles en deux groupes (score faible / score élevé), pour le résumé en camembert."""
    groupes = sonoscores["score"].apply(_etiquette_groupe, seuil=seuil)
    return groupes.value_counts().rename_axis("groupe").reset_index(name="nb_parcelles")


def prevalence_flags_par_groupe(sonoscores: pd.DataFrame, seuil: int = SEUIL_SCORE_FAIBLE) -> pd.DataFrame:
    """Prévalence (% à True) de chacun des 7 flags, pour le groupe score faible et le groupe score élevé.

    Permet de repérer un flag "dominant" (nettement sur-représenté) dans le groupe à score
    faible, indice de ce qui explique un score bas malgré un bâtiment PNB confirmé.
    """
    sonoscores = sonoscores.copy()
    sonoscores["groupe"] = sonoscores["score"].apply(_etiquette_groupe, seuil=seuil)

    lignes = []
    for flag in FLAGS:
        prevalence_par_groupe = sonoscores.groupby("groupe")[flag].mean() * 100
        for groupe, prevalence_pct in prevalence_par_groupe.items():
            lignes.append({"flag": flag, "groupe": groupe, "prevalence_pct": prevalence_pct})

    return pd.DataFrame(lignes)


def charger_temoin(chemin_scores_csv: str, chemin_echantillon_gpkg: str) -> pd.DataFrame:
    """Charge les scores diagBruit du témoin (étape 3, volet 2) et les enrichit avec le groupe A/B."""
    scores = pd.read_csv(chemin_scores_csv)
    echantillon = gpd.read_file(chemin_echantillon_gpkg)[
        ["id_parcelle", "groupe", "bande_distance_pnb", "distance_pnb_m"]
    ]
    return scores.merge(echantillon, on="id_parcelle", how="left")


def comparer_pnb_temoin(sonoscores_pnb: pd.DataFrame, sonoscores_temoin: pd.DataFrame) -> pd.DataFrame:
    """Assemble les scores PNB et témoin dans une seule table (colonne `source`), pour comparaison."""
    pnb = sonoscores_pnb[["id_parcelle", "score"]].assign(source="PNB")
    temoin = sonoscores_temoin[["id_parcelle", "score"]].assign(source="Témoin")
    return pd.concat([pnb, temoin], ignore_index=True)


def statistiques_par_groupe(donnees: pd.DataFrame, colonne_groupe: str) -> pd.DataFrame:
    """Statistiques descriptives du score (moyenne, médiane, quartiles...) par valeur de `colonne_groupe`."""
    return donnees.groupby(colonne_groupe)["score"].describe()


def taux_alerte(sonoscores: pd.DataFrame, seuil: int = SEUIL_SCORE_FAIBLE) -> float:
    """Pourcentage de parcelles dont le score aurait déclenché une alerte (score > seuil).

    Traduction opérationnelle du seuil déjà utilisé pour distinguer score élevé/faible :
    une parcelle à score > seuil est celle que diagBruit aurait signalée comme présentant
    des caractéristiques de point noir du bruit, avant même la construction du bâtiment.
    """
    return (sonoscores["score"] > seuil).mean() * 100


def parcelles_avec_alerte(
    parcelles_pnb: gpd.GeoDataFrame, sonoscores: pd.DataFrame, seuil: int = SEUIL_SCORE_FAIBLE
) -> gpd.GeoDataFrame:
    """Fusionne les parcelles PNB (géométrie) avec leur score, et ajoute la colonne `alerte`.

    `alerte` est vraie si le score dépasse `seuil` : c'est le cas qui aurait justifié un
    signalement à un porteur de projet avant la construction du bâtiment devenu PNB.
    """
    fusion = parcelles_pnb.merge(sonoscores[["id_parcelle", "score"]], on="id_parcelle", how="inner")
    fusion["alerte"] = fusion["score"] > seuil
    return fusion


def gradation_score_isophone(sonoscores_temoin: pd.DataFrame, chemin_isophone_csv: str) -> pd.DataFrame:
    """Moyenne et médiane du score par palier ISOPHONE (dB) touchant la parcelle (groupe A du témoin).

    `chemin_isophone_csv` vient de `echantillon_temoin.isophone_max_par_parcelle`.
    """
    isophone = pd.read_csv(chemin_isophone_csv)
    fusion = sonoscores_temoin.merge(isophone, on="id_parcelle", how="inner")
    return (
        fusion.groupby("isophone_max")["score"]
        .agg(nb_parcelles="count", score_moyen="mean", score_median="median")
        .reset_index()
    )
