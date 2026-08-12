"""Conector nativo Comunidad de Madrid (ATOM contratos-publicos)."""

from __future__ import annotations

import logging
from typing import Any

import feedparser
import pandas as pd
import requests

from config.ccaa_sources import FUENTE_MADRID
from modules.ccaa_common import cpvs_desde_texto, map_estado, texto, to_float_eu
from modules.ingestion import USER_AGENT, build_dataframe, empty_dataframe

LOGGER = logging.getLogger(__name__)

FEED_URL = "https://contratos-publicos.comunidad.madrid/feed/licitaciones2"
REQUEST_TIMEOUT = 60

_STATUS_MAP = {
    "pub": "Publicada",
    "ev": "En evaluación",
    "adj": "Adjudicada",
    "res": "Resuelta",
    "anul": "Anulada",
    "pre": "Anuncio previo",
}


class MadridIngestionError(RuntimeError):
    pass


def _entry_get(entry: Any, *keys: str) -> str:
    for key in keys:
        valor = entry.get(key)
        if valor:
            return texto(valor)
    return ""


def _fila(entry: Any) -> dict[str, Any]:
    cpv_bruto = _entry_get(entry, "cbc_itemclassificationcode")
    cpvs, cpvs_texto = cpvs_desde_texto(cpv_bruto)
    estado_code = _entry_get(entry, "cbc-place-ext_contractfolderstatuscode")
    resumen = texto(entry.get("summary"))
    # El resumen suele traer «Id licitación: …;Órgano…;Importe: …»
    expediente = _entry_get(entry, "cbc_contractfolderid", "cbc_id")
    if not expediente and "Id licitación:" in resumen:
        expediente = texto(resumen.split("Id licitación:", 1)[1].split(";", 1)[0])

    organo = _entry_get(entry, "cbc_name")
    if not organo and "Órgano de Contratación:" in resumen:
        organo = texto(resumen.split("Órgano de Contratación:", 1)[1].split(";", 1)[0])

    importe = to_float_eu(_entry_get(entry, "cbc_taxexclusiveamount"))
    if importe is None and "Importe:" in resumen:
        importe = to_float_eu(resumen.split("Importe:", 1)[1].split(";", 1)[0])

    return {
        "expediente": expediente,
        "titulo": texto(entry.get("title")),
        "organo_contratacion": organo,
        "presupuesto_sin_iva": importe,
        "presupuesto_con_iva": to_float_eu(
            _entry_get(entry, "cbc_estimatedoverallcontractamount")
        ),
        "url": texto(entry.get("link")),
        "fecha_actualizacion": _entry_get(entry, "updated", "cbc_issuedate"),
        "ubicacion": _entry_get(entry, "cbc_countrysubentitycode") or "Madrid",
        "cpvs": cpvs,
        "cpvs_texto": cpvs_texto,
        "estado": map_estado(estado_code, _STATUS_MAP) or estado_code,
        "tipo_contrato": _entry_get(entry, "cbc_typecode"),
        "fecha_limite": _entry_get(entry, "cbc_enddate"),
        "descripcion": resumen or texto(entry.get("title")),
        "nif_organo": "",
        "nif_adjudicatario": "",
        "adjudicatario": "",
        "documentos": [],
        "fuente": FUENTE_MADRID,
        "comunidad_autonoma": "Comunidad de Madrid",
    }


def fetch_madrid_notices(*, sesion: requests.Session | None = None) -> pd.DataFrame:
    """Descarga el feed ATOM oficial de la Comunidad de Madrid."""
    cliente = sesion or requests.Session()
    cliente.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "application/atom+xml, application/xml;q=0.9, */*;q=0.8",
        }
    )
    try:
        resp = cliente.get(FEED_URL, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
    except Exception as exc:
        raise MadridIngestionError(f"ATOM Madrid falló: {exc}") from exc

    registros = [_fila(e) for e in feed.entries]
    if not registros:
        return empty_dataframe()
    df = build_dataframe(registros, fuente_default=FUENTE_MADRID)
    df["fuente"] = FUENTE_MADRID
    df["comunidad_autonoma"] = "Comunidad de Madrid"
    df.attrs["origen"] = "madrid"
    return df
