"""Extracción y descarga de pliegos desde los documentos CODICE/PLACSP."""

from __future__ import annotations

import html
import logging
import re
from typing import Any
from urllib.parse import unquote, urljoin

import requests
from bs4 import BeautifulSoup

LOGGER = logging.getLogger(__name__)

USER_AGENT = "GREFA-Licitaciones/1.0 (analisis de pliegos)"
REQUEST_TIMEOUT = 90
MAX_PDF_BYTES = 20 * 1024 * 1024

# Prioridad para el análisis combinado.
TIPOS_PRIORIDAD = (
    "PCAP",
    "PPT",
    "PLIEGO",
    "ANEXO",
    "OTRO",
)


def _text(nodo) -> str:
    if nodo is None or nodo.text is None:
        return ""
    return " ".join(str(nodo.text).split())


def _findall(element, local_name: str) -> list:
    if element is None:
        return []
    return element.xpath(f".//*[local-name()=$n]", n=local_name)


def _find(element, local_name: str):
    encontrados = _findall(element, local_name)
    return encontrados[0] if encontrados else None


def _clasificar(nombre: str, etiqueta_xml: str = "") -> str:
    blob = f"{nombre} {etiqueta_xml}".lower()
    if any(
        x in blob
        for x in (
            "clausulasadministrativas",
            "cláusulas administrativas",
            "clausulas administrativas",
            "pcap",
            "legaldocument",
            "administrativ",
        )
    ):
        return "PCAP"
    if any(
        x in blob
        for x in (
            "prescripcionestecnicas",
            "prescripciones técnicas",
            "prescripciones tecnicas",
            "ppt",
            "technicaldocument",
            "tecnic",
        )
    ):
        return "PPT"
    if "anexo" in blob or "memoria" in blob:
        return "ANEXO"
    return "OTRO"


def extract_documentos_from_carpeta(carpeta) -> list[dict[str, str]]:
    """Lista documentos con URL descargable a partir de ContractFolderStatus."""
    if carpeta is None:
        return []

    docs: list[dict[str, str]] = []
    vistos: set[str] = set()

    def añadir(nombre: str, url: str, tipo: str) -> None:
        url = (url or "").strip()
        if not url.startswith("http") or url in vistos:
            return
        vistos.add(url)
        nombre = (nombre or "documento.pdf").strip() or "documento.pdf"
        docs.append({"nombre": nombre, "url": url, "tipo": tipo})

    for tag, tipo_fijo in (
        ("LegalDocumentReference", "PCAP"),
        ("TechnicalDocumentReference", "PPT"),
    ):
        for nodo in _findall(carpeta, tag):
            nombre = _text(_find(nodo, "ID")) or _text(_find(nodo, "FileName"))
            uri = _text(_find(nodo, "URI"))
            añadir(nombre, uri, tipo_fijo or _clasificar(nombre, tag))

    for nodo in _findall(carpeta, "GeneralDocument"):
        nombre = _text(_find(nodo, "FileName")) or _text(_find(nodo, "ID"))
        uri = _text(_find(nodo, "URI"))
        añadir(nombre, uri, _clasificar(nombre, "GeneralDocument"))

    # Otros DocumentReference genéricos con URI
    for nodo in _findall(carpeta, "DocumentReference"):
        nombre = _text(_find(nodo, "ID")) or _text(_find(nodo, "FileName"))
        uri = _text(_find(nodo, "URI"))
        if uri:
            añadir(nombre, uri, _clasificar(nombre, "DocumentReference"))

    orden = {t: i for i, t in enumerate(TIPOS_PRIORIDAD)}
    docs.sort(key=lambda d: (orden.get(d["tipo"], 99), d["nombre"].lower()))
    return docs


def _absolutizar(href: str, base: str = "https://contrataciondelestado.es") -> str:
    href = html.unescape((href or "").strip()).replace("&amp;", "&")
    if not href:
        return ""
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return urljoin(base + "/", href.lstrip("/"))
    if href.startswith("http"):
        return href
    return urljoin(base + "/", href)


def _nombre_desde_content_disposition(cabecera: str) -> str:
    if not cabecera:
        return ""
    m = re.search(r"filename\*=UTF-8''([^;]+)", cabecera, flags=re.I)
    if m:
        return unquote(m.group(1).strip().strip('"'))
    m = re.search(r'filename="?([^";]+)"?', cabecera, flags=re.I)
    if m:
        return unquote(m.group(1).strip())
    return ""


def fetch_documentos_desde_detalle(url: str) -> list[dict[str, str]]:
    """Lee la ficha de licitación PLACSP y extrae enlaces GetDocumentById (PDF).

    Es la misma fuente que ve el usuario en «Documentos» / «Pliego» de la plataforma.
    """
    url = (url or "").strip()
    if not url.startswith("http"):
        return []

    sesion = requests.Session()
    sesion.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    respuesta = sesion.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
    respuesta.raise_for_status()

    soup = BeautifulSoup(respuesta.text, "lxml")
    docs: list[dict[str, str]] = []
    vistos: set[str] = set()

    for tr in soup.find_all("tr"):
        celdas = tr.find_all(["td", "th"])
        etiqueta_fila = ""
        if len(celdas) >= 2:
            etiqueta_fila = " ".join(celdas[1].get_text(" ", strip=True).split())
        elif celdas:
            etiqueta_fila = " ".join(celdas[0].get_text(" ", strip=True).split())

        for a in tr.find_all("a", href=True):
            href = _absolutizar(a.get("href") or "")
            if "GetDocumentByIdServlet" not in href and "FileSystem" not in href:
                continue
            img = a.find("img")
            alt = ((img.get("alt") if img else "") or "").lower()
            title = (a.get("title") or "").lower()
            # Preferir PDF; descartar html/xml de la misma fila.
            if any(x in alt or x in title for x in ("html", "xml")) and "pdf" not in alt:
                continue
            if href in vistos:
                continue
            vistos.add(href)
            texto_a = " ".join(a.get_text(" ", strip=True).split())
            nombre = texto_a or etiqueta_fila or "documento.pdf"
            if not nombre.lower().endswith(".pdf"):
                nombre = f"{nombre}.pdf"
            tipo = _clasificar(f"{nombre} {etiqueta_fila}")
            # Filas «Pliego» sin más detalle → priorizar como candidato a PCAP/PPT.
            if tipo == "OTRO" and "pliego" in etiqueta_fila.lower():
                tipo = "PLIEGO"
            docs.append(
                {
                    "nombre": nombre,
                    "url": href,
                    "tipo": tipo,
                    "origen": "ficha_placsp",
                    "etiqueta": etiqueta_fila,
                }
            )

    # Enlaces sueltos fuera de tablas
    for a in soup.find_all("a", href=True):
        href = _absolutizar(a.get("href") or "")
        if "GetDocumentByIdServlet" not in href or href in vistos:
            continue
        img = a.find("img")
        alt = ((img.get("alt") if img else "") or "").lower()
        if "pdf" not in alt and ".pdf" not in href.lower():
            continue
        vistos.add(href)
        nombre = " ".join(a.get_text(" ", strip=True).split()) or "documento.pdf"
        if not nombre.lower().endswith(".pdf"):
            nombre = f"{nombre}.pdf"
        docs.append(
            {
                "nombre": nombre,
                "url": href,
                "tipo": _clasificar(nombre),
                "origen": "ficha_placsp",
                "etiqueta": "",
            }
        )

    orden = {t: i for i, t in enumerate(TIPOS_PRIORIDAD)}
    docs.sort(key=lambda d: (orden.get(d["tipo"], 99), d["nombre"].lower()))
    return docs


def resolver_documentos(
    documentos: list[dict[str, str]] | None,
    url_detalle: str = "",
    *,
    forzar_ficha: bool = False,
) -> list[dict[str, str]]:
    """Combina documentos del feed CODICE con los de la ficha HTML PLACSP."""
    base = [dict(d) for d in (documentos or []) if d.get("url")]
    necesita_ficha = forzar_ficha or not any(
        d.get("tipo") in {"PCAP", "PPT", "PLIEGO"} for d in base
    )
    if necesita_ficha and url_detalle:
        try:
            from_ficha = fetch_documentos_desde_detalle(url_detalle)
        except Exception as exc:
            LOGGER.warning("No se pudo leer la ficha PLACSP: %s", exc)
            from_ficha = []
        vistos = {d["url"] for d in base}
        for doc in from_ficha:
            if doc["url"] not in vistos:
                base.append(doc)
                vistos.add(doc["url"])
    orden = {t: i for i, t in enumerate(TIPOS_PRIORIDAD)}
    base.sort(key=lambda d: (orden.get(d.get("tipo", ""), 99), d.get("nombre", "").lower()))
    return base


def download_pdf(
    url: str, *, session: requests.Session | None = None
) -> tuple[bytes, str]:
    """Descarga un documento PLACSP y valida que sea PDF. Devuelve (bytes, nombre)."""
    sesion = session or requests.Session()
    sesion.headers.setdefault("User-Agent", USER_AGENT)
    respuesta = sesion.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
    respuesta.raise_for_status()
    datos = respuesta.content or b""
    if len(datos) > MAX_PDF_BYTES:
        raise RuntimeError(f"El documento supera {MAX_PDF_BYTES // (1024*1024)} MB.")
    ctype = (respuesta.headers.get("content-type") or "").lower()
    if not datos.startswith(b"%PDF") and "pdf" not in ctype:
        raise RuntimeError(
            "La URL no devolvió un PDF (puede requerir sesión en PLACSP o no ser público)."
        )
    nombre = _nombre_desde_content_disposition(
        respuesta.headers.get("content-disposition") or ""
    )
    return datos, nombre


def download_documentos(
    documentos: list[dict[str, str]],
    *,
    solo_tipos: tuple[str, ...] = ("PCAP", "PPT", "PLIEGO"),
    max_docs: int = 6,
) -> list[dict[str, Any]]:
    """Descarga PCAP/PPT/Pliego y devuelve [{nombre, tipo, bytes, url}]."""
    elegidos = [d for d in documentos if d.get("tipo") in solo_tipos]
    if not elegidos:
        elegidos = list(documentos)
    elegidos = elegidos[:max_docs]

    sesion = requests.Session()
    sesion.headers.update({"User-Agent": USER_AGENT})
    descargados: list[dict[str, Any]] = []
    for doc in elegidos:
        try:
            pdf, nombre_cd = download_pdf(doc["url"], session=sesion)
            nombre = nombre_cd or doc.get("nombre") or "documento.pdf"
            tipo = doc.get("tipo") or _clasificar(nombre)
            if tipo == "PLIEGO":
                tipo = _clasificar(nombre) if _clasificar(nombre) != "OTRO" else "PLIEGO"
            descargados.append(
                {
                    "nombre": nombre,
                    "tipo": tipo,
                    "url": doc.get("url") or "",
                    "bytes": pdf,
                }
            )
        except Exception as exc:
            LOGGER.warning("No se pudo descargar %s: %s", doc.get("nombre"), exc)
            descargados.append(
                {
                    "nombre": doc.get("nombre") or "documento.pdf",
                    "tipo": doc.get("tipo") or "OTRO",
                    "url": doc.get("url") or "",
                    "bytes": b"",
                    "error": str(exc),
                }
            )
    return descargados


def etiquetar_upload(nombre_fichero: str) -> str:
    return _clasificar(nombre_fichero)
