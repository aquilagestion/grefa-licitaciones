"""Conector nativo Andalucía (open data · contratos menores Junta)."""

from __future__ import annotations

import csv
import io
import logging
import re
from collections import deque
from typing import Any

import pandas as pd
import requests

from modules.ccaa_common import cpvs_desde_texto, pick_field, texto, to_float_eu
from modules.ingestion import USER_AGENT, build_dataframe, empty_dataframe

try:
    from config.ccaa_sources import FUENTE_ANDALUCIA
except ImportError:  # redeploy parcial en Streamlit Cloud
    FUENTE_ANDALUCIA = "andalucia"

LOGGER = logging.getLogger(__name__)

DATASET_PAGE = (
    "https://www.juntadeandalucia.es/datosabiertos/portal/dataset/"
    "contratacion-menor-plataforma-de-contratacion-andalucia-2025"
)
# Fallback conocido (nombre de fichero cambia trimestralmente; se redescubre).
CSV_FALLBACK = (
    "https://www.juntadeandalucia.es/datosabiertos/portal/dataset/"
    "00510697-b39d-4e19-b142-14565baafabd/resource/"
    "5a95ae9f-8842-4944-bcf9-2db6b08f5394/download/menores_2025_v1_20260618.csv"
)
REQUEST_TIMEOUT = 120
DEFAULT_LIMIT = 300
PORTAL = "https://www.juntadeandalucia.es"


class AndaluciaIngestionError(RuntimeError):
    pass


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/csv,application/json,*/*",
        }
    )
    return s


def _abs_url(href: str) -> str:
    href = texto(href)
    if not href:
        return ""
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return PORTAL + href
    return href


def descubrir_csv_url(sesion: requests.Session) -> str:
    """Localiza el enlace CSV del dataset de menores 2025."""
    try:
        resp = sesion.get(DATASET_PAGE, timeout=45)
        resp.raise_for_status()
    except Exception as exc:
        LOGGER.warning("Dataset Andalucía no accesible: %s", exc)
        return CSV_FALLBACK

    links = re.findall(r'href="([^"]+)"', resp.text)
    candidatos: list[str] = []
    for href in links:
        low = href.lower()
        if "/download/" in low and low.endswith(".csv"):
            candidatos.append(_abs_url(href))
        elif low.endswith(".csv") and "menor" in low:
            candidatos.append(_abs_url(href))
    if candidatos:
        # Preferir el de resource/…/download/
        for c in candidatos:
            if "/resource/" in c and "/download/" in c:
                return c
        return candidatos[0]
    return CSV_FALLBACK


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
        url = (
            "https://www.juntadeandalucia.es/temas/contratacion-publica.html"
        )

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
        piece = chunk.decode("utf-8-sig" if not buf and not header_line else "utf-8", errors="replace")
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


def fetch_andalucia_notices(
    *,
    limit: int = DEFAULT_LIMIT,
    sesion: requests.Session | None = None,
) -> pd.DataFrame:
    """Descarga contratos menores publicados (open data Junta de Andalucía).

    Nota: son adjudicaciones menores ya publicadas (no pliegos abiertos). Complementa
    PLACSP 1044 cuando el portal de datos responde.
    """
    limit = max(1, min(5000, int(limit)))
    cliente = sesion or _session()
    csv_url = descubrir_csv_url(cliente)
    ultimo_error: Exception | None = None
    filas: list[dict[str, str]] | None = None
    for url in dict.fromkeys([csv_url, CSV_FALLBACK]):
        try:
            with cliente.get(url, timeout=REQUEST_TIMEOUT, stream=True) as resp:
                if resp.status_code >= 400:
                    raise AndaluciaIngestionError(
                        f"HTTP {resp.status_code} al descargar menores Andalucía"
                    )
                filas = _leer_csv_recientes(resp, limit=limit)
            csv_url = url
            break
        except Exception as exc:
            ultimo_error = exc
            LOGGER.warning("Descarga Andalucía %s falló: %s", url, exc)
            filas = None

    if filas is None:
        raise AndaluciaIngestionError(
            f"Open data Andalucía no disponible: {ultimo_error}"
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
