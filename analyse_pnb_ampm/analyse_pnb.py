"""Analyse descriptive des scores diagBruit obtenus sur les parcelles PNB.

Voir plan_action.md, section "Étape 3 - Volet 1", pour le détail des choix
(seuil de score faible, analyse des flags...).
"""

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
