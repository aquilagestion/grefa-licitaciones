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

PROMPT_COMPROBADOR = """Eres un revisor de ofertas para licitaciones públicas españolas
(PLACSP), trabajando para GREFA (Grupo para la Recuperación de la Fauna Autóctona).

Te pasan:
1) Documento(s) que GREFA quiere **presentar** (oferta, memoria, DECLAREs, anexos…).
2) Opcionalmente, el/los **pliego(s)** o requisitos de referencia (PCAP/PPT u otros).
3) Opcionalmente, una lista de requisitos / checklist.

Tu tarea: comprobar si la documentación de oferta parece **válida para presentar**
o qué le falta / qué errores tiene. No inventes datos que no estén en los ficheros.
Si no hay pliego de referencia, evalúa coherencia formal interna y marca limitaciones.

Responde en **español**, con markdown y estas secciones exactas:

## Veredicto
Una sola línea al inicio con UNA de estas etiquetas:
- `✅ APTO PARA PRESENTAR` — si no ves defectos bloqueantes evidentes
- `⚠️ PRESENTABLE CON RESERVAS` — si hay huecos o riesgos pero no es claramente inválido
- `❌ NO APTO / INCOMPLETO` — si faltan piezas críticas o hay errores graves

Luego 2–4 frases justificando el veredicto.

## Errores y defectos detectados
Lista numerada. Cada ítem: gravedad (`Bloqueante` / `Importante` / `Menor`),
qué está mal y dónde (documento / sección si se ve). Si no hay, escribe «Ninguno evidente».

## Documentación o contenido que falta
Lista de lo que debería aportarse o completarse (según pliego/checklist o buenas
prácticas de licitación pública). Si no puedes deducirlo, dilo.

## Inconsistencias y riesgos
Fechas, importes, NIF, firmas, sobres, referencias cruzadas, requisitos de
solvencia no acreditados, formatos, etc.

## Checklist rápido antes de presentar
5–10 casillas accionables (`[ ] …`) priorizadas.

## Limitaciones de este análisis
Qué no has podido verificar (escaneos, firmas digitales, DEH, registro, etc.).

Sé concreto y accionable. No recomiendes presentar si hay defectos bloqueantes claros."""


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


def _generar_con_gemini(
    contenido: list[Any],
    *,
    contexto: str = "",
    prompt_base: str | None = None,
) -> str:
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

    base = prompt_base or PROMPT_PLIEGO
    prompt = base
    if contexto:
        prompt = f"{base}\n\nContexto del expediente:\n{contexto}"

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


def _validar_pdfs(documentos: list[dict[str, Any]], *, etiqueta: str) -> list[dict[str, Any]]:
    utiles = [
        d
        for d in documentos
        if isinstance(d, dict) and d.get("bytes") and len(d.get("bytes") or b"") > 0
    ]
    if not utiles:
        raise PdfSummaryError(f"No hay PDFs válidos en {etiqueta}.")
    for doc in utiles:
        if len(doc["bytes"]) > MAX_PDF_BYTES:
            raise PdfSummaryError(
                f"{doc.get('nombre', 'PDF')} supera {MAX_PDF_BYTES // (1024 * 1024)} MB."
            )
    return utiles


def _partes_gemini_pdfs(documentos: list[dict[str, Any]], *, max_docs: int = 4) -> list[Any]:
    partes: list[Any] = []
    for doc in documentos[:max_docs]:
        etiqueta = f"[{doc.get('tipo', 'OTRO')}] {doc.get('nombre', 'documento.pdf')}"
        partes.append(etiqueta)
        partes.append({"mime_type": "application/pdf", "data": doc["bytes"]})
    return partes


def _texto_desde_pdfs(documentos: list[dict[str, Any]]) -> str:
    bloques: list[str] = []
    for doc in documentos:
        texto = _extraer_texto_pdf(doc["bytes"])
        if texto.strip():
            bloques.append(
                f"### {doc.get('tipo', 'OTRO')} — {doc.get('nombre', 'documento.pdf')}\n{texto}"
            )
    return "\n\n".join(bloques)[:MAX_TEXTO_EXTRAIDO]


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
    utiles = _validar_pdfs(documentos, etiqueta="pliegos")

    contexto_parts = []
    if expediente or titulo:
        contexto_parts.append(f"Expediente: {expediente or '—'}\nTítulo: {titulo or '—'}")
    listado = ", ".join(
        f"{d.get('tipo', 'OTRO')}: {d.get('nombre', 'documento.pdf')}" for d in utiles
    )
    contexto_parts.append(f"Documentos analizados: {listado}")
    contexto = "\n".join(contexto_parts)

    try:
        return _generar_con_gemini(
            _partes_gemini_pdfs(utiles),
            contexto=contexto,
            prompt_base=PROMPT_PLIEGO,
        )
    except PdfSummaryError as exc:
        LOGGER.info("PDF multi directo falló (%s); se intenta texto.", exc)

    combinado = _texto_desde_pdfs(utiles)
    if len(combinado.strip()) < 200:
        raise PdfSummaryError(
            "Los PDF parecen escaneados o sin texto seleccionable. "
            "Sube PDFs con texto o nativos digitales."
        )

    prompt = PROMPT_TEXTO.format(texto=combinado)
    if contexto:
        prompt = f"{contexto}\n\n{prompt}"
    return _generar_con_gemini([prompt], prompt_base=PROMPT_PLIEGO)


def comprobar_documentos(
    documentos_oferta: list[dict[str, Any]],
    *,
    documentos_pliego: list[dict[str, Any]] | None = None,
    expediente: str = "",
    titulo: str = "",
    requisitos_texto: str = "",
) -> str:
    """Revisa si la documentación de oferta parece válida para presentar."""
    oferta = _validar_pdfs(documentos_oferta, etiqueta="documentos de oferta")
    pliegos = []
    if documentos_pliego:
        try:
            pliegos = _validar_pdfs(documentos_pliego, etiqueta="pliegos de referencia")
        except PdfSummaryError:
            pliegos = []

    contexto_parts = [
        "Modo: COMPROBADOR DE DOCUMENTACIÓN A PRESENTAR.",
        f"Expediente: {expediente or '—'}",
        f"Título / referencia: {titulo or '—'}",
        "Documentos de OFERTA (a presentar): "
        + ", ".join(
            f"{d.get('tipo', 'OFERTA')}: {d.get('nombre', 'documento.pdf')}" for d in oferta
        ),
    ]
    if pliegos:
        contexto_parts.append(
            "Documentos de PLIEGO / requisitos (referencia): "
            + ", ".join(
                f"{d.get('tipo', 'PLIEGO')}: {d.get('nombre', 'documento.pdf')}"
                for d in pliegos
            )
        )
    else:
        contexto_parts.append(
            "No se adjuntó pliego de referencia: evalúa solo formalidad interna "
            "y señala limitaciones."
        )
    if requisitos_texto and requisitos_texto.strip():
        contexto_parts.append(
            "Checklist / requisitos adicionales indicados por el usuario:\n"
            + requisitos_texto.strip()[:8000]
        )
    contexto = "\n".join(contexto_parts)

    # Primero oferta (prioridad), luego pliego; tope ~6 PDFs en total.
    docs_envio = [
        {**d, "tipo": d.get("tipo") or "OFERTA"} for d in oferta[:4]
    ] + [
        {**d, "tipo": d.get("tipo") or "PLIEGO"} for d in pliegos[:2]
    ]

    try:
        partes: list[Any] = ["=== DOCUMENTACIÓN A REVISAR ==="]
        partes.extend(_partes_gemini_pdfs(docs_envio, max_docs=6))
        return _generar_con_gemini(
            partes,
            contexto=contexto,
            prompt_base=PROMPT_COMPROBADOR,
        )
    except PdfSummaryError as exc:
        LOGGER.info("Comprobador PDF directo falló (%s); se intenta texto.", exc)

    bloques = ["=== OFERTA ===", _texto_desde_pdfs(oferta)]
    if pliegos:
        bloques.extend(["=== PLIEGO / REQUISITOS ===", _texto_desde_pdfs(pliegos)])
    combinado = "\n\n".join(b for b in bloques if b).strip()[:MAX_TEXTO_EXTRAIDO]
    if len(combinado) < 200:
        raise PdfSummaryError(
            "Los PDF parecen escaneados o sin texto seleccionable. "
            "Sube PDFs con texto o nativos digitales."
        )

    return _generar_con_gemini(
        [f"Extracto de documentos:\n---\n{combinado}\n---"],
        contexto=contexto,
        prompt_base=PROMPT_COMPROBADOR,
    )
