"""Descarga y normalización de convocatorias de la BDNS / infosubvenciones.es.

API pública: https://www.infosubvenciones.es/bdnstrans/api
Buenas prácticas: máx. ~10 GET/s; preferir búsquedas acotadas y caché.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Iterable, Sequence

import pandas as pd
import requests

LOGGER = logging.getLogger(__name__)

API_BASE = "https://www.infosubvenciones.es/bdnstrans/api"
FICHA_URL = "https://www.infosubvenciones.es/bdnstrans/GE/es/convocatorias/{codigo}"
USER_AGENT = "GREFA-Licitaciones/1.0 (monitorizacion ayudas y premios BDNS)"
REQUEST_TIMEOUT = 60
MIN_INTERVAL_S = 0.12  # ~8 req/s, bajo el límite oficial de 10/s

COLUMNS: tuple[str, ...] = (
    "expediente",
    "titulo",
    "organo_contratacion",
    "presupuesto_sin_iva",
    "presupuesto_con_iva",
    "url",
    "fecha_actualizacion",
    "ubicacion",
    "cpvs",
    "cpvs_texto",
    "estado",
    "tipo_contrato",
    "fecha_limite",
    "descripcion",
    "nif_organo",
    "nif_adjudicatario",
    "adjudicatario",
    "documentos",
    "nivel_admin",
    "instrumentos",
    "finalidad",
    "sede_electronica",
    "abierto",
    "id_interno",
)

COLUMN_LABELS: dict[str, str] = {
    "expediente": "Código BDNS",
    "titulo": "Título / Objeto",
    "organo_contratacion": "Órgano convocante",
    "presupuesto_sin_iva": "Presupuesto total",
    "url": "Enlace BDNS",
    "fecha_actualizacion": "Fecha de recepción",
    "ubicacion": "Ámbito / Región",
    "estado": "Estado",
    "tipo_contrato": "Instrumento",
    "fecha_limite": "Fin de solicitud",
    "descripcion": "Descripción",
    "relevancia": "Relevancia GREFA (%)",
    "categoria": "Categoría",
    "badge": "Etiqueta",
    "keywords_match": "Palabras clave coincidentes",
    "justificacion": "Motivo de la puntuación",
    "nivel_admin": "Nivel administrativo",
    "finalidad": "Finalidad",
    "sede_electronica": "Sede electrónica",
}

#: Términos semilla para acotar la API a la actividad GREFA.
DEFAULT_SEARCH_TERMS: tuple[str, ...] = (
    "biodiversidad",
    "fauna",
    "conservación",
    "medio ambiente",
    "educación ambiental",
    "hábitat",
    "especies",
    "naturaleza",
)

_last_request_at = 0.0


class IngestionError(RuntimeError):
    """Fallo al hablar con la API de la BDNS."""


def empty_dataframe() -> pd.DataFrame:
    return pd.DataFrame(columns=list(COLUMNS))


def _throttle() -> None:
    global _last_request_at
    ahora = time.monotonic()
    espera = MIN_INTERVAL_S - (ahora - _last_request_at)
    if espera > 0:
        time.sleep(espera)
    _last_request_at = time.monotonic()


def _session() -> requests.Session:
    sesion = requests.Session()
    sesion.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
    )
    return sesion


def _get_json(
    sesion: requests.Session,
    path: str,
    params: dict[str, Any] | None = None,
) -> Any:
    _throttle()
    url = f"{API_BASE}{path}"
    try:
        respuesta = sesion.get(url, params=params or {}, timeout=REQUEST_TIMEOUT)
        respuesta.raise_for_status()
        return respuesta.json()
    except requests.RequestException as exc:
        raise IngestionError(f"Error BDNS {path}: {exc}") from exc


def _texto(valor: Any) -> str:
    if valor is None:
        return ""
    try:
        if pd.isna(valor):
            return ""
    except (TypeError, ValueError):
        pass
    return str(valor).strip()


def ficha_url(codigo: str) -> str:
    codigo = _texto(codigo)
    return FICHA_URL.format(codigo=codigo) if codigo else ""


def _organos_desde_resumen(item: dict[str, Any]) -> str:
    partes = [
        _texto(item.get("nivel2")),
        _texto(item.get("nivel3")),
    ]
    return " · ".join(p for p in partes if p)


def _organos_desde_detalle(detalle: dict[str, Any]) -> str:
    organo = detalle.get("organo") or {}
    if isinstance(organo, dict):
        partes = [
            _texto(organo.get("nivel2")),
            _texto(organo.get("nivel3")),
        ]
        return " · ".join(p for p in partes if p) or _texto(organo.get("nivel1"))
    return ""


def _instrumentos(detalle: dict[str, Any]) -> list[str]:
    raw = detalle.get("instrumentos") or []
    out: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            desc = _texto(item.get("descripcion"))
            if desc:
                out.append(desc)
        elif item:
            out.append(_texto(item))
    return out


def _regiones(detalle: dict[str, Any]) -> str:
    raw = detalle.get("regiones") or []
    nombres: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            desc = _texto(item.get("descripcion"))
            if desc:
                nombres.append(desc)
    return ", ".join(nombres)


def _documentos(detalle: dict[str, Any]) -> list[dict[str, str]]:
    docs: list[dict[str, str]] = []
    for item in detalle.get("documentos") or []:
        if not isinstance(item, dict):
            continue
        docs.append(
            {
                "id": _texto(item.get("id")),
                "nombre": _texto(item.get("nombreFic") or item.get("descripcion")),
                "descripcion": _texto(item.get("descripcion")),
            }
        )
    return docs


def _estado(detalle: dict[str, Any], resumen: dict[str, Any] | None = None) -> str:
    """Deriva un estado usable en filtros.

    El campo ``abierto`` de la BDNS no siempre refleja el plazo de solicitud
    (hay convocatorias con fin futuro y ``abierto=false``). Preferimos la fecha.
    """
    from datetime import date

    fin = _texto(detalle.get("fechaFinSolicitud"))
    if fin:
        try:
            fin_d = date.fromisoformat(fin[:10])
            if fin_d >= date.today():
                return "Abierta"
            return "Cerrada"
        except ValueError:
            pass
    abierto = detalle.get("abierto")
    if abierto is True:
        return "Abierta"
    if abierto is False:
        return "Cerrada"
    return "Publicada"


def _descripcion_enriquecida(detalle: dict[str, Any]) -> str:
    partes = [
        _texto(detalle.get("descripcion")),
        _texto(detalle.get("descripcionFinalidad")),
        _texto(detalle.get("descripcionBasesReguladoras")),
    ]
    anuncios = detalle.get("anuncios") or []
    if anuncios and isinstance(anuncios[0], dict):
        titulo_anuncio = _texto(anuncios[0].get("titulo"))
        if titulo_anuncio:
            partes.append(titulo_anuncio)
    # Quitar HTML muy básico del extracto si viene
    texto = " | ".join(p for p in partes if p)
    return texto[:4000]


def resumen_a_fila(item: dict[str, Any]) -> dict[str, Any]:
    codigo = _texto(item.get("numeroConvocatoria") or item.get("codigoBDNS"))
    return {
        "expediente": codigo,
        "titulo": _texto(item.get("descripcion")),
        "organo_contratacion": _organos_desde_resumen(item),
        "presupuesto_sin_iva": None,
        "presupuesto_con_iva": None,
        "url": ficha_url(codigo),
        "fecha_actualizacion": _texto(item.get("fechaRecepcion")),
        "ubicacion": "",
        "cpvs": [],
        "cpvs_texto": "",
        "estado": "Publicada",
        "tipo_contrato": "",
        "fecha_limite": None,
        "descripcion": _texto(item.get("descripcion")),
        "nif_organo": "",
        "nif_adjudicatario": "",
        "adjudicatario": "",
        "documentos": [],
        "nivel_admin": _texto(item.get("nivel1")),
        "instrumentos": [],
        "finalidad": "",
        "sede_electronica": "",
        "abierto": None,
        "id_interno": item.get("id"),
    }


def detalle_a_fila(detalle: dict[str, Any], resumen: dict[str, Any] | None = None) -> dict[str, Any]:
    base = resumen_a_fila(resumen) if resumen else {c: None for c in COLUMNS}
    codigo = _texto(detalle.get("codigoBDNS") or base.get("expediente"))
    instrumentos = _instrumentos(detalle)
    presupuesto = detalle.get("presupuestoTotal")
    try:
        presupuesto_f = float(presupuesto) if presupuesto is not None else None
    except (TypeError, ValueError):
        presupuesto_f = None

    base.update(
        {
            "expediente": codigo,
            "titulo": _texto(detalle.get("descripcion")) or base.get("titulo") or "",
            "organo_contratacion": _organos_desde_detalle(detalle)
            or base.get("organo_contratacion")
            or "",
            "presupuesto_sin_iva": presupuesto_f,
            "presupuesto_con_iva": presupuesto_f,
            "url": ficha_url(codigo),
            "fecha_actualizacion": _texto(detalle.get("fechaRecepcion"))
            or base.get("fecha_actualizacion"),
            "ubicacion": _regiones(detalle),
            "estado": _estado(detalle, resumen),
            "tipo_contrato": ", ".join(instrumentos) or base.get("tipo_contrato") or "",
            "fecha_limite": _texto(detalle.get("fechaFinSolicitud")) or None,
            "descripcion": _descripcion_enriquecida(detalle),
            "documentos": _documentos(detalle),
            "nivel_admin": _texto((detalle.get("organo") or {}).get("nivel1"))
            if isinstance(detalle.get("organo"), dict)
            else base.get("nivel_admin") or "",
            "instrumentos": instrumentos,
            "finalidad": _texto(detalle.get("descripcionFinalidad")),
            "sede_electronica": _texto(detalle.get("sedeElectronica")),
            "abierto": detalle.get("abierto"),
            "id_interno": detalle.get("id") or base.get("id_interno"),
            "cpvs": [],
            "cpvs_texto": "",
        }
    )
    return base


def fetch_busqueda_pagina(
    sesion: requests.Session,
    *,
    descripcion: str,
    page: int = 0,
    page_size: int = 50,
) -> tuple[list[dict[str, Any]], int]:
    data = _get_json(
        sesion,
        "/convocatorias/busqueda",
        {
            "descripcion": descripcion,
            "page": page,
            "pageSize": page_size,
        },
    )
    if not isinstance(data, dict):
        return [], 0
    content = data.get("content") or []
    total = int(data.get("totalElements") or 0)
    return list(content), total


def fetch_ultimas_pagina(
    sesion: requests.Session,
    *,
    page: int = 0,
    page_size: int = 50,
) -> tuple[list[dict[str, Any]], int]:
    data = _get_json(
        sesion,
        "/convocatorias/ultimas",
        {"page": page, "pageSize": page_size},
    )
    if not isinstance(data, dict):
        return [], 0
    return list(data.get("content") or []), int(data.get("totalElements") or 0)


def fetch_detalle(
    sesion: requests.Session,
    codigo_bdns: str,
) -> dict[str, Any] | None:
    codigo = _texto(codigo_bdns)
    if not codigo:
        return None
    data = _get_json(sesion, "/convocatorias", {"numConv": codigo})
    if isinstance(data, dict) and data.get("codigoBDNS"):
        return data
    if isinstance(data, list) and data:
        primero = data[0]
        return primero if isinstance(primero, dict) else None
    return None


def _terminos_busqueda(
    keywords: Sequence[str] | None,
    max_terms: int,
    entidades: Sequence[str] | None = None,
) -> list[str]:
    """Prioriza entidades vigiladas, luego semillas GREFA y keywords."""
    vistos: set[str] = set()
    out: list[str] = []
    for termino in list(entidades or []) + list(DEFAULT_SEARCH_TERMS) + list(keywords or []):
        clave = _texto(termino).lower()
        if not clave or clave in vistos:
            continue
        vistos.add(clave)
        out.append(_texto(termino))
        if len(out) >= max_terms:
            break
    return out


def fetch_convocatorias_bdns(
    *,
    keywords: Sequence[str] | None = None,
    entidades: Sequence[str] | None = None,
    max_terms: int = 8,
    pages_per_term: int = 1,
    page_size: int = 40,
    enrich: bool = True,
    max_enrich: int = 120,
    incluir_ultimas: bool = True,
    pages_ultimas: int = 1,
) -> tuple[pd.DataFrame, str]:
    """Descarga convocatorias relevantes y las normaliza al esquema GREFA.

    Returns:
        (dataframe, origen legible)
    """
    sesion = _session()
    por_codigo: dict[str, dict[str, Any]] = {}
    origenes: list[str] = []

    # Las entidades cuentan aparte del tope de keywords temáticos.
    n_ent = len([e for e in (entidades or []) if _texto(e)])
    tope = max(max_terms, n_ent + max(3, max_terms // 2))
    terminos = _terminos_busqueda(keywords, tope, entidades=entidades)
    for termino in terminos:
        for page in range(max(1, pages_per_term)):
            try:
                items, total = fetch_busqueda_pagina(
                    sesion,
                    descripcion=termino,
                    page=page,
                    page_size=page_size,
                )
            except IngestionError as exc:
                LOGGER.warning("Búsqueda BDNS «%s» fallida: %s", termino, exc)
                continue
            if page == 0:
                origenes.append(f"«{termino}» ({total})")
            for item in items:
                codigo = _texto(item.get("numeroConvocatoria"))
                if codigo and codigo not in por_codigo:
                    por_codigo[codigo] = item
            if not items or (page + 1) * page_size >= total:
                break

    if incluir_ultimas:
        for page in range(max(1, pages_ultimas)):
            try:
                items, _total = fetch_ultimas_pagina(
                    sesion, page=page, page_size=page_size
                )
            except IngestionError as exc:
                LOGGER.warning("Últimas BDNS fallidas: %s", exc)
                break
            for item in items:
                codigo = _texto(item.get("numeroConvocatoria"))
                if codigo and codigo not in por_codigo:
                    por_codigo[codigo] = item
            if not items:
                break
        origenes.append(f"últimas×{pages_ultimas}")

    if not por_codigo:
        return empty_dataframe(), "BDNS (sin resultados)"

    filas: list[dict[str, Any]] = []
    codigos = list(por_codigo.keys())
    a_enriquecer = codigos[: max(0, max_enrich)] if enrich else []

    for codigo in codigos:
        resumen = por_codigo[codigo]
        if enrich and codigo in a_enriquecer:
            try:
                detalle = fetch_detalle(sesion, codigo)
            except IngestionError as exc:
                LOGGER.debug("Detalle %s omitido: %s", codigo, exc)
                detalle = None
            if detalle:
                filas.append(detalle_a_fila(detalle, resumen))
                continue
        filas.append(resumen_a_fila(resumen))

    df = pd.DataFrame(filas)
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = None if col in {"presupuesto_sin_iva", "presupuesto_con_iva"} else (
                [] if col in {"cpvs", "documentos", "instrumentos"} else ""
            )
    df = df[list(COLUMNS)].drop_duplicates(subset=["expediente"], keep="first")
    df = df.reset_index(drop=True)

    origen = (
        f"BDNS · {len(df)} convocatorias · "
        + ", ".join(origenes[:6])
        + ("…" if len(origenes) > 6 else "")
    )
    return df, origen


def filter_by_nivel(df: pd.DataFrame, niveles: Iterable[str] | None) -> pd.DataFrame:
    if df.empty or not niveles:
        return df
    permitidos = {str(n).strip().upper() for n in niveles if str(n).strip()}
    if not permitidos:
        return df
    serie = df.get("nivel_admin", pd.Series(dtype=str)).fillna("").astype(str).str.upper()
    return df[serie.isin(permitidos)].reset_index(drop=True)
