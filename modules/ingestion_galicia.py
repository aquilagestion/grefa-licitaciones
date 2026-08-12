"""Conector nativo Galicia (Contratos Públicos de Galicia · RSS)."""

from __future__ import annotations

import logging
import re
import time
from typing import Any

import feedparser
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from modules.ccaa_common import map_estado, texto, to_float_eu
from modules.ingestion import USER_AGENT, build_dataframe, empty_dataframe

try:
    from config.ccaa_sources import FUENTE_GALICIA
except ImportError:  # redeploy parcial en Streamlit Cloud
    FUENTE_GALICIA = "galicia"

LOGGER = logging.getLogger(__name__)

#: Feeds oficiales + host sin www (algunas redes resuelven distinto).
FEED_PUBLICACIONES = (
    "https://www.contratosdegalicia.gal/rss/ultimas-publicacions.rss",
    "https://contratosdegalicia.gal/rss/ultimas-publicacions.rss",
    # Abertos Xunta (suele redirigir al mismo RSS; útil si el DNS www falla).
    "https://abertos.xunta.gal/catalogo/administracion-publica/-/dataset/"
    "0252/actualidade-plataforma-contratos-publicos/001/descarga-directa-ficheiro.rss",
)
FEED_PLAZOS = (
    "https://www.contratosdegalicia.gal/rss/ultimos-dias.rss",
    "https://contratosdegalicia.gal/rss/ultimos-dias.rss",
    "https://abertos.xunta.gal/catalogo/administracion-publica/-/dataset/"
    "0288/ultimos-dias-presentacion-ofertas-plataforma/101/acceso-aos-datos.rss",
)
# (connect, read): connect corto evita colgar el Buscador en Cloud.
REQUEST_TIMEOUT = (8, 25)
MAX_ATTEMPTS = 2

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
            "Connection": "close",
        }
    )
    retry = Retry(
        total=1,
        connect=1,
        read=0,
        backoff_factor=0.4,
        status_forcelist=(502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
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


def _resumen_error(exc: BaseException) -> str:
    nombre = type(exc).__name__
    msg = str(exc)
    if "ConnectTimeout" in nombre or "ConnectTimeout" in msg:
        return "timeout de conexión"
    if "ReadTimeout" in nombre or "ReadTimeout" in msg:
        return "timeout de lectura"
    if "NameResolution" in msg or "getaddrinfo" in msg:
        return "DNS no resuelve el host"
    if len(msg) > 120:
        msg = msg[:117] + "…"
    return f"{nombre}: {msg}"


def _fetch_feed(urls: tuple[str, ...], sesion: requests.Session) -> list[Any]:
    """Prueba varias URLs/reintentos; devuelve entradas o lanza el último error."""
    ultimo: Exception | None = None
    for url in urls:
        for intento in range(1, MAX_ATTEMPTS + 1):
            try:
                resp = sesion.get(url, timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()
                if "html" in (resp.headers.get("content-type") or "").lower():
                    raise GaliciaIngestionError("respuesta HTML en lugar de RSS")
                if not resp.encoding or resp.encoding.lower() in {
                    "iso-8859-1",
                    "latin-1",
                }:
                    resp.encoding = "iso-8859-1"
                feed = feedparser.parse(resp.text)
                return list(feed.entries or [])
            except Exception as exc:
                ultimo = exc
                LOGGER.warning(
                    "RSS Galicia %s intento %s/%s: %s",
                    url,
                    intento,
                    MAX_ATTEMPTS,
                    _resumen_error(exc),
                )
                if intento < MAX_ATTEMPTS:
                    time.sleep(0.35 * intento)
    if ultimo is not None:
        raise ultimo
    return []


def fetch_galicia_notices(
    *,
    incluir_plazos: bool = True,
    sesion: requests.Session | None = None,
) -> pd.DataFrame:
    """Descarga RSS oficiales de Contratos de Galicia (publicaciones ± plazos).

    Si el portal no es alcanzable (frecuente desde Streamlit Cloud), lanza un
    aviso corto; el Buscador sigue cubriendo Galicia vía PLACSP 1044.
    """
    cliente = sesion or _session()
    feeds: list[tuple[str, ...]] = [FEED_PUBLICACIONES]
    if incluir_plazos:
        feeds.append(FEED_PLAZOS)

    entradas: list[Any] = []
    errores: list[str] = []
    for urls in feeds:
        try:
            entradas.extend(_fetch_feed(urls, cliente))
        except Exception as exc:
            errores.append(_resumen_error(exc))

    if not entradas and errores:
        detalle = next(iter(dict.fromkeys(errores)))
        raise GaliciaIngestionError(
            f"portal no alcanzable ({detalle}). Cobertura Galicia vía PLACSP."
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
