import os
import requests
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

URL_DOC_GRIST = os.getenv("URL_DOC_GRIST")
TABLE_ID_CONSO_GRIST = os.getenv("TABLE_ID_CONSO_GRIST")
API_KEY_USER = os.getenv("API_KEY_USER")


def get_records(table_id: str = TABLE_ID_CONSO_GRIST) -> list[dict]: # type: ignore
    """Récupère tous les enregistrements d'une table Grist."""
    url = f"{URL_DOC_GRIST}/tables/{table_id}/records"
    headers = {}
    if API_KEY_USER:
        headers["Authorization"] = f"Bearer {API_KEY_USER}"

    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json().get("records", [])


def records_to_df(records: list[dict]) -> "pd.DataFrame":
    """Aplatit une liste d'enregistrements Grist en DataFrame (id + fields)."""
    import pandas as pd
    return pd.DataFrame([{"id": r["id"], **r["fields"]} for r in records])
