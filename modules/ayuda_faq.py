"""Contenido de ayuda y FAQs para la app GREFA Licitaciones."""

from __future__ import annotations

GUIA_RAPIDA = """
### Flujo recomendado

1. **Oportunidades** — filtra CPV/términos y revisa las de alta/media relevancia.  
2. **⭐ Me interesa** — márcalas para **Mis Licitaciones**.  
3. **Análisis de pliegos** — resume PCAP/PPT con IA.  
4. **Preparar documentación** — Admin → Económico → Técnico (modelos del pliego).  
5. **Comprobador** — revisa los PDF que vas a presentar.  
6. **Revisión humana** — estados y observaciones internas.  
7. **Paquete final** — une los tres bloques y exporta Word/PDF.  
8. **Presentar** en PLACSP y marca el estado *Presentada*.
"""

SECCIONES_FAQ: list[dict[str, str]] = [
    {
        "categoria": "Primeros pasos",
        "pregunta": "¿Por dónde empiezo?",
        "respuesta": (
            "Actualiza el feed en la barra lateral, ve a **Oportunidades GREFA**, "
            "ajusta CPV/términos y pulsa Buscar. Marca con ⭐ las que te interesen."
        ),
    },
    {
        "categoria": "Primeros pasos",
        "pregunta": "¿Necesito Google Sheets / Gemini?",
        "respuesta": (
            "Para buscar en el feed y el Parquet histórico local, no. "
            "Para sync, Mis Licitaciones, checklist, Drive y análisis/preparación con IA "
            "sí hacen falta Secrets de Sheets y `[gemini] api_key`."
        ),
    },
    {
        "categoria": "Búsqueda e histórico",
        "pregunta": "¿Por qué al tocar Ámbito o presupuesto no se actualiza la lista?",
        "respuesta": (
            "Es intencional: los filtros del Buscador e Histórico solo se aplican "
            "al pulsar **Buscar**, para no recargar la app en cada cambio."
        ),
    },
    {
        "categoria": "Búsqueda e histórico",
        "pregunta": "¿De dónde sale el histórico local?",
        "respuesta": (
            "Del fichero `data/historico_grefa.parquet` (Alta/Media 2021–2026). "
            "Si falta en el servidor, hay que regenerarlo o desplegarlo con el repo."
        ),
    },
    {
        "categoria": "Búsqueda e histórico",
        "pregunta": "¿Puedo buscar por NIF de adjudicatario?",
        "respuesta": (
            "Sí, en **Histórico y NIF**: indica el NIF, elige Órgano/Adjudicatario/Ambos "
            "y pulsa Buscar. El histórico GREFA solo incluye Alta/Media."
        ),
    },
    {
        "categoria": "Pliegos e IA",
        "pregunta": "¿El resumen de pliegos sustituye leer el PCAP?",
        "respuesta": (
            "No. Es una ayuda orientativa. Siempre revisa el pliego oficial "
            "y los anexos antes de presentar."
        ),
    },
    {
        "categoria": "Pliegos e IA",
        "pregunta": "Los PDF están escaneados y falla el análisis",
        "respuesta": (
            "Gemini necesita texto seleccionable o PDFs nativos. "
            "Si están solo imagen, OCR externo o sube una versión con texto."
        ),
    },
    {
        "categoria": "Preparar documentación",
        "pregunta": "¿Qué documentos genera el asistente?",
        "respuesta": (
            "Borradores basados en los **modelos/anexos del PCAP/PPT**, "
            "rellenando variables del formulario. No inventa anexos distintos al pliego."
        ),
    },
    {
        "categoria": "Preparar documentación",
        "pregunta": "¿Cómo uso los anexos campo a campo?",
        "respuesta": (
            "En el paso 1, tras extraer exigencias, pulsa "
            "**Detectar anexos numerados**. En el formulario aparecerán los campos "
            "de cada Anexo I, II… del pliego."
        ),
    },
    {
        "categoria": "Preparar documentación",
        "pregunta": "¿Para qué sirve el perfil GREFA?",
        "respuesta": (
            "Guarda NIF, representante, poderes, etc. "
            "Con **Aplicar perfil GREFA** rellena los huecos vacíos del formulario."
        ),
    },
    {
        "categoria": "Preparar documentación",
        "pregunta": "¿Cómo exporto a Word o PDF?",
        "respuesta": (
            "Tras generar el borrador (o el paquete final), usa los botones "
            "**Word (.docx)** / **PDF**. El formato intenta respetar fuente y márgenes "
            "detectados en el pliego."
        ),
    },
    {
        "categoria": "Preparar documentación",
        "pregunta": "¿Se guardan versiones de los borradores?",
        "respuesta": (
            "Sí. Cada vez que guardas un borrador se añade una versión "
            "(máx. 25). Puedes verlas y restaurarlas en el historial del paso 3."
        ),
    },
    {
        "categoria": "Preparar documentación",
        "pregunta": "¿La revisión humana es un visto bueno jurídico?",
        "respuesta": (
            "No. Son estados y observaciones internas del equipo "
            "(Borrador, En revisión, Aprobado interno, etc.). "
            "Un VB jurídico lo da un profesional competente."
        ),
    },
    {
        "categoria": "Comprobador",
        "pregunta": "¿Qué comprueba el Comprobador de documentos?",
        "respuesta": (
            "Si **los PDF que subes se adaptan** a las **cláusulas administrativas "
            "(PCAP/PCP)** y a las **prescripciones técnicas (PPT)**. "
            "Aunque no sea el paquete completo, lo que falta del lote va en una "
            "sección informativa y **no** fuerza un «no conforme». "
            "Es una ayuda, no una validación oficial."
        ),
    },
    {
        "categoria": "Comprobador",
        "pregunta": "Si subo 4 documentos de 16, ¿saldrá siempre incompleto?",
        "respuesta": (
            "No debería: el veredicto es ✅/⚠️/❌ **conforme** con lo subido "
            "frente a administrativas y técnicas. "
            "La cobertura del resto del paquete se lista aparte. "
            "Adjunta idealmente PCAP + PPT (y ficha PLACSP si quieres; hasta 3)."
        ),
    },
    {
        "categoria": "Mis Licitaciones y plazos",
        "pregunta": "¿Cómo vinculo un expediente al asistente?",
        "respuesta": (
            "Desde Oportunidades, resultados o **Mis Licitaciones**, "
            "pulsa **Preparar docs / Preparar documentación**."
        ),
    },
    {
        "categoria": "Mis Licitaciones y plazos",
        "pregunta": "¿Cómo funcionan las alertas de plazo?",
        "respuesta": (
            "En **Revisión humana** indica la fecha límite (YYYY-MM-DD). "
            "La app avisa de plazos en 14 días o vencidos al abrir Preparar documentación."
        ),
    },
    {
        "categoria": "Problemas frecuentes",
        "pregunta": "Veo errores 429 de Google Sheets",
        "respuesta": (
            "Cuota de la API agotada. Espera 1–2 minutos y reintenta. "
            "Evita abrir muchas pestañas que lean Sheets a la vez; "
            "usa el Parquet local para búsquedas históricas."
        ),
    },
    {
        "categoria": "Problemas frecuentes",
        "pregunta": "El menú o una sección no carga datos",
        "respuesta": (
            "Recarga la app. Comprueba Secrets (Sheets/Gemini). "
            "En Histórico, confirma que existe `historico_grefa.parquet` en el Space."
        ),
    },
    {
        "categoria": "Problemas frecuentes",
        "pregunta": "¿Los datos de formularios se pierden al cerrar?",
        "respuesta": (
            "Si solo están de sesión, sí. Usa **Guardar formulario / borrador** "
            "para persistir en local y, si hay configuración, en Sheets/Drive."
        ),
    },
]


def categorias() -> list[str]:
    vistas: list[str] = []
    for item in SECCIONES_FAQ:
        cat = item["categoria"]
        if cat not in vistas:
            vistas.append(cat)
    return vistas


def faqs_por_categoria(categoria: str | None = None) -> list[dict[str, str]]:
    if not categoria or categoria == "Todas":
        return list(SECCIONES_FAQ)
    return [f for f in SECCIONES_FAQ if f["categoria"] == categoria]


def buscar_faqs(texto: str) -> list[dict[str, str]]:
    q = (texto or "").strip().casefold()
    if not q:
        return list(SECCIONES_FAQ)
    salida = []
    for item in SECCIONES_FAQ:
        blob = f"{item['pregunta']} {item['respuesta']} {item['categoria']}".casefold()
        if q in blob:
            salida.append(item)
    return salida
