"""Conector nativo País Vasco (Kontratazio / api.euskadi.eus).

Consume ``/procurements/contracting-notices`` (anuncios de licitación) y
normaliza al esquema de ``modules.ingestion.COLUMNS``.

No se consulta hasta que el Buscador pulsa Buscar.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import requests

from modules.ingestion import USER_AGENT, build_dataframe, empty_dataframe

try:
    from config.ccaa_sources import FUENTE_EUSKADI
except ImportError:  # redeploy parcial en Streamlit Cloud
    FUENTE_EUSKADI = "euskadi"

LOGGER = logging.getLogger(__name__)

BASE_URL = "https://api.euskadi.eus/procurements/contracting-notices"
REQUEST_TIMEOUT = 45
DEFAULT_PAGE_SIZE = 50
DEFAULT_MAX_PAGES = 4  # 200 anuncios recientes por defecto

#: Mapeo de estados Euskadi → etiquetas PLACSP usadas en filtros GREFA.
_STATUS_MAP: dict[str, str] = {
    "abierto / plazo de presentacion": "Publicada",
    "abierto / plazo de presentación": "Publicada",
    "plazo cerrado": "En evaluación",
    "adjudicacion": "Adjudicada",
    "adjudicación": "Adjudicada",
    "modificacion contrato": "Resuelta",
    "modificación contrato": "Resuelta",
    "desierto": "Desierta",
    "anulado": "Anulada",
    "cancelado": "Cancelada",
}


class EuskadiIngestionError(RuntimeError):
    """Fallo al hablar con la API de contratación de Euskadi."""


def _session() -> requests.Session:
    sesion = requests.Session()
    sesion.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
    )
    return sesion


def _texto(valor: Any) -> str:
    if valor is None:
        return ""
    return " ".join(str(valor).split())


def _map_estado(nombre: str) -> str:
    bruto = _texto(nombre)
    if not bruto:
        return ""
    clave = bruto.lower()
    # sin tildes para coincidir claves
    import unicodedata

    clave_n = "".join(
        c for c in unicodedata.normalize("NFKD", clave) if not unicodedata.combining(c)
    )
    for k, v in _STATUS_MAP.items():
        k_n = "".join(
            c for c in unicodedata.normalize("NFKD", k) if not unicodedata.combining(c)
        )
        if clave_n == k_n or k_n in clave_n:
            return v
    return bruto


def _notice_a_fila(item: dict[str, Any]) -> dict[str, Any]:
    autoridad = item.get("contractingAuthority") or {}
    entidad = item.get("entity") or {}
    org = (entidad.get("org") or {}) if isinstance(entidad, dict) else {}
    tipo = item.get("contractType") or {}
    estado = item.get("contractProcedureStatus") or {}

    organo = _texto(autoridad.get("name")) or _texto(entidad.get("name"))
    ubicacion = _texto(autoridad.get("scope")) or _texto(autoridad.get("codNUTS"))
    if org.get("name") and organo and _texto(org.get("name")) not in organo:
        organo = f"{organo} · {_texto(org.get('name'))}"

    url = _texto(item.get("mainEntityOfPage")) or _texto(
        ((item.get("_links") or {}).get("self") or {}).get("href")
    )

    presupuesto = item.get("budgetWithoutVAT")
    try:
        presupuesto_f = float(presupuesto) if presupuesto is not None else None
    except (TypeError, ValueError):
        presupuesto_f = None

    return {
        "expediente": _texto(item.get("code")) or str(item.get("id") or ""),
        "titulo": _texto(item.get("object")),
        "organo_contratacion": organo,
        "presupuesto_sin_iva": presupuesto_f,
        "presupuesto_con_iva": None,
        "url": url,
        "fecha_actualizacion": _texto(
            item.get("lastPublicationDate") or item.get("firstPublicationDate")
        ),
        "ubicacion": ubicacion,
        "cpvs": [],
        "cpvs_texto": "",
        "estado": _map_estado(_texto(estado.get("name"))),
        "tipo_contrato": _texto(tipo.get("name")),
        "fecha_limite": _texto(item.get("deadlineDate")),
        "descripcion": _texto(item.get("object")),
        "nif_organo": _texto(autoridad.get("identificationNumber")),
        "nif_adjudicatario": "",
        "adjudicatario": "",
        "documentos": [],
        "fuente": FUENTE_EUSKADI,
        "comunidad_autonoma": "País Vasco",
    }


def fetch_euskadi_notices(
    *,
    max_pages: int = DEFAULT_MAX_PAGES,
    page_size: int = DEFAULT_PAGE_SIZE,
    sesion: requests.Session | None = None,
) -> pd.DataFrame:
    """Descarga anuncios recientes de contratación pública de Euskadi.

    Parámetros limitan el volumen: la API tiene cientos de miles de ítems.
    """
    max_pages = max(1, int(max_pages))
    page_size = max(1, min(100, int(page_size)))
    cliente = sesion or _session()
    registros: list[dict[str, Any]] = []
    errores: list[str] = []

    for page in range(1, max_pages + 1):
        try:
            respuesta = cliente.get(
                BASE_URL,
                params={"page": page, "itemsOfPage": page_size},
                timeout=REQUEST_TIMEOUT,
            )
            respuesta.raise_for_status()
            payload = respuesta.json()
        except Exception as exc:
            errores.append(f"página {page}: {exc}")
            LOGGER.warning("Euskadi API falló en página %s: %s", page, exc)
            break

        items = payload.get("items") or []
        if not items:
            break
        for item in items:
            if isinstance(item, dict):
                registros.append(_notice_a_fila(item))

        total_pages = int(payload.get("totalPages") or 0)
        if total_pages and page >= total_pages:
            break
        if len(items) < page_size:
            break

    if not registros:
        if errores:
            raise EuskadiIngestionError(
                "No se pudieron descargar anuncios de Euskadi. " + "; ".join(errores[:2])
            )
        return empty_dataframe()

    df = build_dataframe(registros, fuente_default=FUENTE_EUSKADI)
    df["fuente"] = FUENTE_EUSKADI
    df["comunidad_autonoma"] = "País Vasco"
    df.attrs["origen"] = "euskadi"
    df.attrs["paginas"] = min(max_pages, (len(registros) + page_size - 1) // page_size)
    return df
