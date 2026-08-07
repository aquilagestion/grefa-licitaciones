"""Extracción y descarga de pliegos desde los documentos CODICE/PLACSP."""

from __future__ import annotations

import logging
import re
from typing import Any

import requests

LOGGER = logging.getLogger(__name__)

USER_AGENT = "GREFA-Licitaciones/1.0 (analisis de pliegos)"
REQUEST_TIMEOUT = 90
MAX_PDF_BYTES = 20 * 1024 * 1024

# Prioridad para el análisis combinado.
TIPOS_PRIORIDAD = (
    "PCAP",
    "PPT",
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


def download_pdf(url: str, *, session: requests.Session | None = None) -> bytes:
    """Descarga un documento PLACSP y valida que sea PDF."""
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
    return datos


def download_documentos(
    documentos: list[dict[str, str]],
    *,
    solo_tipos: tuple[str, ...] = ("PCAP", "PPT"),
    max_docs: int = 4,
) -> list[dict[str, Any]]:
    """Descarga PCAP/PPT (u otros) y devuelve [{nombre, tipo, bytes, url}]."""
    elegidos = [d for d in documentos if d.get("tipo") in solo_tipos]
    if not elegidos:
        elegidos = list(documentos)
    elegidos = elegidos[:max_docs]

    sesion = requests.Session()
    sesion.headers.update({"User-Agent": USER_AGENT})
    descargados: list[dict[str, Any]] = []
    for doc in elegidos:
        try:
            pdf = download_pdf(doc["url"], session=sesion)
            descargados.append(
                {
                    "nombre": doc.get("nombre") or "documento.pdf",
                    "tipo": doc.get("tipo") or "OTRO",
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
