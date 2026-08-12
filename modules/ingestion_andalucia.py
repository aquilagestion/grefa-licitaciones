"""Conector nativo Andalucía (open data · contratos menores Junta)."""

from __future__ import annotations

import csv
import io
import logging
import re
import time
from collections import deque
from typing import Any

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from modules.ccaa_common import cpvs_desde_texto, pick_field, texto, to_float_eu
from modules.ingestion import USER_AGENT, build_dataframe, empty_dataframe

try:
    from config.ccaa_sources import FUENTE_ANDALUCIA
except ImportError:  # redeploy parcial en Streamlit Cloud
    FUENTE_ANDALUCIA = "andalucia"

LOGGER = logging.getLogger(__name__)

PORTAL = "https://www.juntadeandalucia.es"
CKAN_API = f"{PORTAL}/datosabiertos/portal/api/3/action/package_show"
DATASET_SLUGS = (
    "contratacion-menor-plataforma-de-contratacion-andalucia-2026",
    "contratacion-menor-plataforma-de-contratacion-andalucia-2025",
)
DATASET_PAGES = tuple(
    f"{PORTAL}/datosabiertos/portal/dataset/{slug}" for slug in DATASET_SLUGS
)
# Fallback conocido (nombre de fichero cambia; se redescubre).
CSV_FALLBACKS = (
    (
        f"{PORTAL}/datosabiertos/portal/dataset/"
        "9fd6091c-535a-4762-b4f0-938c61ec0e95/resource/"
        "2a2dc763-53b0-4918-87ec-ec218a910de5/download/"
        "menores_202602_v1_20260720.csv"
    ),
    (
        f"{PORTAL}/datosabiertos/portal/dataset/"
        "00510697-b39d-4e19-b142-14565baafabd/resource/"
        "5a95ae9f-8842-4944-bcf9-2db6b08f5394/download/"
        "menores_2025_v1_20260618.csv"
    ),
)
REQUEST_TIMEOUT = (10, 90)
MAX_ATTEMPTS = 3
DEFAULT_LIMIT = 300
_PAAS_HOST = "gdc-pdpopendata-ckan.paas.junta-andalucia.es"


class AndaluciaIngestionError(RuntimeError):
    pass


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/csv,application/json,*/*",
            "Connection": "close",
        }
    )
    retry = Retry(
        total=1,
        connect=1,
        read=0,
        backoff_factor=0.5,
        status_forcelist=(502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


def _abs_url(href: str) -> str:
    href = texto(href)
    if not href:
        return ""
    if href.startswith("http"):
        # La API CKAN a veces devuelve el host interno PaaS (no resuelve fuera).
        return href.replace(f"https://{_PAAS_HOST}", PORTAL).replace(
            f"http://{_PAAS_HOST}", PORTAL
        )
    if href.startswith("/"):
        return PORTAL + href
    return href


def _resumen_error(exc: Exception) -> str:
    msg = str(exc or "").strip()
    low = msg.lower()
    if "503" in low:
        return "HTTP 503 (portal open data temporalmente caído)"
    if "502" in low or "504" in low:
        return f"HTTP {msg}"
    if "timeout" in low or "timed out" in low:
        return "timeout"
    if "html" in low:
        return "respuesta HTML en lugar de CSV"
    return msg[:120] or exc.__class__.__name__


def _urls_desde_html(html: str) -> list[str]:
    links = re.findall(r'href="([^"]+)"', html or "")
    candidatos: list[str] = []
    for href in links:
        low = href.lower()
        if "/download/" in low and (low.endswith(".csv") or low.endswith(".json")):
            candidatos.append(_abs_url(href))
        elif low.endswith(".csv") and "menor" in low:
            candidatos.append(_abs_url(href))
    return candidatos


def _urls_desde_ckan(sesion: requests.Session, slug: str) -> list[str]:
    try:
        resp = sesion.get(CKAN_API, params={"id": slug}, timeout=REQUEST_TIMEOUT)
        if resp.status_code >= 400:
            return []
        data = resp.json()
        resources = (data.get("result") or {}).get("resources") or []
    except Exception as exc:
        LOGGER.warning("CKAN Andalucía %s: %s", slug, exc)
        return []
    out: list[str] = []
    for res in resources:
        if not isinstance(res, dict):
            continue
        fmt = str(res.get("format") or "").upper()
        url = _abs_url(str(res.get("url") or ""))
        if not url:
            continue
        if fmt == "CSV" or url.lower().endswith(".csv"):
            out.append(url)
        elif fmt == "JSON" or url.lower().endswith(".json"):
            out.append(url)
    return out


def descubrir_csv_urls(sesion: requests.Session) -> list[str]:
    """Localiza URLs CSV/JSON de menores (prioriza 2026, luego 2025)."""
    halladas: list[str] = []
    for slug, page in zip(DATASET_SLUGS, DATASET_PAGES):
        halladas.extend(_urls_desde_ckan(sesion, slug))
        try:
            resp = sesion.get(page, timeout=REQUEST_TIMEOUT)
            if resp.status_code < 400:
                halladas.extend(_urls_desde_html(resp.text))
        except Exception as exc:
            LOGGER.warning("Dataset Andalucía %s no accesible: %s", slug, exc)
    # CSV primero, luego JSON, luego fallbacks conocidos.
    csvs = [u for u in halladas if u.lower().endswith(".csv")]
    jsons = [u for u in halladas if u.lower().endswith(".json")]
    ordenados = list(dict.fromkeys([*csvs, *jsons, *CSV_FALLBACKS]))
    return ordenados


def _fila(row: dict[str, str]) -> dict[str, Any]:
    titulo = pick_field(
        row,
        "Objeto",
        "Objeto del contrato",
        "OBJETO",
        "Descripcion",
        "Descripción",
        "Titulo",
        "Título",
    )
    expediente = pick_field(
        row,
        "Expediente",
        "Numero expediente",
        "Número expediente",
        "N Expediente",
        "Codigo",
        "Código",
        "ID",
    )
    organo = pick_field(
        row,
        "Organo de contratacion",
        "Órgano de contratación",
        "Organo contratacion",
        "Entidad adjudicadora",
        "Poder adjudicador",
        "Organismo",
    )
    url = pick_field(row, "URL", "Enlace", "Link", "Permalink", "Url anuncio")
    cpv_bruto = pick_field(row, "CPV", "Codigo CPV", "Código CPV", "CPVs")
    cpvs, cpvs_texto = cpvs_desde_texto(cpv_bruto)
    importe = to_float_eu(
        pick_field(
            row,
            "Importe adjudicacion",
            "Importe adjudicación",
            "Importe",
            "Presupuesto",
            "Importe sin IVA",
            "Precio",
            "Adjudicacion",
        )
    )
    fecha = pick_field(
        row,
        "Fecha adjudicacion",
        "Fecha adjudicación",
        "Fecha publicacion",
        "Fecha publicación",
        "Fecha",
    )
    adjudicatario = pick_field(
        row, "Adjudicatario", "Adjudicatario nombre", "Razon social", "Razón social"
    )
    nif_adj = pick_field(row, "NIF adjudicatario", "CIF adjudicatario", "NIF", "CIF")
    tipo = pick_field(row, "Tipo contrato", "Tipo de contrato", "Tipo")
    ubicacion = pick_field(row, "Provincia", "Municipio", "Lugar ejecucion", "NUTS") or "Andalucía"

    if not expediente:
        expediente = f"and-{texto(fecha)}-{titulo[:40]}".strip("-") or "andalucia-sin-id"
    if not url:
        url = "https://www.juntadeandalucia.es/temas/contratacion-publica.html"

    return {
        "expediente": expediente,
        "titulo": titulo or "(Sin título)",
        "organo_contratacion": organo,
        "presupuesto_sin_iva": importe,
        "presupuesto_con_iva": None,
        "url": url,
        "fecha_actualizacion": fecha,
        "ubicacion": ubicacion,
        "cpvs": cpvs,
        "cpvs_texto": cpvs_texto,
        "estado": "Adjudicada",
        "tipo_contrato": tipo or "Contrato menor",
        "fecha_limite": "",
        "descripcion": titulo,
        "nif_organo": "",
        "nif_adjudicatario": nif_adj,
        "adjudicatario": adjudicatario,
        "documentos": [],
        "fuente": FUENTE_ANDALUCIA,
        "comunidad_autonoma": "Andalucía",
    }


def _leer_csv_recientes(
    resp: requests.Response, *, limit: int
) -> list[dict[str, str]]:
    """Lee el CSV en streaming y se queda con las últimas ``limit`` filas."""
    buf = ""
    cola: deque[str] = deque(maxlen=max(1, limit))
    header_line: str | None = None
    html_check = ""

    for chunk in resp.iter_content(1024 * 256):
        if not chunk:
            continue
        piece = chunk.decode(
            "utf-8-sig" if not buf and not header_line else "utf-8", errors="replace"
        )
        if len(html_check) < 64:
            html_check += piece
            cabeza = html_check.lstrip()[:64].lower()
            if cabeza.startswith("<!doctype") or cabeza.startswith("<html"):
                raise AndaluciaIngestionError(
                    "El portal de datos abiertos de Andalucía devolvió HTML en lugar de CSV "
                    "(posible 503 temporal)."
                )
        buf += piece
        while True:
            if "\n" in buf:
                linea, buf = buf.split("\n", 1)
            elif "\r" in buf:
                linea, buf = buf.split("\r", 1)
            else:
                break
            linea = linea.rstrip("\r")
            if header_line is None:
                if linea.strip():
                    header_line = linea
                continue
            if linea.strip():
                cola.append(linea)

    if buf.strip():
        if header_line is None:
            header_line = buf.strip()
        else:
            cola.append(buf.rstrip("\r"))

    if not header_line:
        raise AndaluciaIngestionError("CSV Andalucía vacío.")

    texto_csv = header_line + "\n" + "\n".join(cola)
    reader = csv.DictReader(io.StringIO(texto_csv))
    if not reader.fieldnames:
        raise AndaluciaIngestionError("CSV Andalucía sin cabeceras.")
    filas = [
        {str(k): ("" if v is None else str(v)) for k, v in row.items()}
        for row in reader
        if isinstance(row, dict)
    ]
    filas.reverse()
    return filas


def _leer_json_recientes(payload: Any, *, limit: int) -> list[dict[str, str]]:
    data = payload
    if isinstance(data, dict):
        for key in ("records", "data", "result", "items"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    if not isinstance(data, list):
        raise AndaluciaIngestionError("JSON Andalucía con formato inesperado.")
    filas: list[dict[str, str]] = []
    for row in data[-max(1, limit) :]:
        if not isinstance(row, dict):
            continue
        filas.append({str(k): ("" if v is None else str(v)) for k, v in row.items()})
    filas.reverse()
    return filas


def _descargar_filas(
    cliente: requests.Session, url: str, *, limit: int
) -> list[dict[str, str]]:
    ultimo: Exception | None = None
    es_json = url.lower().endswith(".json")
    for intento in range(1, MAX_ATTEMPTS + 1):
        try:
            if es_json:
                resp = cliente.get(url, timeout=REQUEST_TIMEOUT)
                if resp.status_code >= 400:
                    raise AndaluciaIngestionError(
                        f"HTTP {resp.status_code} al descargar menores Andalucía"
                    )
                cabeza = (resp.text or "").lstrip()[:64].lower()
                if cabeza.startswith("<!doctype") or cabeza.startswith("<html"):
                    raise AndaluciaIngestionError(
                        "El portal devolvió HTML en lugar de JSON (posible 503)."
                    )
                return _leer_json_recientes(resp.json(), limit=limit)
            with cliente.get(url, timeout=REQUEST_TIMEOUT, stream=True) as resp:
                if resp.status_code >= 400:
                    raise AndaluciaIngestionError(
                        f"HTTP {resp.status_code} al descargar menores Andalucía"
                    )
                return _leer_csv_recientes(resp, limit=limit)
        except Exception as exc:
            ultimo = exc
            LOGGER.warning(
                "Descarga Andalucía %s intento %s/%s: %s",
                url,
                intento,
                MAX_ATTEMPTS,
                _resumen_error(exc),
            )
            if intento < MAX_ATTEMPTS:
                time.sleep(0.6 * intento)
    assert ultimo is not None
    raise ultimo


def fetch_andalucia_notices(
    *,
    limit: int = DEFAULT_LIMIT,
    sesion: requests.Session | None = None,
) -> pd.DataFrame:
    """Descarga contratos menores publicados (open data Junta de Andalucía).

    Nota: son adjudicaciones menores ya publicadas (no pliegos abiertos). Complementa
    PLACSP 1044 cuando el portal de datos responde. Si el CSV está en 503 (frecuente),
    el Buscador sigue cubriendo licitaciones abiertas de Andalucía vía PLACSP.
    """
    limit = max(1, min(5000, int(limit)))
    cliente = sesion or _session()
    urls = descubrir_csv_urls(cliente)
    ultimo_error: Exception | None = None
    filas: list[dict[str, str]] | None = None
    csv_url = ""
    for url in urls:
        try:
            filas = _descargar_filas(cliente, url, limit=limit)
            csv_url = url
            break
        except Exception as exc:
            ultimo_error = exc
            LOGGER.warning("Descarga Andalucía %s falló: %s", url, _resumen_error(exc))
            filas = None

    if filas is None:
        detalle = _resumen_error(ultimo_error or AndaluciaIngestionError("sin respuesta"))
        raise AndaluciaIngestionError(
            f"open data menores no disponible ({detalle}). "
            "Licitaciones abiertas Andalucía siguen vía PLACSP."
        )
    if not filas:
        return empty_dataframe()

    registros = [_fila(f) for f in filas]
    df = build_dataframe(registros, fuente_default=FUENTE_ANDALUCIA)
    df["fuente"] = FUENTE_ANDALUCIA
    df["comunidad_autonoma"] = "Andalucía"
    df.attrs["origen"] = "andalucia"
    df.attrs["csv_url"] = csv_url
    return df
