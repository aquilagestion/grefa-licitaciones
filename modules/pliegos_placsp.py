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
    # Evitar falsos positivos: «Acta administrativa» no es el PCAP.
    if any(
        x in blob
        for x in (
            "clausulasadministrativas",
            "cláusulas administrativas",
            "clausulas administrativas",
            "pliegodeclausulas",
            "pliego de clausulas",
            "pliego de cláusulas",
            "condiciones particulares",
            "pcap",
            "legaldocument",
        )
    ):
        return "PCAP"
    if any(
        x in blob
        for x in (
            "prescripcionestecnicas",
            "prescripciones técnicas",
            "prescripciones tecnicas",
            "pliegodeprescripciones",
            "pliego de prescripciones",
            "ppt",
            "technicaldocument",
        )
    ):
        return "PPT"
    if "anexo" in blob or "memoria" in blob:
        return "ANEXO"
    if blob.strip() in {"pliego", "pliego.pdf", "documento de pliegos", "documento de pliegos.pdf"}:
        return "PLIEGO"
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


def extract_document_uris_from_pdf(pdf_bytes: bytes) -> list[str]:
    """URIs GetDocumentById embebidas como hipervínculos en un PDF (índice de pliegos)."""
    if not pdf_bytes or not pdf_bytes.startswith(b"%PDF"):
        return []
    try:
        from io import BytesIO

        from pypdf import PdfReader
    except ImportError:
        return []

    uris: list[str] = []
    try:
        lector = PdfReader(BytesIO(pdf_bytes))
        for pagina in lector.pages:
            anotaciones = pagina.get("/Annots")
            if not anotaciones:
                continue
            for anot in anotaciones:
                try:
                    obj = anot.get_object()
                except Exception:
                    continue
                if obj.get("/Subtype") != "/Link":
                    continue
                accion = obj.get("/A")
                if accion is None:
                    continue
                try:
                    accion = accion.get_object()
                except Exception:
                    pass
                uri = str(accion.get("/URI") or "").strip()
                if "GetDocumentByIdServlet" in uri:
                    uris.append(_absolutizar(uri))
    except Exception as exc:
        LOGGER.warning("No se pudieron leer enlaces del PDF índice: %s", exc)
        return []

    # Deduplicar preservando orden
    vistos: set[str] = set()
    out: list[str] = []
    for uri in uris:
        if uri in vistos:
            continue
        vistos.add(uri)
        out.append(uri)
    return out


def expandir_pliegos_desde_indice(
    documentos: list[dict[str, str]],
    *,
    session: requests.Session | None = None,
    max_indices: int = 2,
) -> list[dict[str, str]]:
    """Si solo hay el PDF «Pliego» (índice), descarga PCAP/PPT enlazados dentro.

    En muchas licitaciones (p. ej. ADIF) la ficha solo muestra «Pliego» y dentro
    del PDF están los hipervínculos a PliegoDeClausulasAdministrativas y
    PliegoDePrescripcionesTecnicas.
    """
    base = [dict(d) for d in documentos if d.get("url")]

    def _pcap_ppt_real(d: dict[str, str]) -> bool:
        if d.get("origen") == "indice_pliego" and d.get("tipo") in {"PCAP", "PPT"}:
            return True
        n = f"{d.get('nombre', '')} {d.get('etiqueta', '')}".lower()
        return any(
            x in n
            for x in (
                "clausulasadministrativas",
                "clausulas administrativas",
                "cláusulas administrativas",
                "prescripcionestecnicas",
                "prescripciones tecnicas",
                "prescripciones técnicas",
                "condiciones particulares",
            )
        )

    if any(_pcap_ppt_real(d) for d in base if d.get("tipo") == "PCAP") and any(
        _pcap_ppt_real(d) for d in base if d.get("tipo") == "PPT"
    ):
        return base

    candidatos = [
        d
        for d in base
        if d.get("tipo") == "PLIEGO"
        or str(d.get("etiqueta", "")).strip().lower() == "pliego"
        or str(d.get("nombre", "")).strip().lower() in {"pliego", "pliego.pdf"}
    ]
    if not candidatos:
        return base

    sesion = session or requests.Session()
    sesion.headers.setdefault("User-Agent", USER_AGENT)
    vistos = {d["url"] for d in base}
    añadidos = 0

    for indice in candidatos[:max_indices]:
        try:
            pdf, nombre_cd = download_pdf(indice["url"], session=sesion)
        except Exception as exc:
            LOGGER.warning("No se pudo descargar índice %s: %s", indice.get("nombre"), exc)
            continue
        if nombre_cd:
            indice["nombre"] = nombre_cd
            tip = _clasificar(nombre_cd)
            if tip in {"PCAP", "PPT"}:
                indice["tipo"] = tip
        uris = extract_document_uris_from_pdf(pdf)
        for uri in uris:
            if uri in vistos:
                continue
            # Resolver nombre/tipo con HEAD/GET ligero (Content-Disposition).
            nombre = "documento.pdf"
            try:
                resp = sesion.get(uri, timeout=REQUEST_TIMEOUT, allow_redirects=True, stream=True)
                resp.raise_for_status()
                nombre = (
                    _nombre_desde_content_disposition(
                        resp.headers.get("content-disposition") or ""
                    )
                    or nombre
                )
                # Consumir poco: si es PDF pequeño lo podemos omitir aquí
                resp.close()
            except Exception:
                pass
            tipo = _clasificar(nombre)
            if tipo == "OTRO":
                # En el índice ADIF los dos GetDocument suelen ser PCAP/PPT.
                tipo = "PPT" if añadidos == 0 and "tecnic" in nombre.lower() else (
                    "PCAP" if "admin" in nombre.lower() or "clausul" in nombre.lower() else "OTRO"
                )
            if tipo not in {"PCAP", "PPT", "ANEXO"} and "GetDocument" in uri:
                # Clasificar por nombre de fichero ya resuelto
                if "prescripcion" in nombre.lower() or "tecnic" in nombre.lower():
                    tipo = "PPT"
                elif "clausul" in nombre.lower() or "admin" in nombre.lower():
                    tipo = "PCAP"
            doc = {
                "nombre": nombre,
                "url": uri,
                "tipo": tipo if tipo != "OTRO" else _clasificar(nombre),
                "origen": "indice_pliego",
                "etiqueta": indice.get("etiqueta") or "Pliego",
            }
            if doc["tipo"] == "OTRO":
                # Último recurso: orden típico PPT luego PCAP en el índice PLACSP
                doc["tipo"] = "PPT" if añadidos == 0 else "PCAP"
            base.append(doc)
            vistos.add(uri)
            añadidos += 1

    orden = {t: i for i, t in enumerate(TIPOS_PRIORIDAD)}
    base.sort(key=lambda d: (orden.get(d.get("tipo", ""), 99), d.get("nombre", "").lower()))
    return base


def fetch_documentos_desde_detalle(url: str) -> list[dict[str, str]]:
    """Lee la ficha de licitación PLACSP y extrae enlaces GetDocumentById (PDF).

    Es la misma fuente que ve el usuario en «Anuncios y Documentos» / «Pliego».
    Si el PDF «Pliego» es un índice, se expanden los enlaces internos a PCAP/PPT.
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
            # Filas «Pliego» sin más detalle → índice que enlaza PCAP/PPT.
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

    # Enlaces «Ver» de Otros Documentos
    for a in soup.find_all("a", href=True):
        href = _absolutizar(a.get("href") or "")
        if "GetDocumentByIdServlet" not in href or href in vistos:
            continue
        img = a.find("img")
        alt = ((img.get("alt") if img else "") or "").lower()
        texto_a = " ".join(a.get_text(" ", strip=True).split())
        # Incluir PDF explícitos; «Ver» sin alt también (otros documentos)
        if "html" in alt or "xml" in alt:
            continue
        if "pdf" not in alt and texto_a.lower() not in {"", "ver", "documento pdf"}:
            if ".pdf" not in href.lower() and "GetDocument" not in href:
                continue
        vistos.add(href)
        # Contexto de la fila
        etiqueta = ""
        padre = a.find_parent("tr")
        if padre is not None:
            celdas = padre.find_all(["td", "th"])
            if celdas:
                etiqueta = " ".join(celdas[0].get_text(" ", strip=True).split())
                if len(celdas) > 1 and len(etiqueta) < 3:
                    etiqueta = " ".join(celdas[1].get_text(" ", strip=True).split())
        nombre = texto_a if texto_a and texto_a.lower() not in {"ver", "documento pdf"} else (
            etiqueta or "documento.pdf"
        )
        if not nombre.lower().endswith(".pdf"):
            nombre = f"{nombre}.pdf"
        docs.append(
            {
                "nombre": nombre,
                "url": href,
                "tipo": _clasificar(f"{nombre} {etiqueta}"),
                "origen": "ficha_placsp",
                "etiqueta": etiqueta,
            }
        )

    docs = expandir_pliegos_desde_indice(docs, session=sesion)
    orden = {t: i for i, t in enumerate(TIPOS_PRIORIDAD)}
    docs.sort(key=lambda d: (orden.get(d["tipo"], 99), d["nombre"].lower()))
    return docs


def resolver_documentos(
    documentos: list[dict[str, str]] | None,
    url_detalle: str = "",
    *,
    forzar_ficha: bool = False,
) -> list[dict[str, str]]:
    """Combina feed CODICE + ficha HTML + enlaces internos del PDF «Pliego»."""
    base = [dict(d) for d in (documentos or []) if d.get("url")]
    tiene_pcap_ppt = any(d.get("tipo") in {"PCAP", "PPT"} for d in base)
    necesita_ficha = forzar_ficha or not tiene_pcap_ppt
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
    elif not tiene_pcap_ppt:
        base = expandir_pliegos_desde_indice(base)

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
    """Descarga PCAP/PPT (y Pliego índice solo si faltan) y devuelve bytes."""
    # Expandir índice por si aún no se hizo.
    documentos = expandir_pliegos_desde_indice(list(documentos or []))
    elegidos = [d for d in documentos if d.get("tipo") in solo_tipos]
    # Si ya hay PCAP o PPT, no hace falta mandar el PDF índice a Gemini.
    if any(d.get("tipo") in {"PCAP", "PPT"} for d in elegidos):
        elegidos = [d for d in elegidos if d.get("tipo") in {"PCAP", "PPT", "ANEXO"}]
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
