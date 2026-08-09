"""Contenido de ayuda y FAQs para la app GREFA Licitaciones."""

from __future__ import annotations

GUIA_RAPIDA = """
### Flujo recomendado

**Licitaciones (PLACSP)**  
1. **Oportunidades / Buscador** — filtra y revisa expedientes.  
2. **⭐ A Mis Licitaciones** — guarda las que te interesen.  
3. **Preparar documentación** — en **cada campo** del formulario puedes escribir **o** subir un archivo (📎 Anexo V, DNI, escrituras…) y **Comprobar conformidad**.  
4. **Guardar sesión** — borrador recuperable en cualquier momento.  
5. **Comprobador** — lotes de docs + **Analizar al completo**.  
6. **Presentar** en PLACSP y marca *Presentada*.

**Ayudas y premios (BDNS)**  
1. Entra al modo **Ayudas y premios** desde el hub.  
2. Actualiza datos BDNS y revisa **Oportunidades GREFA**.  
3. Guarda con **⭐ A Mis Convocatorias** y envía a Sheets.  
4. Gestiona el estado en **Seguimiento**.
"""

SECCIONES_FAQ: list[dict[str, str]] = [
    {
        "categoria": "Primeros pasos",
        "pregunta": "¿Por dónde empiezo?",
        "respuesta": (
            "Al entrar elige **Licitaciones** o **Ayudas y premios**. "
            "En licitaciones: actualiza el feed, ve a **Oportunidades GREFA**, "
            "ajusta CPV/términos y usa **⭐ A Mis Licitaciones**. "
            "En ayudas: actualiza BDNS y guarda en **Mis Convocatorias**."
        ),
    },
    {
        "categoria": "Primeros pasos",
        "pregunta": "¿Qué diferencia hay entre Licitaciones y Ayudas/premios?",
        "respuesta": (
            "**Licitaciones** vienen de la PLACSP (contratos públicos). "
            "**Ayudas y premios** vienen de la BDNS (infosubvenciones.es): "
            "subvenciones, premios y otras ayudas públicas. "
            "Los premios privados de fundaciones que no publican en BDNS no aparecen."
        ),
    },
    {
        "categoria": "Primeros pasos",
        "pregunta": "¿Necesito Google Sheets / Gemini?",
        "respuesta": (
            "Para buscar en el feed y el Parquet histórico local, no. "
            "Para sync, Mis Licitaciones/Convocatorias, checklist, Drive, resúmenes IA, "
            "preparación y comprobador sí hacen falta Secrets de Sheets y `[gemini] api_key`."
        ),
    },
    {
        "categoria": "Ayudas y premios",
        "pregunta": "¿De dónde salen las convocatorias de ayudas?",
        "respuesta": (
            "De la API pública de la **BDNS** (Base de Datos Nacional de Subvenciones). "
            "Se buscan términos GREFA (biodiversidad, fauna, etc.) y se enriquecen "
            "con el detalle oficial (presupuesto, fechas, documentos)."
        ),
    },
    {
        "categoria": "Ayudas y premios",
        "pregunta": "¿Cómo se puntúa una ayuda o premio?",
        "respuesta": (
            "Con el mismo catálogo de términos GREFA que las licitaciones, pero **sin CPV** "
            "(las subvenciones no usan códigos CPV). Las palabras clave pesan hasta el 100 % "
            "del Índice de Relevancia."
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
        "categoria": "Búsqueda e histórico",
        "pregunta": "¿Cómo añado una licitación del buscador a Mis Licitaciones?",
        "respuesta": (
            "En cada registro del **Buscador general** (e Histórico) tienes "
            "**⭐ A Mis Licitaciones** junto a **📝 Preparar docs**. "
            "Si ya está añadida, el botón indica *Ya en Mis Licitaciones* y permite quitarla."
        ),
    },
    {
        "categoria": "Pliegos e IA",
        "pregunta": "¿Qué formatos acepta el resumen / la IA?",
        "respuesta": (
            "**PDF, Word (.docx) y Excel (.xlsx)**. "
            "Los `.doc` / `.xls` antiguos hay que guardarlos como .docx / .xlsx."
        ),
    },
    {
        "categoria": "Pliegos e IA",
        "pregunta": "¿El resumen de pliegos se guarda solo?",
        "respuesta": (
            "No: al generarlo queda solo en pantalla. Pulsa **Guardar resumen** "
            "para conservarlo (Sheets + copia en Drive con nombre "
            "`contratista_expediente.md`). **Borrar** lo quita de pantalla y de memoria "
            "(también de Sheets si estaba guardado)."
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
            "Si están solo imagen, OCR externo o sube una versión con texto. "
            "Word/Excel con texto también sirven."
        ),
    },
    {
        "categoria": "Preparar documentación",
        "pregunta": "¿Qué documentos genera el asistente?",
        "respuesta": (
            "Borradores basados en los **modelos/anexos del PCAP/PPT**, "
            "rellenando variables del formulario y/o documentos aportados. "
            "No inventa anexos distintos al pliego."
        ),
    },
    {
        "categoria": "Preparar documentación",
        "pregunta": "¿Puedo subir un archivo en un campo (Anexo V, DNI, escrituras…)?",
        "respuesta": (
            "Sí. En **cada campo** del formulario (incluidos anexos) hay un desplegable "
            "**📎 Archivo para este campo**. Puedes escribir texto **o** subir un "
            "PDF / Word / Excel (p. ej. DNI, escrituras, Anexo V relleno)."
        ),
    },
    {
        "categoria": "Preparar documentación",
        "pregunta": "¿Cómo compruebo que el archivo de un campo es válido?",
        "respuesta": (
            "Dentro del desplegable 📎 del propio campo, pulsa "
            "**🔎 Comprobar conformidad**. La IA indica si es ✅ válido, ⚠️ con reservas "
            "o ❌ no corresponde a **ese** campo frente al pliego."
        ),
    },
    {
        "categoria": "Preparar documentación",
        "pregunta": "¿Cómo funciona el borrador recuperable / guardar sesión?",
        "respuesta": (
            "Arriba del asistente: **💾 Guardar sesión ahora** actualiza el borrador "
            "completo (formulario, docs aportados, exigencias, borrador generado) "
            "y añade una **sesión** al historial. "
            "**📂 Recuperar último borrador** restaura el estado actual; "
            "en el historial puedes **Restaurar** cualquier sesión anterior. "
            "También se autoguarda al extraer exigencias del pliego."
        ),
    },
    {
        "categoria": "Preparar documentación",
        "pregunta": "¿Se pierden los datos al cerrar la app?",
        "respuesta": (
            "Solo lo que no hayas guardado. Tras **Guardar sesión / formulario / borrador**, "
            "puedes recuperarlo en otra visita con el mismo expediente y bloque "
            "(local + Sheets/Drive si están configurados)."
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
        "pregunta": "¿Se guardan versiones del texto del borrador?",
        "respuesta": (
            "Sí: además de las **sesiones** completas, el texto del borrador "
            "tiene historial de versiones en el paso 3 (ver / restaurar)."
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
            "Si **los documentos que subes se adaptan** a las **cláusulas administrativas "
            "(PCAP/PCP)** y a las **prescripciones técnicas (PPT)**. "
            "Acepta **PDF, Word (.docx) y Excel (.xlsx)**. "
            "El veredicto es de **conformidad de lo subido**, no de completitud del paquete. "
            "Es una ayuda, no una validación oficial."
        ),
    },
    {
        "categoria": "Comprobador",
        "pregunta": "¿Cómo trabajo si tengo más de 4 documentos?",
        "respuesta": (
            "Analiza por **lotes de hasta 4**: **Analizar lote** → informe parcial → "
            "**➕ Subir más documentos** → otro lote. "
            "Cuando termines, **📊 Analizar al completo** unifica todos los parciales "
            "en un informe global. El PCAP/PPT de referencia se reutiliza en cada lote."
        ),
    },
    {
        "categoria": "Comprobador",
        "pregunta": "Si subo 4 documentos de 16, ¿saldrá siempre incompleto?",
        "respuesta": (
            "No: el parcial mide conformidad de ese lote. "
            "Lo que falta del paquete se lista aparte (informativo). "
            "El informe global sale al pulsar **Analizar al completo**."
        ),
    },
    {
        "categoria": "Mis Licitaciones y plazos",
        "pregunta": "¿Cómo vinculo un expediente al asistente?",
        "respuesta": (
            "Desde Oportunidades, Buscador, Histórico o **Mis Licitaciones**, "
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
            "Si no has guardado, sí. Usa **Guardar sesión ahora** "
            "(o guardar formulario / borrador) y luego **Recuperar último borrador**."
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
