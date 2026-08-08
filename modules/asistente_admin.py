"""Asistente de documentación (administrativa y económica) vía formulario + pliego."""

from __future__ import annotations

import json
import re
from typing import Any

from modules import pdf_summary

# ---------------------------------------------------------------------------
# Campos
# ---------------------------------------------------------------------------
CAMPOS_ADMIN: list[dict[str, Any]] = [
    {"id": "razon_social", "label": "Razón social / entidad", "grupo": "Entidad", "tipo": "text"},
    {"id": "nif", "label": "NIF / CIF", "grupo": "Entidad", "tipo": "text"},
    {"id": "domicilio_social", "label": "Domicilio social", "grupo": "Entidad", "tipo": "text"},
    {
        "id": "domicilio_notificaciones",
        "label": "Domicilio a efectos de notificaciones",
        "grupo": "Entidad",
        "tipo": "text",
    },
    {"id": "email", "label": "Email de notificaciones", "grupo": "Entidad", "tipo": "text"},
    {"id": "telefono", "label": "Teléfono", "grupo": "Entidad", "tipo": "text"},
    {
        "id": "representante_nombre",
        "label": "Representante (nombre y apellidos)",
        "grupo": "Representación",
        "tipo": "text",
    },
    {
        "id": "representante_nif",
        "label": "NIF del representante",
        "grupo": "Representación",
        "tipo": "text",
    },
    {
        "id": "representante_cargo",
        "label": "Cargo / poder de representación",
        "grupo": "Representación",
        "tipo": "text",
    },
    {"id": "expediente", "label": "ID expediente", "grupo": "Licitación", "tipo": "text"},
    {
        "id": "organo",
        "label": "Órgano de contratación",
        "grupo": "Licitación",
        "tipo": "text",
    },
    {
        "id": "objeto",
        "label": "Objeto del contrato (tal como figure)",
        "grupo": "Licitación",
        "tipo": "area",
    },
    {"id": "lote", "label": "Lote(s) a los que se presenta", "grupo": "Licitación", "tipo": "text"},
    {
        "id": "clasificacion",
        "label": "Clasificación empresarial (si aplica)",
        "grupo": "Solvencia",
        "tipo": "text",
    },
    {
        "id": "solvencia_economica",
        "label": "Solvencia económica (cómo se acredita)",
        "grupo": "Solvencia",
        "tipo": "area",
    },
    {
        "id": "solvencia_tecnica",
        "label": "Solvencia técnica / experiencia (resumen)",
        "grupo": "Solvencia",
        "tipo": "area",
    },
    {
        "id": "seguros_garantias",
        "label": "Seguros / garantías provisionales",
        "grupo": "Solvencia",
        "tipo": "area",
    },
    {
        "id": "medio_presentacion",
        "label": "Medio de presentación (PLACSP, sobre, etc.)",
        "grupo": "Presentación",
        "tipo": "text",
    },
    {
        "id": "observaciones",
        "label": "Observaciones / particularidades",
        "grupo": "Presentación",
        "tipo": "area",
    },
]

CAMPOS_ECO: list[dict[str, Any]] = [
    {"id": "razon_social", "label": "Razón social / entidad", "grupo": "Identificación", "tipo": "text"},
    {"id": "nif", "label": "NIF / CIF", "grupo": "Identificación", "tipo": "text"},
    {"id": "expediente", "label": "ID expediente", "grupo": "Identificación", "tipo": "text"},
    {
        "id": "organo",
        "label": "Órgano de contratación",
        "grupo": "Identificación",
        "tipo": "text",
    },
    {
        "id": "objeto",
        "label": "Objeto del contrato",
        "grupo": "Identificación",
        "tipo": "area",
    },
    {"id": "lote", "label": "Lote(s)", "grupo": "Identificación", "tipo": "text"},
    {
        "id": "presupuesto_base_licitacion",
        "label": "Presupuesto base de licitación (sin IVA) según pliego",
        "grupo": "Importes de referencia",
        "tipo": "text",
    },
    {
        "id": "presupuesto_base_iva",
        "label": "Presupuesto base con IVA / tipo IVA del pliego",
        "grupo": "Importes de referencia",
        "tipo": "text",
    },
    {
        "id": "valor_estimado",
        "label": "Valor estimado del contrato (si consta)",
        "grupo": "Importes de referencia",
        "tipo": "text",
    },
    {
        "id": "importe_ofertado_sin_iva",
        "label": "Importe ofertado GREFA (sin IVA)",
        "grupo": "Oferta económica",
        "tipo": "text",
    },
    {
        "id": "tipo_iva",
        "label": "Tipo de IVA aplicable (%)",
        "grupo": "Oferta económica",
        "tipo": "text",
    },
    {
        "id": "importe_ofertado_con_iva",
        "label": "Importe ofertado con IVA",
        "grupo": "Oferta económica",
        "tipo": "text",
    },
    {
        "id": "baja_porcentaje",
        "label": "Baja respecto al PBL (%) si aplica",
        "grupo": "Oferta económica",
        "tipo": "text",
    },
    {
        "id": "desglose_partidas",
        "label": "Desglose por partidas / precios unitarios",
        "grupo": "Desglose",
        "tipo": "area",
    },
    {
        "id": "anualidades",
        "label": "Anualidades / distribución temporal",
        "grupo": "Desglose",
        "tipo": "area",
    },
    {
        "id": "variantes_mejoras",
        "label": "Variantes / mejoras económicas (si se admiten)",
        "grupo": "Desglose",
        "tipo": "area",
    },
    {
        "id": "modelo_anexo",
        "label": "Modelo / anexo económico del pliego a usar",
        "grupo": "Formato",
        "tipo": "text",
    },
    {
        "id": "moneda_unidad",
        "label": "Moneda y unidad (EUR, €/ud…)",
        "grupo": "Formato",
        "tipo": "text",
    },
    {
        "id": "observaciones_eco",
        "label": "Observaciones económicas",
        "grupo": "Formato",
        "tipo": "area",
    },
]

REGLA_MODELOS = """
REGLA OBLIGATORIA SOBRE ANEXOS:
- Los anexos a generar serán SIEMPRE los **modelos propuestos en los pliegos**
  (PCAP y/o PPT), identificados por su número/nombre de anexo.
- NO inventes anexos genéricos propios si el pliego ya aporta modelo.
- Extrae y respeta las **variables / campos en blanco** de cada modelo
  (casillas, tablas, declaraciones, firmas, fechas, NIF, lotes…).
- Si un campo del modelo no tiene dato en el formulario, usa `[COMPLETAR: …]`.
"""

CAMPOS_TEC: list[dict[str, Any]] = [
    {"id": "razon_social", "label": "Razón social / entidad", "grupo": "Identificación", "tipo": "text"},
    {"id": "nif", "label": "NIF / CIF", "grupo": "Identificación", "tipo": "text"},
    {"id": "expediente", "label": "ID expediente", "grupo": "Identificación", "tipo": "text"},
    {
        "id": "organo",
        "label": "Órgano de contratación",
        "grupo": "Identificación",
        "tipo": "text",
    },
    {
        "id": "objeto",
        "label": "Objeto del contrato",
        "grupo": "Identificación",
        "tipo": "area",
    },
    {"id": "lote", "label": "Lote(s)", "grupo": "Identificación", "tipo": "text"},
    {
        "id": "anexos_modelo_ppt",
        "label": "Anexos/modelos del PPT a rellenar (números y títulos)",
        "grupo": "Modelos del pliego",
        "tipo": "area",
    },
    {
        "id": "anexos_modelo_pcap",
        "label": "Anexos técnicos que figuren también en el PCAP",
        "grupo": "Modelos del pliego",
        "tipo": "area",
    },
    {
        "id": "criterios_tecnicos",
        "label": "Criterios técnicos de adjudicación a cubrir",
        "grupo": "Modelos del pliego",
        "tipo": "area",
    },
    {
        "id": "comprension_necesidad",
        "label": "Comprensión de la necesidad / objeto",
        "grupo": "Memoria técnica",
        "tipo": "area",
    },
    {
        "id": "metodologia",
        "label": "Metodología / plan de trabajo",
        "grupo": "Memoria técnica",
        "tipo": "area",
    },
    {
        "id": "medios_humanos",
        "label": "Medios humanos / equipo (perfiles, dedicación)",
        "grupo": "Memoria técnica",
        "tipo": "area",
    },
    {
        "id": "medios_materiales",
        "label": "Medios materiales / equipos / instalaciones",
        "grupo": "Memoria técnica",
        "tipo": "area",
    },
    {
        "id": "cronograma",
        "label": "Cronograma / plazos de ejecución",
        "grupo": "Memoria técnica",
        "tipo": "area",
    },
    {
        "id": "experiencia_similar",
        "label": "Experiencia similar / referencias",
        "grupo": "Memoria técnica",
        "tipo": "area",
    },
    {
        "id": "calidad_medioambiente",
        "label": "Calidad, seguridad, medio ambiente (si aplica)",
        "grupo": "Memoria técnica",
        "tipo": "area",
    },
    {
        "id": "mejoras",
        "label": "Mejoras / valor añadido (solo si el pliego las admite)",
        "grupo": "Memoria técnica",
        "tipo": "area",
    },
    {
        "id": "variables_modelos",
        "label": "Otras variables de los modelos/anexos (campo → valor)",
        "grupo": "Variables de anexos",
        "tipo": "area",
    },
    {
        "id": "observaciones_tec",
        "label": "Observaciones técnicas",
        "grupo": "Variables de anexos",
        "tipo": "area",
    },
]

PROMPT_EXIGENCIAS_ADMIN = f"""Eres experto en contratación pública española (PCAP).
Extrae SOLO exigencias de la **documentación administrativa** a presentar.
{REGLA_MODELOS}

Devuelve markdown en español con estas secciones exactas:

## Modelos y anexos administrativos del pliego
Lista CADA modelo/anexo del PCAP (y PPT si aporta anexos admin) con:
número/nombre, para qué sirve, si es eliminatorio, y si hay plantilla oficial.

## Variables de cada modelo
Por cada anexo/modelo: campos o huecos a rellenar (NIF, representante, lote,
casillas sí/no, tablas, fechas, firmas…).

## Formato y presentación
- Formato de fichero (PDF, DOCX, XML DEUC…)
- Firmas (manuscrita, electrónica, eIDAS…)
- Idioma, sobres / apartados electrónicos
- **Fuente tipográfica, tamaño, interlineado, extensión máxima** si constan
- Nomenclatura de archivos

## Datos obligatorios fuera de anexos
Capacidad, solvencia, prohibiciones, etc. si no van en un modelo concreto.

## Advertencias / causas de exclusión documentales
## Campos del formulario GREFA sugeridos
Variables a pedir para rellenar esos modelos (incluye las de los anexos).

Si un dato no consta, escribe «No consta». No inventes. Cita PCAP/PPT/anexo."""

PROMPT_BORRADOR_ADMIN = f"""Eres redactor de documentación administrativa de licitaciones para GREFA.
{REGLA_MODELOS}

Con DATOS DEL FORMULARIO y EXIGENCIAS del pliego, redacta un **borrador
administrativo** en español (markdown) basado en los modelos del pliego.

Incluye:

## Portada / identificación
Expediente, órgano, objeto, lote, licitador, NIF, representante.

## Anexos / modelos del pliego (rellenados)
Para CADA modelo/anexo identificado en el PCAP (o PPT si aplica):
### Anexo X — [título del pliego]
- Reproduce la estructura del modelo (apartados, tablas, declaraciones).
- Rellena con datos del formulario; huecos → `[COMPLETAR: …]`.
- Indica origen: PCAP/PPT y número de anexo.
NO añadas anexos que el pliego no proponga, salvo una sección final
«Documentos a aportar aparte» (certificados, poderes…) sin inventar modelo.

## Cumplimiento de formato
Fuente, PDF/DOCX, firma, sobres, extensión… → cómo cumplirlos en el fichero final.

## Pendientes antes de firmar
Lista accionable.

Reglas:
- Usa SOLO datos del formulario; no inventes NIF ni fechas.
- Es un BORRADOR: no digas que está listo para presentar sin revisión."""

PROMPT_VERIFICAR_ADMIN = f"""Eres revisor de conformidad documental administrativa (pliego vs borrador GREFA).
{REGLA_MODELOS}

Comprueba que el borrador usa los **modelos del pliego**, rellena sus variables,
y respeta formatos/fuentes/firmas.

Responde en español con:

## Veredicto de conformidad
Una línea con UNA etiqueta:
- `✅ CONFORME CON EL PLIEGO (borrador)`
- `⚠️ CONFORME CON RESERVAS`
- `❌ NO CONFORME`

## Modelos/anexos del pliego cubiertos
## Modelos/anexos o variables NO cubiertos
## Formato / fuente / firma
## Inconsistencias formulario ↔ borrador ↔ pliego
## Ajustes concretos antes del PDF final
## Limitaciones

No des visto bueno jurídico. Sé estricto con modelos oficiales del pliego."""

PROMPT_EXIGENCIAS_ECO = f"""Eres experto en contratación pública española (oferta económica / PCAP).
Extrae SOLO exigencias de la **oferta económica** a presentar.
{REGLA_MODELOS}

Devuelve markdown en español con estas secciones exactas:

## Modelos y anexos económicos del pliego
Cada modelo/anexo (número, título, eliminatorio, plantilla).

## Variables de cada modelo económico
Campos, filas de tablas de precios, IVA, lotes, firmas, etc.

## Importes y reglas de cálculo
PBL, IVA, bajas, partidas, anualidades, decimales, moneda.

## Formato y presentación
Fichero, **fuente tipográfica**, sobres ECONÓMICA, nomenclatura.

## Criterios económicos de adjudicación (si ayudan a rellenar)
## Causas de exclusión / nulidad por defecto económico
## Campos del formulario GREFA sugeridos
Incluye variables de los modelos/anexos.

Si un dato no consta: «No consta». Cita PCAP/anexo."""

PROMPT_BORRADOR_ECO = f"""Eres redactor de la **oferta económica** de GREFA.
{REGLA_MODELOS}

Con DATOS DEL FORMULARIO y EXIGENCIAS, redacta un **borrador económico**
basado en los modelos del pliego (no en plantillas inventadas).

Incluye:

## Portada económica
## Anexos / modelos económicos del pliego (rellenados)
Por cada anexo/modelo económico del PCAP:
### Anexo X — [título]
Estructura del modelo + datos del formulario; huecos `[COMPLETAR: …]`.

## Cuadro resumen (si el modelo lo incluye o el pliego lo pide aparte)
Importes solo del formulario; no inventes.

## Cumplimiento de formato
## Pendientes antes de firmar / presentar

Reglas:
- NO inventes importes ni partidas.
- NO crees anexos que el pliego no proponga.
- Es un BORRADOR."""

PROMPT_VERIFICAR_ECO = f"""Eres revisor de conformidad de la **oferta económica**.
{REGLA_MODELOS}

Comprueba modelos/anexos del pliego, variables, importes, IVA, formatos y fuentes.

## Veredicto de conformidad
Una línea con UNA etiqueta:
- `✅ CONFORME CON EL PLIEGO (borrador)`
- `⚠️ CONFORME CON RESERVAS`
- `❌ NO CONFORME`

## Modelos/anexos cubiertos
## Modelos/variables NO cubiertos
## Inconsistencias de importes / cálculos
## Formato / fuente / firma
## Ajustes concretos antes del fichero final
## Limitaciones

No des visto bueno jurídico ni financiero."""

PROMPT_EXIGENCIAS_TEC = f"""Eres experto en contratación pública española (PPT / oferta técnica).
Extrae SOLO exigencias de la **documentación técnica** a presentar.
{REGLA_MODELOS}

Devuelve markdown en español con estas secciones exactas:

## Modelos y anexos técnicos del pliego
Lista CADA modelo/anexo del **PPT** y, si también hay anexos técnicos en el **PCAP**,
inclúyelos. Número/nombre, contenido esperado, eliminatorio, plantilla.

## Variables de cada modelo técnico
Campos, tablas, epígrafes obligatorios de memoria, fichas, compromisos, firmas…

## Contenido técnico exigido (aunque no haya anexo numerado)
Epígrafes de memoria, metodología, medios, plazos, mejoras admitidas, etc.

## Formato y presentación
- Extensión máxima, estructura de capítulos
- **Fuente tipográfica, tamaño, interlineado, márgenes**
- Formato de fichero, firmas, sobre/apartado TÉCNICA
- Prohibición de datos económicos en el sobre técnico (si consta)

## Criterios técnicos de adjudicación a cubrir
## Causas de exclusión / incumplimiento técnico documental
## Campos del formulario GREFA sugeridos
Variables para rellenar modelos del PPT/PCAP + memoria.

Si un dato no consta: «No consta». Cita PPT/PCAP/anexo."""

PROMPT_BORRADOR_TEC = f"""Eres redactor de la **oferta técnica** de GREFA.
{REGLA_MODELOS}

Con DATOS DEL FORMULARIO y EXIGENCIAS (PPT y/o PCAP), redacta un **borrador técnico**
basado en los modelos del pliego.

Incluye:

## Portada técnica
Expediente, órgano, objeto, lote, licitador, NIF.

## Anexos / modelos técnicos del pliego (rellenados)
Para CADA anexo/modelo del PPT (y técnicos del PCAP):
### Anexo X — [título exacto del pliego]
- Sigue la estructura del modelo (no inventes otro índice).
- Rellena con datos del formulario / variables; `[COMPLETAR: …]` si falta.
- Indica si proviene de PPT o PCAP.

## Memoria técnica (solo si el pliego la exige y no está ya en un anexo)
Usa epígrafes que pida el pliego. Si el pliego no pide memoria libre, omite esta
sección o redúcela a «No exigida como documento libre».

## Cumplimiento de formato
Fuente, extensión, PDF, sobre técnico, etc.

## Pendientes antes de firmar / presentar

Reglas:
- NO inventes anexos distintos a los del pliego.
- NO metas precios/importes en el sobre técnico si el pliego lo prohíbe.
- Es un BORRADOR técnico, no una oferta firmada."""

PROMPT_VERIFICAR_TEC = f"""Eres revisor de conformidad de la **oferta técnica**.
{REGLA_MODELOS}

Comprueba que el borrador sigue los modelos del PPT/PCAP, rellena sus variables,
cubre criterios técnicos y respeta formatos/fuentes (sin filtrar datos económicos
si están prohibidos en el sobre técnico).

## Veredicto de conformidad
Una línea con UNA etiqueta:
- `✅ CONFORME CON EL PLIEGO (borrador)`
- `⚠️ CONFORME CON RESERVAS`
- `❌ NO CONFORME`

## Modelos/anexos del PPT/PCAP cubiertos
## Modelos/variables NO cubiertos
## Criterios técnicos insuficientemente tratados
## Formato / fuente / extensión / sobre
## Riesgo de incluir datos económicos indebidos
## Ajustes concretos antes del PDF final
## Limitaciones

No des visto bueno técnico-jurídico."""

BLOQUES: dict[str, dict[str, Any]] = {
    "admin": {
        "id": "admin",
        "etiqueta": "Administrativo",
        "campos": CAMPOS_ADMIN,
        "prompt_exigencias": PROMPT_EXIGENCIAS_ADMIN,
        "prompt_borrador": PROMPT_BORRADOR_ADMIN,
        "prompt_verificar": PROMPT_VERIFICAR_ADMIN,
        "enfoque": (
            "documentación ADMINISTRATIVA; anexos = modelos del PCAP/PPT "
            "y sus variables"
        ),
        "uploader_help": "PDF del PCAP (y anexos/modelos administrativos)",
    },
    "eco": {
        "id": "eco",
        "etiqueta": "Económico",
        "campos": CAMPOS_ECO,
        "prompt_exigencias": PROMPT_EXIGENCIAS_ECO,
        "prompt_borrador": PROMPT_BORRADOR_ECO,
        "prompt_verificar": PROMPT_VERIFICAR_ECO,
        "enfoque": (
            "OFERTA ECONÓMICA; anexos = modelos del pliego y sus variables/importes"
        ),
        "uploader_help": "PDF del PCAP / modelos de oferta económica",
    },
    "tec": {
        "id": "tec",
        "etiqueta": "Técnico",
        "campos": CAMPOS_TEC,
        "prompt_exigencias": PROMPT_EXIGENCIAS_TEC,
        "prompt_borrador": PROMPT_BORRADOR_TEC,
        "prompt_verificar": PROMPT_VERIFICAR_TEC,
        "enfoque": (
            "OFERTA TÉCNICA; anexos = modelos del PPT y/o PCAP y sus variables"
        ),
        "uploader_help": "PDF del PPT (y PCAP si incluye anexos técnicos)",
    },
}


def listar_bloques() -> list[tuple[str, str]]:
    return [(cfg["id"], cfg["etiqueta"]) for cfg in BLOQUES.values()]


def config_bloque(bloque: str) -> dict[str, Any]:
    if bloque not in BLOQUES:
        raise KeyError(f"Bloque desconocido: {bloque}")
    return BLOQUES[bloque]


def campos_por_grupo(bloque: str = "admin") -> dict[str, list[dict[str, Any]]]:
    cfg = config_bloque(bloque)
    salida: dict[str, list[dict[str, Any]]] = {}
    for campo in cfg["campos"]:
        salida.setdefault(str(campo["grupo"]), []).append(campo)
    return salida


def datos_formulario_a_texto(datos: dict[str, str], bloque: str = "admin") -> str:
    cfg = config_bloque(bloque)
    lineas = []
    for campo in cfg["campos"]:
        valor = str(datos.get(campo["id"], "") or "").strip()
        if valor:
            lineas.append(f"- {campo['label']}: {valor}")
    return "\n".join(lineas) if lineas else "(sin datos)"


def _docs_pliego(documentos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return pdf_summary._validar_pdfs(documentos, etiqueta="pliegos")


def extraer_exigencias(
    bloque: str,
    documentos_pliego: list[dict[str, Any]],
    *,
    expediente: str = "",
    titulo: str = "",
) -> str:
    cfg = config_bloque(bloque)
    utiles = _docs_pliego(documentos_pliego)
    contexto = (
        f"Expediente: {expediente or '—'}\n"
        f"Título: {titulo or '—'}\n"
        f"Enfoque: {cfg['enfoque']}."
    )
    try:
        return pdf_summary._generar_con_gemini(
            pdf_summary._partes_gemini_pdfs(utiles, max_docs=4),
            contexto=contexto,
            prompt_base=cfg["prompt_exigencias"],
        )
    except pdf_summary.PdfSummaryError:
        texto = pdf_summary._texto_desde_pdfs(utiles)
        if len(texto.strip()) < 200:
            raise
        return pdf_summary._generar_con_gemini(
            [f"Extracto del pliego:\n---\n{texto}\n---"],
            contexto=contexto,
            prompt_base=cfg["prompt_exigencias"],
        )


def generar_borrador(
    bloque: str,
    datos: dict[str, str],
    exigencias: str,
    *,
    documentos_pliego: list[dict[str, Any]] | None = None,
) -> str:
    cfg = config_bloque(bloque)
    contexto = (
        "DATOS DEL FORMULARIO:\n"
        f"{datos_formulario_a_texto(datos, bloque)}\n\n"
        "EXIGENCIAS EXTRAÍDAS DEL PLIEGO:\n"
        f"{(exigencias or 'No disponibles').strip()[:20000]}"
    )
    partes: list[Any] = [
        f"Genera el borrador {cfg['etiqueta'].lower()} con la información anterior."
    ]
    if documentos_pliego:
        try:
            tope = 3 if bloque == "tec" else 2
            utiles = _docs_pliego(documentos_pliego)[:tope]
            partes.append(
                "Pliego(s) de apoyo (usa SOLO sus modelos/anexos oficiales):"
            )
            partes.extend(pdf_summary._partes_gemini_pdfs(utiles, max_docs=tope))
        except pdf_summary.PdfSummaryError:
            pass
    return pdf_summary._generar_con_gemini(
        partes,
        contexto=contexto,
        prompt_base=cfg["prompt_borrador"],
    )


def verificar_ajuste(
    bloque: str,
    borrador: str,
    exigencias: str,
    *,
    datos: dict[str, str] | None = None,
    documentos_pliego: list[dict[str, Any]] | None = None,
) -> str:
    cfg = config_bloque(bloque)
    contexto = (
        "EXIGENCIAS DEL PLIEGO:\n"
        f"{(exigencias or '').strip()[:16000]}\n\n"
        f"BORRADOR {cfg['etiqueta'].upper()} GREFA:\n"
        f"{(borrador or '').strip()[:16000]}\n\n"
        "DATOS DEL FORMULARIO:\n"
        f"{datos_formulario_a_texto(datos or {}, bloque)}"
    )
    partes: list[Any] = [f"Verifica conformidad {cfg['etiqueta'].lower()} y de formato."]
    if documentos_pliego:
        try:
            utiles = _docs_pliego(documentos_pliego)[:2]
            partes.append("Pliego original:")
            partes.extend(pdf_summary._partes_gemini_pdfs(utiles, max_docs=2))
        except pdf_summary.PdfSummaryError:
            pass
    return pdf_summary._generar_con_gemini(
        partes,
        contexto=contexto,
        prompt_base=cfg["prompt_verificar"],
    )


# Compatibilidad con llamadas antiguas
def campos_por_grupo_admin() -> dict[str, list[dict[str, Any]]]:
    return campos_por_grupo("admin")


def extraer_exigencias_admin(
    documentos_pliego: list[dict[str, Any]],
    *,
    expediente: str = "",
    titulo: str = "",
) -> str:
    return extraer_exigencias(
        "admin", documentos_pliego, expediente=expediente, titulo=titulo
    )


def generar_borrador_admin(
    datos: dict[str, str],
    exigencias: str,
    *,
    documentos_pliego: list[dict[str, Any]] | None = None,
) -> str:
    return generar_borrador(
        "admin", datos, exigencias, documentos_pliego=documentos_pliego
    )


def verificar_ajuste_admin(
    borrador: str,
    exigencias: str,
    *,
    datos: dict[str, str] | None = None,
    documentos_pliego: list[dict[str, Any]] | None = None,
) -> str:
    return verificar_ajuste(
        "admin",
        borrador,
        exigencias,
        datos=datos,
        documentos_pliego=documentos_pliego,
    )


def sugerir_campos_desde_exigencias(exigencias: str) -> list[str]:
    """Extrae variables sugeridas (formulario + modelos) desde las exigencias."""
    if not exigencias:
        return []
    items: list[str] = []
    for patron in (
        r"##\s*Campos del formulario.*?\n(.*?)(?:\n##\s|\Z)",
        r"##\s*Variables de cada modelo.*?\n(.*?)(?:\n##\s|\Z)",
    ):
        match = re.search(patron, exigencias, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            continue
        for linea in match.group(1).splitlines():
            limpia = re.sub(r"^[\s\-\*\d\.]+", "", linea).strip()
            if limpia and limpia.lower() != "no consta" and limpia not in items:
                items.append(limpia[:200])
    return items[:30]


def serializar_datos(datos: dict[str, str]) -> str:
    return json.dumps(datos, ensure_ascii=False, indent=2)


def copiar_datos_compartidos(
    origen: dict[str, str],
    *,
    hacia_bloque: str,
) -> dict[str, str]:
    """Copia campos comunes (NIF, expediente…) hacia otro bloque."""
    cfg = config_bloque(hacia_bloque)
    ids = {c["id"] for c in cfg["campos"]}
    comunes = (
        "razon_social",
        "nif",
        "expediente",
        "organo",
        "objeto",
        "lote",
    )
    salida: dict[str, str] = {}
    for cid in comunes:
        if cid in ids and origen.get(cid):
            salida[cid] = str(origen[cid]).strip()
    return salida


def fuentes_copia_datos(bloque: str) -> list[str]:
    """Otros bloques desde los que tiene sentido importar datos comunes."""
    return [b for b in ("admin", "eco", "tec") if b != bloque]
