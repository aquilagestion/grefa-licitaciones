"""Descarga y parseo de los feeds ATOM de la Plataforma de Contratación del Sector Público.

La PLACSP publica sindicaciones ATOM en las que cada `<entry>` incorpora un
documento CODICE/UBL (`ContractFolderStatus`) con el detalle del expediente.
Los prefijos de namespace varían entre versiones de CODICE (cbc, cac,
cac-place-ext, ...), por lo que todo el parseo se hace por *local-name* y es
inmune a esos cambios.

Fuentes PLACSP (no mezclar conceptualmente):

* **sindicacion_643** — perfiles de contratante *alojados* en la propia PLACSP
  (AGE, locales y CCAA sin plataforma propia).
* **sindicacion_1044** — plataformas autonómicas *agregadas* (art. 347.3 LCSP),
  sin contratos menores.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Iterable, Sequence

import feedparser
import pandas as pd
import requests
from bs4 import BeautifulSoup
from lxml import etree

from config.ccaa_sources import (
    FUENTE_PLACSP,
    FUENTE_PLACSP_1044,
    FUENTE_PLACSP_643,
    FUENTE_PLACSP_LOCAL,
    enrich_comunidad_autonoma,
    enrich_fuente,
    fuente_desde_url_feed,
    infer_comunidad_autonoma,
)

LOGGER = logging.getLogger(__name__)

ATOM_NS = "http://www.w3.org/2005/Atom"

#: Feed histórico de la especificación del proyecto (hoy suele devolver 404).
PRIMARY_FEED_URL = (
    "https://contrataciondelestado.es/sourcing/licitaciones/ATOM/licitaciones.atom"
)

#: Perfiles de contratante alojados en la propia PLACSP.
PLACSP_FEED_643 = (
    "https://contrataciondelestado.es/sindicacion/sindicacion_643/"
    "licitacionesPerfilesContratanteCompleto3.atom"
)

#: Plataformas autonómicas agregadas (sin menores). Se prueba la `_3` primero.
PLACSP_FEEDS_1044: tuple[str, ...] = (
    "https://contrataciondelestado.es/sindicacion/sindicacion_1044/"
    "PlataformasAgregadasSinMenores_3.atom",
    "https://contrataciondelestado.es/sindicacion/sindicacion_1044/"
    "PlataformasAgregadasSinMenores.atom",
)

#: Alias de compatibilidad: orden de prueba si se pide un único feed.
FALLBACK_FEED_URLS: tuple[str, ...] = (PLACSP_FEED_643, *PLACSP_FEEDS_1044)

USER_AGENT = "GREFA-Licitaciones/1.0 (monitorizacion de licitaciones publicas)"
REQUEST_TIMEOUT = 60

#: Esquema del DataFrame devuelto por el módulo.
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
    "fuente",
    "comunidad_autonoma",
)

#: Etiquetas legibles para la interfaz y las exportaciones.
COLUMN_LABELS: dict[str, str] = {
    "expediente": "ID Expediente",
    "titulo": "Título / Objeto",
    "organo_contratacion": "Órgano de Contratación",
    "presupuesto_sin_iva": "Presupuesto base (sin IVA)",
    "presupuesto_con_iva": "Presupuesto (con IVA)",
    "url": "Enlace PLACSP",
    "fecha_actualizacion": "Fecha de actualización",
    "ubicacion": "Ubicación / Provincia",
    "cpvs_texto": "Códigos CPV",
    "estado": "Estado",
    "tipo_contrato": "Tipo de contrato",
    "fecha_limite": "Fecha límite de presentación",
    "descripcion": "Descripción",
    "nif_organo": "NIF órgano",
    "nif_adjudicatario": "NIF adjudicatario",
    "adjudicatario": "Adjudicatario",
    "fuente": "Fuente",
    "comunidad_autonoma": "Comunidad Autónoma",
    "relevancia": "Relevancia GREFA (%)",
    "categoria": "Categoría",
    "badge": "Etiqueta",
    "cpvs_match": "CPV coincidentes",
    "keywords_match": "Palabras clave coincidentes",
    "justificacion": "Motivo de la puntuación",
    "compartir_whatsapp": "Compartir WhatsApp",
    "compartir_email": "Compartir Email",
}

CONTRACT_TYPES: dict[str, str] = {
    "1": "Obras",
    "2": "Servicios",
    "3": "Suministros",
    "21": "Gestión de servicios públicos",
    "31": "Concesión de obras",
    "32": "Concesión de servicios",
    "40": "Colaboración público-privada",
    "7": "Administrativo especial",
    "8": "Privado",
    "50": "Patrimonial",
}

STATUS_CODES: dict[str, str] = {
    "PRE": "Anuncio previo",
    "PUB": "Publicada",
    "EV": "En evaluación",
    "ADJ": "Adjudicada",
    "RES": "Resuelta",
    "ANUL": "Anulada",
    "CANC": "Cancelada",
    "DES": "Desierta",
}


class IngestionError(RuntimeError):
    """Error irrecuperable durante la descarga o el parseo del feed."""


# ---------------------------------------------------------------------------
# Utilidades XML
# ---------------------------------------------------------------------------
def _findall(element, local_name: str, direct: bool = False) -> list:
    """Busca elementos por nombre local, ignorando el namespace."""
    prefijo = "./" if direct else ".//"
    return element.xpath(f"{prefijo}*[local-name()=$n]", n=local_name)


def _find(element, local_name: str, direct: bool = False):
    encontrados = _findall(element, local_name, direct=direct)
    return encontrados[0] if encontrados else None


def _text(element, local_name: str, direct: bool = False) -> str:
    if element is None:
        return ""
    nodo = _find(element, local_name, direct=direct)
    if nodo is None or nodo.text is None:
        return ""
    return " ".join(nodo.text.split())


def _texts(element, local_name: str) -> list[str]:
    if element is None:
        return []
    valores = []
    for nodo in _findall(element, local_name):
        if nodo.text:
            valores.append(" ".join(nodo.text.split()))
    return valores


def _clean_html(valor: str) -> str:
    """Elimina el marcado HTML que algunos organismos incrustan en los textos."""
    if not valor or "<" not in valor:
        return valor
    texto = BeautifulSoup(valor, "html.parser").get_text(" ")
    return " ".join(texto.split())


def _to_float(valor: str) -> float | None:
    if not valor:
        return None
    limpio = valor.replace("\u00a0", "").replace(" ", "")
    # Formatos posibles: 1234.56 / 1.234,56 / 1,234.56
    if "," in limpio and "." in limpio:
        if limpio.rfind(",") > limpio.rfind("."):
            limpio = limpio.replace(".", "").replace(",", ".")
        else:
            limpio = limpio.replace(",", "")
    elif "," in limpio:
        limpio = limpio.replace(",", ".")
    try:
        return float(limpio)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Parseo de una entrada del feed
# ---------------------------------------------------------------------------
_SUMMARY_PATTERNS = {
    "organo": re.compile(r"Órgano de [Cc]ontratación\s*:\s*([^;\n]+)", re.IGNORECASE),
    "expediente": re.compile(r"Id licitación\s*:\s*([^;\n]+)", re.IGNORECASE),
    "importe": re.compile(r"Importe\s*:\s*([0-9.,]+)", re.IGNORECASE),
    "estado": re.compile(r"Estado\s*:\s*([^;\n]+)", re.IGNORECASE),
}

_NIF_ES_RE = re.compile(
    r"^(?:"
    r"[ABCDEFGHJNPQRSUVW]\d{7}[0-9A-J]|"
    r"\d{8}[A-Z]|"
    r"[XYZ]\d{7}[A-Z]|"
    r"[PAFQS]\d{7,8}[A-Z0-9]?"
    r")$",
    re.IGNORECASE,
)


def _normalizar_nif(valor: str) -> str:
    return re.sub(r"[\s\-/]", "", (valor or "").upper())


def _es_nif_espanol(valor: str) -> bool:
    limpio = _normalizar_nif(valor)
    if not limpio or len(limpio) < 8 or len(limpio) > 10:
        return False
    if limpio.startswith("L") and len(limpio) >= 9:
        return False
    if limpio.isdigit() and len(limpio) > 9:
        return False
    return bool(_NIF_ES_RE.match(limpio))


def _ids_party(element) -> list[str]:
    if element is None:
        return []
    ids: list[str] = []
    for ident in _findall(element, "PartyIdentification"):
        for id_nodo in _findall(ident, "ID", direct=True):
            if id_nodo.text:
                ids.append(id_nodo.text.strip())
    return ids


def _elegir_nif(ids: Sequence[str]) -> str:
    for candidato in ids:
        if _es_nif_espanol(candidato):
            return _normalizar_nif(candidato)
    return ""


def _nif_organo(carpeta) -> str:
    parte = _find(carpeta, "LocatedContractingParty") if carpeta is not None else None
    if parte is None:
        return ""
    party = _find(parte, "Party", direct=True)
    if party is None:
        party = parte
    return _elegir_nif(_ids_party(party))


def _adjudicatario(carpeta) -> tuple[str, str]:
    """Extrae NIF y nombre del ganador (WinningParty / TenderResult).

    En CODICE el nombre suele ir en PartyName/Name (no como hijo directo de Party)
    y a veces WinningParty trae PartyIdentification/PartyName sin nodo Party.
    Algunos NIF de personas físicas vienen enmascarados (***1234**) y se omiten.
    """
    if carpeta is None:
        return "", ""
    candidatos = _findall(carpeta, "WinningParty")
    if not candidatos:
        # Algunas versiones anidan el ganador bajo TenderResult
        resultado = _find(carpeta, "TenderResult")
        if resultado is not None:
            candidatos = _findall(resultado, "WinningParty")
    for ganador in candidatos:
        party = _find(ganador, "Party", direct=True)
        if party is None:
            party = ganador
        # PartyName/Name (estándar) o Name en cualquier profundidad
        nombre = (
            _text(party, "Name")
            or _text(ganador, "Name")
            or _text(party, "PartyName")
        )
        nif = _elegir_nif(_ids_party(party)) or _elegir_nif(_ids_party(ganador))
        if nombre or nif:
            return nif, _clean_html(nombre)
    return "", ""


def _entry_link(entry) -> str:
    enlaces = entry.findall(f"{{{ATOM_NS}}}link")
    if not enlaces:
        enlaces = _findall(entry, "link")
    preferido = ""
    for enlace in enlaces:
        href = (enlace.get("href") or "").strip()
        if not href:
            continue
        rel = (enlace.get("rel") or "alternate").lower()
        if rel == "alternate":
            return href
        preferido = preferido or href
    if preferido:
        return preferido
    identificador = _text(entry, "id", direct=True)
    return identificador if identificador.startswith("http") else ""


def _normalize_cpv(codigo: str) -> str:
    digitos = re.sub(r"\D", "", codigo or "")
    return digitos[:8]


def _parse_entry(entry) -> dict[str, Any]:
    resumen = _text(entry, "summary", direct=True)
    coincidencias = {
        clave: (patron.search(resumen).group(1).strip() if patron.search(resumen) else "")
        for clave, patron in _SUMMARY_PATTERNS.items()
    }

    carpeta = _find(entry, "ContractFolderStatus")
    proyecto = _find(carpeta, "ProcurementProject", direct=True) if carpeta is not None else None

    expediente = _text(carpeta, "ContractFolderID") or coincidencias["expediente"]

    titulo = _text(proyecto, "Name", direct=True) if proyecto is not None else ""
    if not titulo:
        titulo = _text(entry, "title", direct=True)

    descripcion = ""
    if proyecto is not None:
        descripcion = _text(proyecto, "Description", direct=True)
    if not descripcion:
        # Objetos de los lotes: aportan contexto muy útil para el scoring.
        lotes = _findall(carpeta, "ProcurementProjectLot") if carpeta is not None else []
        partes = []
        for lote in lotes:
            nombre = _text(lote, "Name")
            if nombre:
                partes.append(nombre)
        descripcion = " | ".join(partes)

    organo = ""
    parte_contratante = _find(carpeta, "LocatedContractingParty") if carpeta is not None else None
    if parte_contratante is not None:
        organo = _text(parte_contratante, "Name")
    if not organo:
        organo = coincidencias["organo"]

    presupuesto_sin_iva = None
    presupuesto_con_iva = None
    if proyecto is not None:
        importes = _find(proyecto, "BudgetAmount", direct=True)
        if importes is not None:
            presupuesto_sin_iva = _to_float(_text(importes, "TaxExclusiveAmount"))
            presupuesto_con_iva = _to_float(_text(importes, "TotalAmount"))
    if presupuesto_sin_iva is None:
        presupuesto_sin_iva = _to_float(coincidencias["importe"])

    ubicacion = ""
    if proyecto is not None:
        localizacion = _find(proyecto, "RealizedLocation", direct=True)
        if localizacion is not None:
            ubicacion = _text(localizacion, "CountrySubentity") or _text(localizacion, "CityName")
    if not ubicacion and parte_contratante is not None:
        direccion = _find(parte_contratante, "PostalAddress")
        if direccion is not None:
            ubicacion = _text(direccion, "CountrySubentity") or _text(direccion, "CityName")

    cpvs_normalizados: list[str] = []
    for codigo in _texts(carpeta, "ItemClassificationCode"):
        normalizado = _normalize_cpv(codigo)
        if normalizado and normalizado not in cpvs_normalizados:
            cpvs_normalizados.append(normalizado)

    codigo_estado = _text(carpeta, "ContractFolderStatusCode")
    estado = STATUS_CODES.get(codigo_estado.upper(), codigo_estado or coincidencias["estado"])

    codigo_tipo = _text(proyecto, "TypeCode", direct=True) if proyecto is not None else ""
    tipo_contrato = CONTRACT_TYPES.get(codigo_tipo, codigo_tipo)

    fecha_limite = ""
    proceso = _find(carpeta, "TenderingProcess") if carpeta is not None else None
    if proceso is not None:
        periodo = _find(proceso, "TenderSubmissionDeadlinePeriod")
        if periodo is not None:
            fecha_limite = _text(periodo, "EndDate")

    nif_adjudicatario, adjudicatario = _adjudicatario(carpeta)

    from modules.pliegos_placsp import extract_documentos_from_carpeta

    organo_limpio = _clean_html(organo)
    return {
        "expediente": expediente,
        "titulo": _clean_html(titulo),
        "organo_contratacion": organo_limpio,
        "presupuesto_sin_iva": presupuesto_sin_iva,
        "presupuesto_con_iva": presupuesto_con_iva,
        "url": _entry_link(entry),
        "fecha_actualizacion": _text(entry, "updated", direct=True),
        "ubicacion": ubicacion,
        "cpvs": cpvs_normalizados,
        "cpvs_texto": ", ".join(cpvs_normalizados),
        "estado": estado,
        "tipo_contrato": tipo_contrato,
        "fecha_limite": fecha_limite,
        "descripcion": _clean_html(descripcion) or _clean_html(resumen),
        "nif_organo": _nif_organo(carpeta),
        "nif_adjudicatario": nif_adjudicatario,
        "adjudicatario": adjudicatario,
        "documentos": extract_documentos_from_carpeta(carpeta),
        "fuente": "",
        "comunidad_autonoma": infer_comunidad_autonoma(ubicacion, organo_limpio),
    }


def _parse_with_feedparser(raw: bytes) -> tuple[list[dict[str, Any]], str]:
    """Plan B: extrae la información básica cuando el XML CODICE no es legible."""
    feed = feedparser.parse(raw)
    registros: list[dict[str, Any]] = []
    for entrada in feed.entries:
        resumen = _clean_html(getattr(entrada, "summary", ""))
        coincidencias = {
            clave: (patron.search(resumen).group(1).strip() if patron.search(resumen) else "")
            for clave, patron in _SUMMARY_PATTERNS.items()
        }
        organo = coincidencias["organo"]
        registros.append(
            {
                "expediente": coincidencias["expediente"],
                "titulo": _clean_html(getattr(entrada, "title", "")),
                "organo_contratacion": organo,
                "presupuesto_sin_iva": _to_float(coincidencias["importe"]),
                "presupuesto_con_iva": None,
                "url": getattr(entrada, "link", ""),
                "fecha_actualizacion": getattr(entrada, "updated", ""),
                "ubicacion": "",
                "cpvs": [],
                "cpvs_texto": "",
                "estado": coincidencias["estado"],
                "tipo_contrato": "",
                "fecha_limite": "",
                "descripcion": resumen,
                "nif_organo": "",
                "nif_adjudicatario": "",
                "adjudicatario": "",
                "documentos": [],
                "fuente": "",
                "comunidad_autonoma": infer_comunidad_autonoma("", organo),
            }
        )

    siguiente = ""
    for enlace in feed.feed.get("links", []):
        if enlace.get("rel") == "next":
            siguiente = enlace.get("href", "")
            break
    return registros, siguiente


def _parse_feed_bytes(raw: bytes) -> tuple[list[dict[str, Any]], str]:
    """Devuelve (registros, url_siguiente_pagina) de una página del feed."""
    parser = etree.XMLParser(recover=True, huge_tree=True, resolve_entities=False)
    try:
        root = etree.fromstring(raw, parser=parser)
    except etree.XMLSyntaxError as exc:  # pragma: no cover - feed corrupto
        raise IngestionError(f"El feed no es XML válido: {exc}") from exc
    if root is None:
        raise IngestionError("El feed no ha devuelto contenido XML procesable.")

    entradas = _findall(root, "entry")
    if not entradas:
        return _parse_with_feedparser(raw)

    registros = [_parse_entry(entry) for entry in entradas]

    siguiente = ""
    for enlace in root.findall(f"{{{ATOM_NS}}}link"):
        if (enlace.get("rel") or "").lower() == "next":
            siguiente = (enlace.get("href") or "").strip()
            break

    return registros, siguiente


# ---------------------------------------------------------------------------
# Construcción del DataFrame
# ---------------------------------------------------------------------------
def empty_dataframe() -> pd.DataFrame:
    """DataFrame vacío con el esquema estándar (evita KeyError en la UI)."""
    return build_dataframe([])


def build_dataframe(
    registros: Sequence[dict[str, Any]],
    *,
    fuente_default: str = "",
) -> pd.DataFrame:
    filas = [dict(r) for r in registros]
    for fila in filas:
        for col in COLUMNS:
            fila.setdefault(col, [] if col in {"cpvs", "documentos"} else None if col.startswith("presupuesto") else "")
    df = pd.DataFrame(filas, columns=list(COLUMNS)) if filas else pd.DataFrame(columns=list(COLUMNS))

    df["presupuesto_sin_iva"] = pd.to_numeric(df["presupuesto_sin_iva"], errors="coerce")
    df["presupuesto_con_iva"] = pd.to_numeric(df["presupuesto_con_iva"], errors="coerce")

    fechas = pd.to_datetime(df["fecha_actualizacion"], errors="coerce", utc=True, format="mixed")
    try:
        fechas = fechas.dt.tz_convert("Europe/Madrid")
    except Exception:  # zoneinfo sin base de datos de husos horarios
        LOGGER.debug("Sin husos horarios locales; se mantienen las fechas en UTC.")
    df["fecha_actualizacion"] = fechas.dt.tz_localize(None)

    df["fecha_limite"] = pd.to_datetime(
        df["fecha_limite"], errors="coerce", format="mixed"
    ).dt.date

    df["cpvs"] = df["cpvs"].apply(lambda valor: list(valor) if isinstance(valor, (list, tuple)) else [])
    df["documentos"] = df["documentos"].apply(
        lambda valor: list(valor) if isinstance(valor, (list, tuple)) else []
    )
    for columna in (
        "expediente",
        "titulo",
        "organo_contratacion",
        "url",
        "ubicacion",
        "cpvs_texto",
        "estado",
        "tipo_contrato",
        "descripcion",
        "nif_organo",
        "nif_adjudicatario",
        "adjudicatario",
        "fuente",
        "comunidad_autonoma",
    ):
        df[columna] = df[columna].fillna("").astype(str).str.strip()

    if fuente_default:
        df = enrich_fuente(df, fuente_default)
    df = enrich_comunidad_autonoma(df)

    if not df.empty:
        df = df.drop_duplicates(subset=["expediente", "url"], keep="first")
        df = df.sort_values("fecha_actualizacion", ascending=False, na_position="last")
        df = df.reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------
def _http_session(session: requests.Session | None = None) -> requests.Session:
    sesion = session or requests.Session()
    sesion.headers.update({"User-Agent": USER_AGENT, "Accept": "application/atom+xml, application/xml;q=0.9, */*;q=0.8"})
    return sesion


def _download(url: str, session: requests.Session) -> bytes:
    respuesta = session.get(url, timeout=REQUEST_TIMEOUT)
    respuesta.raise_for_status()
    return respuesta.content


def parse_atom_bytes(raw: bytes, *, fuente: str = FUENTE_PLACSP_LOCAL) -> pd.DataFrame:
    """Parsea un fichero ATOM ya descargado (útil para trabajar sin conexión)."""
    registros, _ = _parse_feed_bytes(raw)
    return build_dataframe(registros, fuente_default=fuente)


def _fetch_feed_registros(
    url: str,
    *,
    session: requests.Session,
    max_pages: int,
    max_entries: int | None,
) -> tuple[list[dict[str, Any]], int]:
    """Descarga páginas de un feed y devuelve (registros, páginas leídas)."""
    registros: list[dict[str, Any]] = []
    siguiente = url
    paginas = 0
    while siguiente and paginas < max(1, max_pages):
        contenido = _download(siguiente, session)
        nuevos, siguiente = _parse_feed_bytes(contenido)
        registros.extend(nuevos)
        paginas += 1
        if max_entries and len(registros) >= int(max_entries):
            break
    return registros, paginas


def _es_feed_oficial_o_vacio(url: str | None) -> bool:
    """True si conviene fusionar las sindicaciones 643+1044 (URL por defecto/rota)."""
    if not url or not str(url).strip():
        return True
    candidata = str(url).strip()
    if candidata == PRIMARY_FEED_URL:
        return True
    # Ya es una sindicación concreta: no fusionar otras.
    if "sindicacion_643" in candidata or "sindicacion_1044" in candidata:
        return False
    return False


def fetch_placsp_licitaciones(
    feed_url: str | None = None,
    max_pages: int = 3,
    max_entries: int | None = None,
    session: requests.Session | None = None,
    extra_urls: Iterable[str] | None = None,
    *,
    merge_syndications: bool | None = None,
) -> pd.DataFrame:
    """Descarga y normaliza las licitaciones publicadas en la PLACSP.

    Por defecto fusiona las dos sindicaciones oficiales:

    * ``placsp_643`` — perfiles alojados en PLACSP
    * ``placsp_1044`` — plataformas autonómicas agregadas

    Si ``feed_url`` apunta a una sindicación concreta (o a una URL propia),
    solo se consume esa fuente. ``PRIMARY_FEED_URL`` (histórico, suele 404)
    se trata como “usar sindicaciones oficiales”.

    Args:
        feed_url: URL del feed ATOM. ``None`` / principal → sindicaciones 643+1044.
        max_pages: nº máximo de páginas del feed a recorrer (paginación `rel=next`).
        max_entries: corta al nº de expedientes más recientes tras ordenar el lote.
        session: sesión `requests` reutilizable.
        extra_urls: URLs adicionales a probar (modo feed único).
        merge_syndications: fuerza fusionar 643+1044 (``None`` = auto).

    Returns:
        DataFrame con el esquema de :data:`COLUMNS` (incl. ``fuente`` y
        ``comunidad_autonoma``).

    Raises:
        IngestionError: si ninguna de las URLs candidatas devuelve entradas.
    """
    sesion = _http_session(session)
    fusionar = (
        bool(merge_syndications)
        if merge_syndications is not None
        else _es_feed_oficial_o_vacio(feed_url)
    )

    errores: list[str] = []

    if fusionar:
        # 643 y 1044 por separado; si una falla, la otra sigue.
        partes: list[pd.DataFrame] = []
        urls_ok: list[str] = []
        paginas_total = 0

        try:
            regs_643, pags_643 = _fetch_feed_registros(
                PLACSP_FEED_643,
                session=sesion,
                max_pages=max_pages,
                max_entries=max_entries,
            )
            if regs_643:
                df_643 = build_dataframe(regs_643, fuente_default=FUENTE_PLACSP_643)
                partes.append(df_643)
                urls_ok.append(PLACSP_FEED_643)
                paginas_total += pags_643
                LOGGER.info(
                    "Descargados %s expedientes desde sindicación 643 (%s páginas)",
                    len(df_643),
                    pags_643,
                )
            else:
                errores.append(f"{PLACSP_FEED_643} -> el feed no contiene entradas")
        except (requests.RequestException, IngestionError) as exc:
            errores.append(f"{PLACSP_FEED_643} -> {exc}")
            LOGGER.warning("Feed 643 no disponible: %s", exc)

        feed_1044_ok = False
        for url_1044 in PLACSP_FEEDS_1044:
            try:
                regs_1044, pags_1044 = _fetch_feed_registros(
                    url_1044,
                    session=sesion,
                    max_pages=max_pages,
                    max_entries=max_entries,
                )
                if regs_1044:
                    df_1044 = build_dataframe(regs_1044, fuente_default=FUENTE_PLACSP_1044)
                    partes.append(df_1044)
                    urls_ok.append(url_1044)
                    paginas_total += pags_1044
                    feed_1044_ok = True
                    LOGGER.info(
                        "Descargados %s expedientes desde sindicación 1044 (%s páginas)",
                        len(df_1044),
                        pags_1044,
                    )
                    break
                errores.append(f"{url_1044} -> el feed no contiene entradas")
            except (requests.RequestException, IngestionError) as exc:
                errores.append(f"{url_1044} -> {exc}")
                LOGGER.warning("Feed 1044 no disponible (%s): %s", url_1044, exc)

        if not feed_1044_ok and not any("sindicacion_1044" in e for e in errores):
            errores.append("sindicacion_1044 -> ninguna URL candidata respondió")

        if partes:
            df = pd.concat(partes, ignore_index=True, sort=False)
            for col in COLUMNS:
                if col not in df.columns:
                    if col in {"cpvs", "documentos"}:
                        df[col] = [[] for _ in range(len(df))]
                    elif col in {"presupuesto_sin_iva", "presupuesto_con_iva"}:
                        df[col] = pd.NA
                    else:
                        df[col] = ""
            df = df[list(COLUMNS)]
            df = enrich_comunidad_autonoma(df)
            if not df.empty:
                df = df.drop_duplicates(subset=["expediente", "url"], keep="first")
                df = df.sort_values(
                    "fecha_actualizacion", ascending=False, na_position="last"
                )
                df = df.reset_index(drop=True)
            if max_entries is not None and len(df) > int(max_entries):
                df = df.head(int(max_entries)).reset_index(drop=True)
            df.attrs["feed_url"] = " + ".join(urls_ok)
            df.attrs["feed_urls"] = list(urls_ok)
            df.attrs["paginas"] = paginas_total
            df.attrs["fuentes"] = sorted(
                {str(f) for f in df["fuente"].unique() if str(f).strip()}
            )
            return df

        detalle = "\n".join(f"  · {mensaje}" for mensaje in errores)
        raise IngestionError(
            "No se pudo obtener ninguna licitación de la PLACSP.\n"
            f"Sindicaciones 643/1044 probadas:\n{detalle}"
        )

    # Modo feed único (URL explícita de sindicación o personalizada).
    candidatas: list[str] = [(feed_url or PRIMARY_FEED_URL).strip()]
    if extra_urls:
        candidatas.extend(url.strip() for url in extra_urls if url)
    # Red de seguridad: si la URL custom falla, probar sindicaciones oficiales.
    candidatas.extend(FALLBACK_FEED_URLS)
    candidatas = [url for url in dict.fromkeys(candidatas) if url]

    for url in candidatas:
        try:
            registros, paginas = _fetch_feed_registros(
                url,
                session=sesion,
                max_pages=max_pages,
                max_entries=max_entries,
            )
        except (requests.RequestException, IngestionError) as exc:
            errores.append(f"{url} -> {exc}")
            LOGGER.warning("Feed no disponible (%s): %s", url, exc)
            continue

        if registros:
            fuente = fuente_desde_url_feed(url) or FUENTE_PLACSP
            LOGGER.info(
                "Descargados %s expedientes desde %s (%s páginas)",
                len(registros),
                url,
                paginas,
            )
            df = build_dataframe(registros, fuente_default=fuente)
            if max_entries is not None and len(df) > int(max_entries):
                df = df.head(int(max_entries)).reset_index(drop=True)
            df.attrs["feed_url"] = url
            df.attrs["feed_urls"] = [url]
            df.attrs["paginas"] = paginas
            df.attrs["fuentes"] = [fuente]
            return df
        errores.append(f"{url} -> el feed no contiene entradas")

    detalle = "\n".join(f"  · {mensaje}" for mensaje in errores)
    raise IngestionError(
        "No se pudo obtener ninguna licitación de la PLACSP.\n"
        f"Fuentes probadas:\n{detalle}"
    )
