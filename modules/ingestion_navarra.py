"""Conector nativo Navarra (datosabiertos.navarra.es · CSV anuncios)."""

from __future__ import annotations

import csv
import io
import logging
from typing import Any

import pandas as pd
import requests

from config.ccaa_sources import FUENTE_NAVARRA
from modules.ccaa_common import cpvs_desde_texto, map_estado, texto, to_float_eu
from modules.ingestion import USER_AGENT, build_dataframe, empty_dataframe

LOGGER = logging.getLogger(__name__)

PACKAGE_API = "https://datosabiertos.navarra.es/api/3/action/package_show"
PACKAGE_ID = "anuncios-licitaciones"
REQUEST_TIMEOUT = 60
DEFAULT_LIMIT = 250

_STATUS_MAP = {
    "publicado": "Publicada",
    "publicada": "Publicada",
    "en plazo": "Publicada",
    "evaluacion": "En evaluación",
    "adjudicado": "Adjudicada",
    "adjudicada": "Adjudicada",
    "resuelto": "Resuelta",
    "formalizado": "Resuelta",
    "cancelado": "Cancelada",
    "anulado": "Anulada",
    "desierto": "Desierta",
}


class NavarraIngestionError(RuntimeError):
    pass


def _resolver_csv_url(sesion: requests.Session) -> str:
    resp = sesion.get(
        PACKAGE_API, params={"id": PACKAGE_ID}, timeout=REQUEST_TIMEOUT
    )
    resp.raise_for_status()
    payload = resp.json()
    if not payload.get("success"):
        raise NavarraIngestionError("CKAN package_show sin éxito.")
    resources = (payload.get("result") or {}).get("resources") or []
    for res in resources:
        fmt = str(res.get("format") or "").upper()
        url = str(res.get("url") or "")
        if fmt == "CSV" and url:
            return url
    raise NavarraIngestionError("No hay recurso CSV en anuncios-licitaciones.")


def _fila(row: dict[str, str]) -> dict[str, Any]:
    cpvs, cpvs_texto = cpvs_desde_texto(row.get("CPV"))
    organo = texto(row.get("Organo")) or texto(row.get("Entidad"))
    if texto(row.get("Entidad")) and texto(row.get("Organo")):
        if texto(row.get("Entidad")) not in organo:
            organo = f"{texto(row.get('Entidad'))} · {texto(row.get('Organo'))}"
    # El CSV no trae ID estable: sintetizamos uno legible.
    expediente = texto(row.get("Expediente") or row.get("Codigo") or "")
    if not expediente:
        base = f"{texto(row.get('FechaPublicacion'))}-{texto(row.get('BreveDescripcion'))[:40]}"
        expediente = base.strip("-") or "navarra-sin-id"

    return {
        "expediente": expediente,
        "titulo": texto(row.get("BreveDescripcion")),
        "organo_contratacion": organo,
        "presupuesto_sin_iva": to_float_eu(
            row.get("PrecioLicitacion") or row.get("ValorEstimado")
        ),
        "presupuesto_con_iva": None,
        "url": texto(row.get("URL") or row.get("Enlace") or ""),
        "fecha_actualizacion": texto(row.get("FechaPublicacion")),
        "ubicacion": texto(row.get("LugarEjecucion")) or texto(row.get("codigoNUTS")),
        "cpvs": cpvs,
        "cpvs_texto": cpvs_texto,
        "estado": map_estado(texto(row.get("Estado")), _STATUS_MAP),
        "tipo_contrato": texto(row.get("TipoContrato")),
        "fecha_limite": texto(row.get("PlazoEjecucion")),
        "descripcion": texto(row.get("BreveDescripcion")),
        "nif_organo": "",
        "nif_adjudicatario": "",
        "adjudicatario": "",
        "documentos": [],
        "fuente": FUENTE_NAVARRA,
        "comunidad_autonoma": "Comunidad Foral de Navarra",
    }


def fetch_navarra_notices(
    *,
    limit: int = DEFAULT_LIMIT,
    sesion: requests.Session | None = None,
) -> pd.DataFrame:
    """Lee el CSV diario de anuncios de Navarra (las filas más recientes)."""
    limit = max(1, min(2000, int(limit)))
    cliente = sesion or requests.Session()
    cliente.headers.update({"User-Agent": USER_AGENT, "Accept": "text/csv,*/*"})
    try:
        csv_url = _resolver_csv_url(cliente)
        resp = cliente.get(csv_url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        texto_csv = resp.content.decode("utf-8-sig", errors="replace")
    except NavarraIngestionError:
        raise
    except Exception as exc:
        raise NavarraIngestionError(f"Descarga CSV Navarra falló: {exc}") from exc

    reader = csv.DictReader(io.StringIO(texto_csv))
    filas = list(reader)
    if not filas:
        return empty_dataframe()

    # El CSV suele ir cronológico ascendente: nos quedamos con el final.
    recientes = filas[-limit:]
    recientes.reverse()
    registros = [_fila(f) for f in recientes]
    df = build_dataframe(registros, fuente_default=FUENTE_NAVARRA)
    df["fuente"] = FUENTE_NAVARRA
    df["comunidad_autonoma"] = "Comunidad Foral de Navarra"
    df.attrs["origen"] = "navarra"
    df.attrs["csv_url"] = csv_url
    return df
