"""Interroge l'API diagBruit pour caractériser les parcelles PNB (sonoscore + niveaux de bruit).

Voir plan_action.md, section "Étape 2", pour le détail des choix (endpoint, cadence,
idempotence...).
"""

import os
import time

import geopandas as gpd
import pandas as pd
import requests
from dotenv import load_dotenv
from shapely.geometry import MultiPolygon, mapping

load_dotenv()

URL_DIAGBRUIT_API = os.getenv("URL_DIAGBRUIT_API")

TAILLE_BLOC = 100
DELAI_ENTRE_APPELS_S = 0.2


def parcelles_a_traiter(parcelles_pnb: gpd.GeoDataFrame, chemin_registre: str) -> gpd.GeoDataFrame:
    """Exclut les parcelles déjà présentes dans le registre des résultats diagBruit (idempotence)."""
    if not os.path.exists(chemin_registre):
        return parcelles_pnb
    deja_traitees = set(pd.read_csv(chemin_registre)["id_parcelle"])
    return parcelles_pnb[~parcelles_pnb["id_parcelle"].isin(deja_traitees)]


def geometrie_vers_payload(geometry) -> list:
    """Convertit une géométrie shapely (Polygon ou MultiPolygon) au format attendu par l'API diagBruit."""
    if geometry.geom_type == "Polygon":
        geometry = MultiPolygon([geometry])
    return mapping(geometry)["coordinates"]


def construire_items(parcelles: gpd.GeoDataFrame) -> list[dict]:
    """Construit la liste `items` du corps de requête `/diag/generate/from-geometries`.

    Les géométries doivent être en WGS84 (lon/lat) pour l'API ; les parcelles issues de
    l'étape 1 sont en Lambert-93, d'où la reprojection ici.
    """
    parcelles_wgs84 = parcelles.to_crs("EPSG:4326")
    return [
        {
            "parcelle": {
                "code_insee": ligne["commune"],
                "section": ligne["section"],
                "numero": ligne["numero"],
            },
            "populate": {"zones": False, "isolation": False},
            "geometry": geometrie_vers_payload(ligne.geometry),
        }
        for _, ligne in parcelles_wgs84.iterrows()
    ]


def appeler_diag_generate(items: list[dict]) -> list[dict]:
    """Appelle `/diag/generate/from-geometries` pour un bloc d'items et retourne la liste `diagnostics`."""
    url = f"{URL_DIAGBRUIT_API}/diag/generate/from-geometries"
    reponse = requests.post(url, json={"items": items})
    reponse.raise_for_status()
    return reponse.json()["diagnostics"]


def diagnostics_vers_tables(diagnostics: list[dict], ids_parcelles: list[str]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Aplatit une liste de diagnostics diagBruit en 3 tables (sonoscores, classement sonore, cartes de bruit).

    `ids_parcelles` doit être dans le même ordre que les items envoyés à l'API (la réponse
    n'échoue pas l'identifiant de parcelle envoyé).
    """
    lignes_sonoscores = []
    lignes_classement = []
    lignes_cartes_bruit = []

    for id_parcelle, diag in zip(ids_parcelles, diagnostics):
        d = diag["diagnostic"]

        lignes_sonoscores.append({"id_parcelle": id_parcelle, "score": d["score"], "max_db_lden": d["max_db_lden"], "min_db_lden": d["min_db_lden"], **d["flags"]})

        for classement in d["soundclassification_intersections"]:
            lignes_classement.append(
                {
                    "id_parcelle": id_parcelle,
                    "source": classement["source"],
                    "label": classement["label"],
                    "acoustic_category": classement["acoustic_category"],
                    "min_distance": classement["min_distance"],
                    "max_distance": classement["max_distance"],
                    "percent_impacted": classement["percent_impacted"],
                }
            )

        for periode, cle in [("LD", "land_intersections_ld"), ("LN", "land_intersections_ln")]:
            for carte in d[cle]:
                lignes_cartes_bruit.append(
                    {
                        "id_parcelle": id_parcelle,
                        "periode": periode,
                        "acoustic_producer_kind": carte["acoustic_producer_kind"],
                        "acoustic_db_value": carte["acoustic_db_value"],
                        "percent_impacted": carte["percent_impacted"],
                        "direction": carte["direction"],
                    }
                )

    return pd.DataFrame(lignes_sonoscores), pd.DataFrame(lignes_classement), pd.DataFrame(lignes_cartes_bruit)


def interroger_parcelles(
    parcelles_pnb: gpd.GeoDataFrame,
    chemin_sonoscores: str,
    chemin_classement: str,
    chemin_cartes_bruit: str,
) -> dict:
    """Interroge diagBruit pour les parcelles pas encore traitées, par blocs, et met à jour les 3 registres.

    Retourne un petit rapport d'exécution (nb traitées, nb ignorées car déjà faites, erreurs par bloc).
    """
    a_traiter = parcelles_a_traiter(parcelles_pnb, chemin_sonoscores)
    rapport = {"nb_deja_traitees": len(parcelles_pnb) - len(a_traiter), "nb_a_traiter": len(a_traiter), "nb_traitees": 0, "erreurs": []}

    if a_traiter.empty:
        return rapport

    nouvelles_sonoscores, nouvelles_classement, nouvelles_cartes_bruit = [], [], []

    for debut in range(0, len(a_traiter), TAILLE_BLOC):
        bloc = a_traiter.iloc[debut : debut + TAILLE_BLOC]
        try:
            items = construire_items(bloc)
            diagnostics = appeler_diag_generate(items)
            sonoscores, classement, cartes_bruit = diagnostics_vers_tables(diagnostics, bloc["id_parcelle"].tolist())
            nouvelles_sonoscores.append(sonoscores)
            nouvelles_classement.append(classement)
            nouvelles_cartes_bruit.append(cartes_bruit)
            rapport["nb_traitees"] += len(bloc)
        except requests.RequestException as erreur:
            rapport["erreurs"].append({"ids_parcelles": bloc["id_parcelle"].tolist(), "erreur": str(erreur)})

        time.sleep(DELAI_ENTRE_APPELS_S)

    _ajouter_au_registre(chemin_sonoscores, nouvelles_sonoscores)
    _ajouter_au_registre(chemin_classement, nouvelles_classement)
    _ajouter_au_registre(chemin_cartes_bruit, nouvelles_cartes_bruit)

    return rapport


def _ajouter_au_registre(chemin: str, nouvelles_tables: list[pd.DataFrame]) -> None:
    """Ajoute les nouvelles lignes à un registre CSV existant (ou le crée s'il n'existe pas encore)."""
    if not nouvelles_tables:
        return
    nouvelles = pd.concat(nouvelles_tables, ignore_index=True)
    if os.path.exists(chemin):
        existantes = pd.read_csv(chemin)
        nouvelles = pd.concat([existantes, nouvelles], ignore_index=True)
    nouvelles.to_csv(chemin, index=False)
