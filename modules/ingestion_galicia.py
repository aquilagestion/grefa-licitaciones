"""Conector nativo Galicia (Contratos Públicos de Galicia · RSS)."""

from __future__ import annotations

import logging
import re
from typing import Any

import feedparser
import pandas as pd
import requests

from modules.ccaa_common import map_estado, texto, to_float_eu
from modules.ingestion import USER_AGENT, build_dataframe, empty_dataframe

try:
    from config.ccaa_sources import FUENTE_GALICIA
except ImportError:  # redeploy parcial en Streamlit Cloud
    FUENTE_GALICIA = "galicia"

LOGGER = logging.getLogger(__name__)

FEED_PUBLICACIONES = (
    "https://www.contratosdegalicia.gal/rss/ultimas-publicacions.rss"
)
FEED_PLAZOS = "https://www.contratosdegalicia.gal/rss/ultimos-dias.rss"
REQUEST_TIMEOUT = 45

_STATUS_MAP = {
    "en curso": "Publicada",
    "publicado": "Publicada",
    "publicada": "Publicada",
    "adjudicado": "Adjudicada",
    "adjudicada": "Adjudicada",
    "adjudicacion": "Adjudicada",
    "resolto": "Resuelta",
    "resuelto": "Resuelta",
    "anulado": "Anulada",
    "deserto": "Desierta",
    "desierta": "Desierta",
}


class GaliciaIngestionError(RuntimeError):
    pass


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
        }
    )
    return s


def _campo_html(summary: str, etiqueta: str) -> str:
    """Extrae el valor tras ``<b>Etiqueta:</b>`` en el summary HTML del RSS."""
    if not summary:
        return ""
    pat = re.compile(
        rf"<b>\s*{re.escape(etiqueta)}\s*:?\s*</b>\s*([^<]*)",
        flags=re.I,
    )
    m = pat.search(summary)
    return texto(m.group(1)) if m else ""


def _parse_titulo(title: str) -> tuple[str, str]:
    bruto = texto(title)
    m = re.search(r"\s*-\s*ID:\s*(\d+)\s*$", bruto, flags=re.I)
    if not m:
        return bruto, ""
    expediente = m.group(1)
    titulo = texto(bruto[: m.start()])
    return titulo or bruto, expediente


def _fila(entry: Any) -> dict[str, Any]:
    titulo, expediente = _parse_titulo(entry.get("title"))
    link = texto(entry.get("link"))
    if not expediente and "N=" in link:
        m = re.search(r"[?&]N=(\d+)", link)
        if m:
            expediente = m.group(1)
    summary = entry.get("summary") or entry.get("description") or ""
    if isinstance(summary, bytes):
        summary = summary.decode("latin-1", errors="replace")
    summary_txt = texto(re.sub(r"<[^>]+>", " ", str(summary)))

    organo = (
        _campo_html(str(summary), "Órgano de contratación")
        or _campo_html(str(summary), "Orgao de contratacion")
        or _campo_html(str(summary), "Órgano de contratacion")
    )
    estado_bruto = _campo_html(str(summary), "Estado")
    importe = to_float_eu(
        _campo_html(str(summary), "Importe")
        or _campo_html(str(summary), "Presupuesto")
        or _campo_html(str(summary), "Importe de licitación")
    )
    tipo = (
        _campo_html(str(summary), "Sistema de contratación")
        or _campo_html(str(summary), "Tipo de contrato")
    )
    plazo = (
        _campo_html(str(summary), "Prazo de presentación")
        or _campo_html(str(summary), "Plazo de presentación")
        or _campo_html(str(summary), "Data límite")
    )

    return {
        "expediente": expediente or texto(entry.get("id")) or link,
        "titulo": titulo,
        "organo_contratacion": organo,
        "presupuesto_sin_iva": importe,
        "presupuesto_con_iva": None,
        "url": link.replace("gal//", "gal/"),
        "fecha_actualizacion": texto(
            entry.get("published") or entry.get("updated")
        ),
        "ubicacion": "Galicia",
        "cpvs": [],
        "cpvs_texto": "",
        "estado": map_estado(estado_bruto, _STATUS_MAP) or estado_bruto,
        "tipo_contrato": tipo,
        "fecha_limite": plazo,
        "descripcion": summary_txt or titulo,
        "nif_organo": "",
        "nif_adjudicatario": "",
        "adjudicatario": "",
        "documentos": [],
        "fuente": FUENTE_GALICIA,
        "comunidad_autonoma": "Galicia",
    }


def _fetch_feed(url: str, sesion: requests.Session) -> list[Any]:
    resp = sesion.get(url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    # RSS Galicia declara ISO-8859-1.
    if not resp.encoding or resp.encoding.lower() in {"iso-8859-1", "latin-1"}:
        resp.encoding = "iso-8859-1"
    feed = feedparser.parse(resp.text)
    return list(feed.entries or [])


def fetch_galicia_notices(
    *,
    incluir_plazos: bool = True,
    sesion: requests.Session | None = None,
) -> pd.DataFrame:
    """Descarga RSS oficiales de Contratos de Galicia (publicaciones ± plazos)."""
    cliente = sesion or _session()
    urls = [FEED_PUBLICACIONES]
    if incluir_plazos:
        urls.append(FEED_PLAZOS)

    entradas: list[Any] = []
    errores: list[str] = []
    for url in urls:
        try:
            entradas.extend(_fetch_feed(url, cliente))
        except Exception as exc:
            LOGGER.warning("RSS Galicia %s falló: %s", url, exc)
            errores.append(f"{url}: {exc}")

    if not entradas and errores:
        raise GaliciaIngestionError(
            "RSS Galicia falló: " + "; ".join(errores)
        )
    if not entradas:
        return empty_dataframe()

    registros = [_fila(e) for e in entradas]
    df = build_dataframe(registros, fuente_default=FUENTE_GALICIA)
    df["fuente"] = FUENTE_GALICIA
    df["comunidad_autonoma"] = "Galicia"
    if "expediente" in df.columns:
        subset = ["expediente", "url"] if "url" in df.columns else ["expediente"]
        df = df.drop_duplicates(subset=subset, keep="first")
    df.attrs["origen"] = "galicia"
    return df.reset_index(drop=True)
