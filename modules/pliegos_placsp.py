"""Extracción y descarga de pliegos desde PLACSP (todas las licitaciones).

Estrategia uniforme:

1. Documentos CODICE del feed (LegalDocumentReference / TechnicalDocumentReference).
2. Ficha HTML de la licitación (fila «Pliego» + otros PDF).
3. Si el PDF/HTML «Pliego» es un índice, seguir los hipervínculos internos
   GetDocumentById hasta el PCAP y el PPT reales.
"""

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
    return element.xpath(".//*[local-name()=$n]", n=local_name)


def _find(element, local_name: str):
    encontrados = _findall(element, local_name)
    return encontrados[0] if encontrados else None


def _clasificar(nombre: str, etiqueta_xml: str = "") -> str:
    blob = f"{nombre} {etiqueta_xml}".lower()
    # PCAP / cláusulas / condiciones particulares / PCJ / PCC / PCA
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
            "pliego de condiciones particulares",
            "legaldocument",
            "pcap",
            "pcj_",
            "pcj-",
            "pcj.",
            "pcc_",
            "pcc-",
            "pcc.",
            "pca-",
            "pca_",
            "pca.",
        )
    ) or re.search(r"(?:^|[^a-z])pca(?:[^a-z]|$)", blob):
        return "PCAP"
    # PPT / prescripciones / PCT
    if any(
        x in blob
        for x in (
            "prescripcionestecnicas",
            "prescripciones técnicas",
            "prescripciones tecnicas",
            "pliegodeprescripciones",
            "pliego de prescripciones",
            "technicaldocument",
            "ppt",
            "pct_",
            "pct-",
            "pct.",
        )
    ) or re.search(r"(?:^|[^a-z])ppt(?:[^a-z]|$)", blob):
        return "PPT"
    if "anexo" in blob or "memoria" in blob:
        return "ANEXO"
    if re.search(r"\bpliego\b", blob) and not any(
        x in blob for x in ("anuncio", "adjudic", "formaliz", "acta", "resoluci")
    ):
        # «Pliego.pdf» / fila Pliego → índice, no el PCAP/PPT en sí
        if any(
            x in blob
            for x in (
                "documento de pliegos",
                "pliego.pdf",
                " pliego ",
            )
        ) or blob.strip() in {"pliego", "pliego.pdf"}:
            return "PLIEGO"
        if blob.strip().startswith("pliego") and len(blob) < 40:
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
        docs.append({"nombre": nombre, "url": url, "tipo": tipo, "origen": "codice"})

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

    for nodo in _findall(carpeta, "DocumentReference"):
        nombre = _text(_find(nodo, "ID")) or _text(_find(nodo, "FileName"))
        uri = _text(_find(nodo, "URI"))
        if uri:
            añadir(nombre, uri, _clasificar(nombre, "DocumentReference"))

    return _ordenar(docs)


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


def _ordenar(docs: list[dict[str, str]]) -> list[dict[str, str]]:
    orden = {t: i for i, t in enumerate(TIPOS_PRIORIDAD)}
    docs.sort(key=lambda d: (orden.get(d.get("tipo", ""), 99), d.get("nombre", "").lower()))
    return docs


def _tiene_tipo_real(docs: list[dict[str, str]], tipo: str) -> bool:
    for d in docs:
        if d.get("tipo") != tipo:
            continue
        # CODICE Legal/Technical son fiables aunque el nombre sea genérico
        if d.get("origen") == "codice":
            return True
        if _clasificar(d.get("nombre", ""), d.get("etiqueta", "")) == tipo:
            return True
        if d.get("origen") == "indice_pliego":
            return True
    return False


def extract_document_uris_from_pdf(pdf_bytes: bytes) -> list[str]:
    """URIs GetDocumentById embebidas como hipervínculos en un PDF índice."""
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

    vistos: set[str] = set()
    out: list[str] = []
    for uri in uris:
        if uri in vistos:
            continue
        vistos.add(uri)
        out.append(uri)
    return out


def extract_documentos_from_html(html_text: str) -> list[dict[str, str]]:
    """Enlaces GetDocumentById con texto visible (versión HTML del pliego índice)."""
    if not html_text:
        return []
    soup = BeautifulSoup(html_text, "lxml")
    docs: list[dict[str, str]] = []
    vistos: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = _absolutizar(a.get("href") or "")
        if "GetDocumentByIdServlet" not in href or href in vistos:
            continue
        nombre = " ".join(a.get_text(" ", strip=True).split()) or "documento.pdf"
        tipo = _clasificar(nombre)
        if tipo not in {"PCAP", "PPT", "ANEXO"}:
            continue
        vistos.add(href)
        if not nombre.lower().endswith(".pdf"):
            nombre = f"{nombre}.pdf"
        docs.append(
            {
                "nombre": nombre,
                "url": href,
                "tipo": tipo,
                "origen": "indice_pliego_html",
                "etiqueta": "Pliego",
            }
        )
    return docs


def _peek_nombre(url: str, session: requests.Session) -> str:
    """Obtiene el filename del Content-Disposition sin guardar el cuerpo entero."""
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True, stream=True)
        resp.raise_for_status()
        nombre = _nombre_desde_content_disposition(
            resp.headers.get("content-disposition") or ""
        )
        resp.close()
        return nombre
    except Exception:
        return ""


def expandir_pliegos_desde_indice(
    documentos: list[dict[str, str]],
    *,
    session: requests.Session | None = None,
    max_indices: int = 3,
) -> list[dict[str, str]]:
    """Para cualquier licitación: si falta PCAP o PPT, abrir el «Pliego» índice."""
    base = [dict(d) for d in documentos if d.get("url")]
    if _tiene_tipo_real(base, "PCAP") and _tiene_tipo_real(base, "PPT"):
        return base

    candidatos = [
        d
        for d in base
        if d.get("tipo") == "PLIEGO"
        or str(d.get("etiqueta", "")).strip().lower() == "pliego"
        or str(d.get("nombre", "")).strip().lower() in {"pliego", "pliego.pdf"}
        or (
            "pliego" in str(d.get("nombre", "")).lower()
            and d.get("tipo") not in {"PCAP", "PPT"}
            and "anuncio" not in str(d.get("nombre", "")).lower()
        )
    ]
    # También HTML del pliego si se guardó como url_html
    html_idxs = [d for d in base if d.get("url_html")]
    if not candidatos and not html_idxs:
        return base

    sesion = session or requests.Session()
    sesion.headers.setdefault("User-Agent", USER_AGENT)
    vistos = {d["url"] for d in base}

    def _añadir_si_pcap_ppt(uri: str, nombre_hint: str = "", etiqueta: str = "Pliego") -> None:
        nonlocal base
        if uri in vistos:
            return
        nombre = nombre_hint or _peek_nombre(uri, sesion) or "documento.pdf"
        tipo = _clasificar(nombre, etiqueta)
        if tipo not in {"PCAP", "PPT"}:
            return
        if _tiene_tipo_real(base, tipo):
            # Ya tenemos ese tipo; no duplicar basura
            return
        vistos.add(uri)
        base.append(
            {
                "nombre": nombre,
                "url": uri,
                "tipo": tipo,
                "origen": "indice_pliego",
                "etiqueta": etiqueta,
            }
        )

    for indice in candidatos[:max_indices]:
        # 1) Versión HTML del mismo documento (mejor etiquetado de enlaces)
        url_html = (indice.get("url_html") or "").strip()
        if url_html:
            try:
                rh = sesion.get(url_html, timeout=REQUEST_TIMEOUT, allow_redirects=True)
                rh.raise_for_status()
                for doc in extract_documentos_from_html(rh.text):
                    _añadir_si_pcap_ppt(doc["url"], doc.get("nombre", ""), "Pliego")
            except Exception as exc:
                LOGGER.debug("HTML índice no legible: %s", exc)

        if _tiene_tipo_real(base, "PCAP") and _tiene_tipo_real(base, "PPT"):
            break

        # 2) PDF índice con anotaciones
        try:
            pdf, nombre_cd = download_pdf(indice["url"], session=sesion)
        except Exception as exc:
            LOGGER.warning("No se pudo descargar índice %s: %s", indice.get("nombre"), exc)
            continue
        if nombre_cd:
            indice["nombre"] = nombre_cd
            tip = _clasificar(nombre_cd)
            if tip in {"PCAP", "PPT"} and not _tiene_tipo_real(base, tip):
                indice["tipo"] = tip
        for uri in extract_document_uris_from_pdf(pdf):
            _añadir_si_pcap_ppt(uri, etiqueta=indice.get("etiqueta") or "Pliego")

        if _tiene_tipo_real(base, "PCAP") and _tiene_tipo_real(base, "PPT"):
            break

    return _ordenar(base)


def _parse_tabla_documentos(soup: BeautifulSoup) -> list[dict[str, str]]:
    """Extrae PDF (y HTML asociado) de las tablas Anuncios/Documentos de la ficha."""
    docs: list[dict[str, str]] = []
    # Agrupar por fila: varios formatos (html/xml/pdf) del mismo documento
    for tr in soup.find_all("tr"):
        celdas = tr.find_all(["td", "th"])
        if not celdas:
            continue
        etiqueta_fila = ""
        if len(celdas) >= 2:
            etiqueta_fila = " ".join(celdas[1].get_text(" ", strip=True).split())
        if not etiqueta_fila:
            etiqueta_fila = " ".join(celdas[0].get_text(" ", strip=True).split())

        pdf_url = ""
        html_url = ""
        for a in tr.find_all("a", href=True):
            href = _absolutizar(a.get("href") or "")
            if "GetDocumentByIdServlet" not in href and "FileSystem" not in href:
                continue
            img = a.find("img")
            alt = ((img.get("alt") if img else "") or "").lower()
            if "html" in alt:
                html_url = href
            elif "xml" in alt:
                continue
            elif "pdf" in alt or href.lower().endswith(".pdf"):
                pdf_url = href
            elif not pdf_url and "GetDocument" in href:
                # «Ver» u otros sin icono
                texto = " ".join(a.get_text(" ", strip=True).split()).lower()
                if texto in {"", "ver", "documento pdf"} or "pdf" in texto:
                    pdf_url = href

        if not pdf_url:
            continue
        nombre = etiqueta_fila or "documento.pdf"
        if not nombre.lower().endswith(".pdf"):
            nombre = f"{nombre}.pdf"
        tipo = _clasificar(nombre, etiqueta_fila)
        if tipo == "OTRO" and etiqueta_fila.strip().lower() == "pliego":
            tipo = "PLIEGO"
        item = {
            "nombre": nombre,
            "url": pdf_url,
            "tipo": tipo,
            "origen": "ficha_placsp",
            "etiqueta": etiqueta_fila,
        }
        if html_url:
            item["url_html"] = html_url
        docs.append(item)
    return docs


def fetch_documentos_desde_detalle(url: str) -> list[dict[str, str]]:
    """Lee la ficha PLACSP de cualquier licitación y resuelve PCAP/PPT."""
    url = (url or "").strip()
    if not url.startswith("http"):
        return []

    sesion = requests.Session()
    sesion.headers.update(
        {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    )
    respuesta = sesion.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
    respuesta.raise_for_status()

    soup = BeautifulSoup(respuesta.text, "lxml")
    docs = _parse_tabla_documentos(soup)

    # Deduplicar por URL
    vistos: set[str] = set()
    unicos: list[dict[str, str]] = []
    for d in docs:
        if d["url"] in vistos:
            continue
        vistos.add(d["url"])
        unicos.append(d)

    unicos = expandir_pliegos_desde_indice(unicos, session=sesion)
    return _ordenar(unicos)


def resolver_documentos(
    documentos: list[dict[str, str]] | None,
    url_detalle: str = "",
    *,
    forzar_ficha: bool = False,
) -> list[dict[str, str]]:
    """Pipeline único para todas las licitaciones: feed → ficha → índice Pliego."""
    base = [dict(d) for d in (documentos or []) if d.get("url")]
    for d in base:
        tip = _clasificar(d.get("nombre", ""), d.get("etiqueta", ""))
        if tip in {"PCAP", "PPT", "PLIEGO"}:
            d["tipo"] = tip
        d.setdefault("origen", d.get("origen") or "feed")

    falta_pcap = not _tiene_tipo_real(base, "PCAP")
    falta_ppt = not _tiene_tipo_real(base, "PPT")
    consultar_ficha = bool(url_detalle) and (forzar_ficha or falta_pcap or falta_ppt)

    if consultar_ficha:
        try:
            from_ficha = fetch_documentos_desde_detalle(url_detalle)
        except Exception as exc:
            LOGGER.warning("No se pudo leer la ficha PLACSP: %s", exc)
            from_ficha = []
        vistos = {d["url"] for d in base}
        for doc in from_ficha:
            if doc["url"] in vistos:
                # Enriquecer con url_html si falta
                if doc.get("url_html"):
                    for b in base:
                        if b["url"] == doc["url"] and not b.get("url_html"):
                            b["url_html"] = doc["url_html"]
                continue
            tip = doc.get("tipo")
            if tip in {"PCAP", "PPT"}:
                if tip == "PCAP" and not falta_pcap:
                    continue
                if tip == "PPT" and not falta_ppt:
                    continue
                base.append(doc)
                vistos.add(doc["url"])
                if tip == "PCAP":
                    falta_pcap = False
                if tip == "PPT":
                    falta_ppt = False
            elif tip == "PLIEGO" or doc.get("url_html"):
                base.append(doc)
                vistos.add(doc["url"])

    if not _tiene_tipo_real(base, "PCAP") or not _tiene_tipo_real(base, "PPT"):
        base = expandir_pliegos_desde_indice(base)

    return _ordenar(base)


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
    url_detalle: str = "",
) -> list[dict[str, Any]]:
    """Resuelve (si hace falta) y descarga PCAP/PPT de cualquier licitación."""
    documentos = resolver_documentos(documentos, url_detalle, forzar_ficha=bool(url_detalle))
    elegidos = [d for d in documentos if d.get("tipo") in solo_tipos]
    if _tiene_tipo_real(elegidos, "PCAP") or _tiene_tipo_real(elegidos, "PPT"):
        elegidos = [d for d in elegidos if d.get("tipo") in {"PCAP", "PPT"}]
    if not elegidos:
        elegidos = [d for d in documentos if d.get("tipo") == "PLIEGO"] or list(documentos)
    elegidos = elegidos[:max_docs]

    sesion = requests.Session()
    sesion.headers.update({"User-Agent": USER_AGENT})
    descargados: list[dict[str, Any]] = []
    for doc in elegidos:
        try:
            pdf, nombre_cd = download_pdf(doc["url"], session=sesion)
            nombre = nombre_cd or doc.get("nombre") or "documento.pdf"
            tipo = _clasificar(nombre) or doc.get("tipo") or "OTRO"
            if tipo == "OTRO":
                tipo = doc.get("tipo") or "OTRO"
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
