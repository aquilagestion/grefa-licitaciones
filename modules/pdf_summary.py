"""Resumen de pliegos PDF con Gemini (tier gratuito de Google AI Studio)."""

from __future__ import annotations

import logging
import os
from typing import Any

from modules.sheets_store import _secret

LOGGER = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-flash-latest"
MAX_PDF_BYTES = 15 * 1024 * 1024  # ~15 MB
MAX_TEXTO_EXTRAIDO = 120_000

PROMPT_PLIEGO = """Eres un analista de licitaciones públicas para el equipo GREFA
(Grupo para la Recuperación de la Fauna Autóctona).

Analiza el/los pliego(s) adjunto(s). Puede haber varios documentos (p. ej. PCAP =
Pliego de Cláusulas Administrativas Particulares y PPT = Pliego de Prescripciones
Técnicas). Intégralos en un único resumen en **español**, claro y accionable,
con estas secciones (usa títulos markdown):

## Objeto del contrato
## Presupuesto e importes (si constan)
## Requisitos de solvencia y clasificación (sobre todo PCAP)
## Criterios de adjudicación
## Alcance técnico / prestaciones (sobre todo PPT)
## Plazos clave (presentación, ejecución, garantías)
## Documentación a presentar
## Puntos de atención para GREFA
## Recomendación breve (Presentar / Estudiar / Descartar) y por qué

Si algún dato no aparece en los documentos, indícalo como «No consta».
Sé conciso pero no omitas requisitos eliminatorios. Indica de qué documento
sale cada dato clave cuando haya varios."""

PROMPT_TEXTO = """Eres un analista de licitaciones públicas para GREFA.
Resume el siguiente extracto de pliego(s) en español con las mismas secciones que
un pliego completo (objeto, solvencia, criterios, alcance técnico, plazos,
documentación, atención GREFA, recomendación). Si falta información, indica «No consta».

---
{texto}
"""


class PdfSummaryError(RuntimeError):
    """Error al procesar o resumir un PDF."""


def api_key() -> str | None:
    clave = _secret("gemini", "api_key") or os.environ.get("GREFA_GEMINI_API_KEY")
    return str(clave).strip() if clave else None


def model_name() -> str:
    return str(_secret("gemini", "model") or os.environ.get("GREFA_GEMINI_MODEL") or DEFAULT_MODEL)


def is_configured() -> bool:
    return bool(api_key())


def _extraer_texto_pdf(pdf_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader
        from io import BytesIO

        lector = PdfReader(BytesIO(pdf_bytes))
        partes: list[str] = []
        for pagina in lector.pages:
            texto = pagina.extract_text() or ""
            if texto.strip():
                partes.append(texto.strip())
            if sum(len(p) for p in partes) >= MAX_TEXTO_EXTRAIDO:
                break
        return "\n\n".join(partes)[:MAX_TEXTO_EXTRAIDO]
    except Exception as exc:
        raise PdfSummaryError(f"No se pudo leer el PDF: {exc}") from exc


def _generar_con_gemini(contenido: list[Any], *, contexto: str = "") -> str:
    clave = api_key()
    if not clave:
        raise PdfSummaryError(
            "Gemini no configurado. Añade [gemini] api_key en secrets.toml "
            "o la variable GREFA_GEMINI_API_KEY."
        )

    try:
        import google.generativeai as genai
    except ImportError as exc:
        raise PdfSummaryError("Falta el paquete google-generativeai.") from exc

    genai.configure(api_key=clave)
    modelo = genai.GenerativeModel(model_name())

    prompt = PROMPT_PLIEGO
    if contexto:
        prompt = f"{PROMPT_PLIEGO}\n\nContexto del expediente:\n{contexto}"

    try:
        respuesta = modelo.generate_content([*contenido, prompt])
        texto = (respuesta.text or "").strip()
        if not texto:
            raise PdfSummaryError("Gemini no devolvió texto. Prueba con otro PDF o modelo.")
        return texto
    except PdfSummaryError:
        raise
    except Exception as exc:
        raise PdfSummaryError(f"Error al llamar a Gemini: {exc}") from exc


def summarize_pdf(
    pdf_bytes: bytes,
    *,
    expediente: str = "",
    titulo: str = "",
) -> str:
    """Resume un pliego PDF. Intenta enviar el PDF a Gemini; si falla, extrae texto."""
    return summarize_documentos(
        [{"nombre": "pliego.pdf", "tipo": "OTRO", "bytes": pdf_bytes}],
        expediente=expediente,
        titulo=titulo,
    )


def summarize_documentos(
    documentos: list[dict[str, Any]],
    *,
    expediente: str = "",
    titulo: str = "",
) -> str:
    """Resume uno o varios PDFs (p. ej. PCAP + PPT) en un único informe."""
    utiles = [
        d
        for d in documentos
        if isinstance(d, dict) and d.get("bytes") and len(d.get("bytes") or b"") > 0
    ]
    if not utiles:
        raise PdfSummaryError("No hay PDFs válidos para analizar.")

    for doc in utiles:
        datos = doc["bytes"]
        if len(datos) > MAX_PDF_BYTES:
            raise PdfSummaryError(
                f"{doc.get('nombre', 'PDF')} supera "
                f"{MAX_PDF_BYTES // (1024 * 1024)} MB."
            )

    contexto_parts = []
    if expediente or titulo:
        contexto_parts.append(f"Expediente: {expediente or '—'}\nTítulo: {titulo or '—'}")
    listado = ", ".join(
        f"{d.get('tipo', 'OTRO')}: {d.get('nombre', 'documento.pdf')}" for d in utiles
    )
    contexto_parts.append(f"Documentos analizados: {listado}")
    contexto = "\n".join(contexto_parts)

    # Gemini admite varios PDF en el mismo prompt.
    try:
        partes: list[Any] = []
        for doc in utiles[:4]:
            etiqueta = f"[{doc.get('tipo', 'OTRO')}] {doc.get('nombre', 'documento.pdf')}"
            partes.append(etiqueta)
            partes.append({"mime_type": "application/pdf", "data": doc["bytes"]})
        return _generar_con_gemini(partes, contexto=contexto)
    except PdfSummaryError as exc:
        LOGGER.info("PDF multi directo falló (%s); se intenta texto.", exc)

    bloques: list[str] = []
    for doc in utiles:
        texto = _extraer_texto_pdf(doc["bytes"])
        if texto.strip():
            bloques.append(
                f"### {doc.get('tipo', 'OTRO')} — {doc.get('nombre', 'documento.pdf')}\n{texto}"
            )
    combinado = "\n\n".join(bloques)[:MAX_TEXTO_EXTRAIDO]
    if len(combinado.strip()) < 200:
        raise PdfSummaryError(
            "Los PDF parecen escaneados o sin texto seleccionable. "
            "Sube PDFs con texto o nativos digitales."
        )

    prompt = PROMPT_TEXTO.format(texto=combinado)
    if contexto:
        prompt = f"{contexto}\n\n{prompt}"
    return _generar_con_gemini([prompt])
