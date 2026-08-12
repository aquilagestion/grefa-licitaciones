"""Conector nativo Cataluña (PSCP / Transparència Catalunya · Socrata)."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import requests

from modules.ccaa_common import cpvs_desde_texto, map_estado, texto, to_float_eu
from modules.ingestion import USER_AGENT, build_dataframe, empty_dataframe

try:
    from config.ccaa_sources import FUENTE_CATALUNYA
except ImportError:  # redeploy parcial en Streamlit Cloud
    FUENTE_CATALUNYA = "catalunya"

LOGGER = logging.getLogger(__name__)

DATASET_URL = "https://analisi.transparenciacatalunya.cat/resource/ybgg-dgi6.json"
REQUEST_TIMEOUT = 45
DEFAULT_LIMIT = 200

_STATUS_MAP = {
    "licitacio": "Publicada",
    "anunci": "Publicada",
    "presentacio": "Publicada",
    "adjudicacio": "Adjudicada",
    "formalitzacio": "Resuelta",
    "anul": "Anulada",
    "deserta": "Desierta",
    "agregada": "Adjudicada",
}


class CatalunyaIngestionError(RuntimeError):
    pass


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    return s


def _fila(item: dict[str, Any]) -> dict[str, Any]:
    cpvs, cpvs_texto = cpvs_desde_texto(item.get("codi_cpv"))
    enlace = item.get("enllac_publicacio")
    url = texto(enlace)
    organo = texto(item.get("nom_organ")) or texto(item.get("nom_departament_ens"))
    return {
        "expediente": texto(item.get("codi_expedient")),
        "titulo": texto(item.get("denominacio") or item.get("objecte_contracte")),
        "organo_contratacion": organo,
        "presupuesto_sin_iva": to_float_eu(
            item.get("pressupost_licitacio_sense") or item.get("valor_estimat_contracte")
        ),
        "presupuesto_con_iva": to_float_eu(item.get("pressupost_licitacio_amb")),
        "url": url,
        "fecha_actualizacion": texto(
            item.get("data_publicacio_contracte")
            or item.get("data_publicacio_anunci")
            or item.get("data_adjudicacio_contracte")
        ),
        "ubicacion": texto(item.get("lloc_execucio")) or texto(item.get("codi_nuts")),
        "cpvs": cpvs,
        "cpvs_texto": cpvs_texto,
        "estado": map_estado(texto(item.get("fase_publicacio")), _STATUS_MAP),
        "tipo_contrato": texto(item.get("tipus_contracte")),
        "fecha_limite": texto(item.get("termini_presentacio_ofertes")),
        "descripcion": texto(item.get("objecte_contracte") or item.get("denominacio")),
        "nif_organo": texto(item.get("codi_dir3")),
        "nif_adjudicatario": texto(item.get("identificacio_adjudicatari")),
        "adjudicatario": texto(item.get("denominacio_adjudicatari")),
        "documentos": [],
        "fuente": FUENTE_CATALUNYA,
        "comunidad_autonoma": "Cataluña",
    }


def fetch_catalunya_notices(
    *,
    limit: int = DEFAULT_LIMIT,
    sesion: requests.Session | None = None,
) -> pd.DataFrame:
    """Descarga publicaciones recientes de la PSCP vía Socrata."""
    limit = max(1, min(1000, int(limit)))
    cliente = sesion or _session()
    try:
        resp = cliente.get(
            DATASET_URL,
            params={
                "$limit": limit,
                "$order": "data_publicacio_contracte DESC",
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        items = resp.json()
    except Exception as exc:
        raise CatalunyaIngestionError(f"Socrata Cataluña falló: {exc}") from exc

    if not isinstance(items, list) or not items:
        return empty_dataframe()

    registros = [_fila(x) for x in items if isinstance(x, dict)]
    df = build_dataframe(registros, fuente_default=FUENTE_CATALUNYA)
    df["fuente"] = FUENTE_CATALUNYA
    df["comunidad_autonoma"] = "Cataluña"
    df.attrs["origen"] = "catalunya"
    return df
