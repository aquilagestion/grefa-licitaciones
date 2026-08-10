"""Búsqueda web de convocatorias/premios asociados a entidades vigiladas.

- Por defecto: DuckDuckGo HTML (sin API key).
- Opcional: Google Custom Search si hay ``[web_search] api_key`` y ``cx`` en Secrets.

Solo se conservan resultados cuyo título o snippet **contienen la cadena** de
la entidad (sin acentos, case-insensitive).
"""

from __future__ import annotations

import logging
import re
import time
import unicodedata
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup

LOGGER = logging.getLogger(__name__)

USER_AGENT = "GREFA-Licitaciones/1.0 (busqueda entidades premios)"
REQUEST_TIMEOUT = 30
MIN_INTERVAL_S = 0.8

WEB_COLUMNS: tuple[str, ...] = (
    "entidad",
    "titulo",
    "url",
    "snippet",
    "fuente",
    "consulta",
)

_last_request_at = 0.0


class WebSearchError(RuntimeError):
    """Fallo en la búsqueda web."""


def empty_web_dataframe() -> pd.DataFrame:
    return pd.DataFrame(columns=list(WEB_COLUMNS))


def _normalize(texto: str) -> str:
    if not texto:
        return ""
    descompuesto = unicodedata.normalize("NFKD", str(texto))
    sin_tildes = "".join(c for c in descompuesto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sin_tildes.lower()).strip()


def contiene_cadena(texto: str, entidad: str) -> bool:
    """True si ``texto`` contiene la cadena de la entidad (normalizada)."""
    haystack = _normalize(texto)
    needle = _normalize(entidad)
    if not haystack or not needle:
        return False
    return needle in haystack


def _throttle() -> None:
    global _last_request_at
    ahora = time.monotonic()
    espera = MIN_INTERVAL_S - (ahora - _last_request_at)
    if espera > 0:
        time.sleep(espera)
    _last_request_at = time.monotonic()


def _secret(*ruta: str) -> Any:
    try:
        import streamlit as st

        nodo: Any = st.secrets
        for parte in ruta:
            if parte not in nodo:
                return None
            nodo = nodo[parte]
        return nodo
    except Exception:
        return None


def google_cse_configured() -> bool:
    return bool(_secret("web_search", "api_key") and _secret("web_search", "cx"))


def build_query(entidad: str, *, extra: str = "") -> str:
    """Consulta compacta (DuckDuckGo HTML rechaza OR muy largos y a menudo las comillas)."""
    entidad = (entidad or "").strip()
    base = f"{entidad} premio convocatoria ayudas"
    extra = (extra or "").strip()
    return f"{base} {extra}".strip() if extra else base


def build_queries(entidad: str, *, extra: str = "") -> list[str]:
    """Varias consultas cortas por entidad para mejorar cobertura."""
    entidad = (entidad or "").strip()
    if not entidad:
        return []
    extra = (extra or "").strip()
    variantes = [
        f"{entidad} premio convocatoria",
        f"{entidad} ayudas subvenciones",
        f"{entidad} concurso premios",
    ]
    if extra:
        variantes = [f"{q} {extra}" for q in variantes]
    return variantes


def _unwrap_ddg_url(href: str) -> str:
    if not href:
        return ""
    if "uddg=" in href:
        try:
            parsed = urlparse(href)
            qs = parse_qs(parsed.query)
            if "uddg" in qs:
                return unquote(qs["uddg"][0])
        except Exception:
            pass
    return href


def search_duckduckgo(consulta: str, *, max_results: int = 10) -> list[dict[str, str]]:
    _throttle()
    try:
        respuesta = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": consulta},
            headers={"User-Agent": USER_AGENT, "Accept-Language": "es-ES,es;q=0.9"},
            timeout=REQUEST_TIMEOUT,
        )
        respuesta.raise_for_status()
    except requests.RequestException as exc:
        raise WebSearchError(f"DuckDuckGo no disponible: {exc}") from exc

    soup = BeautifulSoup(respuesta.text, "html.parser")
    resultados: list[dict[str, str]] = []
    for item in soup.select(".result"):
        enlace = item.select_one("a.result__a")
        if not enlace:
            continue
        titulo = enlace.get_text(" ", strip=True)
        url = _unwrap_ddg_url(str(enlace.get("href") or ""))
        snippet_el = item.select_one(".result__snippet")
        snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""
        if not titulo or not url or url.startswith("/"):
            continue
        resultados.append(
            {
                "titulo": titulo,
                "url": url,
                "snippet": snippet,
                "fuente": "DuckDuckGo",
                "consulta": consulta,
            }
        )
        if len(resultados) >= max_results:
            break
    return resultados


def search_google_cse(consulta: str, *, max_results: int = 10) -> list[dict[str, str]]:
    api_key = _secret("web_search", "api_key")
    cx = _secret("web_search", "cx")
    if not api_key or not cx:
        raise WebSearchError("Google CSE no configurado ([web_search] api_key + cx).")

    _throttle()
    try:
        respuesta = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={
                "key": api_key,
                "cx": cx,
                "q": consulta,
                "num": min(max_results, 10),
                "hl": "es",
                "gl": "es",
            },
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        respuesta.raise_for_status()
        data = respuesta.json()
    except requests.RequestException as exc:
        raise WebSearchError(f"Google CSE falló: {exc}") from exc

    resultados: list[dict[str, str]] = []
    for item in data.get("items") or []:
        resultados.append(
            {
                "titulo": str(item.get("title") or ""),
                "url": str(item.get("link") or ""),
                "snippet": str(item.get("snippet") or ""),
                "fuente": "Google CSE",
                "consulta": consulta,
            }
        )
    return resultados


def search_web(
    consulta: str,
    *,
    max_results: int = 10,
    prefer_google: bool = True,
) -> list[dict[str, str]]:
    """Busca en la web; Google CSE si está configurado, si no DuckDuckGo."""
    errores: list[str] = []
    if prefer_google and google_cse_configured():
        try:
            return search_google_cse(consulta, max_results=max_results)
        except WebSearchError as exc:
            errores.append(str(exc))
            LOGGER.warning("Google CSE falló, se usa DuckDuckGo: %s", exc)
    try:
        return search_duckduckgo(consulta, max_results=max_results)
    except WebSearchError as exc:
        if errores:
            raise WebSearchError("; ".join(errores + [str(exc)])) from exc
        raise


def filtrar_contiene_entidad(
    resultados: list[dict[str, str]],
    entidad: str,
) -> list[dict[str, str]]:
    """Conserva solo filas cuyo título o snippet contienen la cadena de entidad."""
    filtrados: list[dict[str, str]] = []
    for item in resultados:
        blob = f"{item.get('titulo', '')} {item.get('snippet', '')} {item.get('url', '')}"
        if contiene_cadena(blob, entidad):
            fila = dict(item)
            fila["entidad"] = entidad
            filtrados.append(fila)
    return filtrados


def buscar_entidades_en_web(
    entidades: list[str],
    *,
    max_por_entidad: int = 8,
    extra_query: str = "",
) -> tuple[pd.DataFrame, str]:
    """Busca en la web cada entidad activa y filtra por contención de cadena.

    Returns:
        (dataframe, origen legible)
    """
    if not entidades:
        return empty_web_dataframe(), "Sin entidades activas"

    filas: list[dict[str, str]] = []
    vistos_url: set[str] = set()
    origenes: list[str] = []
    motor = "Google CSE" if google_cse_configured() else "DuckDuckGo"

    for entidad in entidades:
        consultas = build_queries(entidad, extra=extra_query)
        crudos_ent: list[dict[str, str]] = []
        error_ent = False
        for consulta in consultas:
            try:
                crudos_ent.extend(
                    search_web(consulta, max_results=max(max_por_entidad, 6))
                )
            except WebSearchError as exc:
                LOGGER.warning("Búsqueda web «%s»: %s", entidad, exc)
                error_ent = True
                break
        if error_ent and not crudos_ent:
            origenes.append(f"«{entidad}» error")
            continue
        # Deduplicar crudos por URL antes de filtrar
        vistos_local: set[str] = set()
        unicos: list[dict[str, str]] = []
        for item in crudos_ent:
            u = (item.get("url") or "").strip().lower()
            if not u or u in vistos_local:
                continue
            vistos_local.add(u)
            unicos.append(item)
        filtrados = filtrar_contiene_entidad(unicos, entidad)[:max_por_entidad]
        origenes.append(f"«{entidad}» ({len(filtrados)})")
        for item in filtrados:
            url = (item.get("url") or "").strip().lower()
            if not url or url in vistos_url:
                continue
            vistos_url.add(url)
            filas.append(item)

    df = pd.DataFrame(filas) if filas else empty_web_dataframe()
    for col in WEB_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    if not df.empty:
        df = df[list(WEB_COLUMNS)].reset_index(drop=True)
    origen = f"Web · {motor} · {len(df)} resultados · " + ", ".join(origenes[:8])
    if len(origenes) > 8:
        origen += "…"
    return df, origen
