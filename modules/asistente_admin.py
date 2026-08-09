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
  (PCAP y/o PPT), identificados por su número/nombre de anexo (Anexo I, II…).
- NO inventes anexos genéricos propios si el pliego ya aporta modelo.
- Respeta la **estructura campo a campo** del modelo (casillas, tablas, epígrafes).
- Usa los valores del formulario (incluidos campos `anx_*` de cada anexo).
- Si un campo del modelo no tiene dato, usa `[COMPLETAR: campo]`.
- Indica siempre el número de anexo del pliego en el encabezado de cada sección.
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


MAX_DOCS_APOYO = 4

PROMPT_DOC_CAMPO = """Eres un revisor de documentación de oferta para licitaciones públicas
españolas (PLACSP), trabajando para GREFA.

Te pasan:
1) Un **documento aportado** por GREFA.
2) El **campo del formulario** al que se quiere asociar (nombre y contexto).
3) Exigencias / modelos del pliego del bloque (administrativo, económico o técnico).

## Objetivo
Comprobar si ese documento **corresponde, se adapta y es válido** para el campo
indicado según el pliego (tipo de documento, contenido, estructura, modelo/anexo,
idioma, firmas visibles, datos coherentes con el campo).

No inventes requisitos que no estén en el pliego o en la descripción del campo.
Si el pliego no detalla el campo, evalúa coherencia formal razonable y márcalo
en limitaciones.

Responde en **español**, markdown, con estas secciones:

## Veredicto
Una línea con UNA etiqueta:
- `✅ VÁLIDO PARA EL CAMPO` — encaja con lo pedido para ese campo
- `⚠️ VÁLIDO CON RESERVAS` — útil pero incompleto o con dudas
- `❌ NO VÁLIDO / NO CORRESPONDE` — no es el documento del campo o no se adapta

Luego 2–4 frases.

## Correspondencia con el campo
¿Es el tipo de documento/modelo que pide ese campo? sí / parcial / no.

## Adaptación al pliego / modelo
Estructura, cláusulas, anexos o formato exigido vs lo aportado.

## Defectos o huecos
Lista breve (gravedad Bloqueante / Importante / Menor). Si no hay: «Ninguno evidente».

## Limitaciones
Qué no has podido verificar.

Sé concreto. El veredicto es solo sobre **este documento ↔ este campo**."""


def listar_campos_formulario(
    bloque: str = "admin",
    modelos: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Campos del bloque (+ anexos dinámicos) para asociar documentos."""
    salida: list[dict[str, str]] = []
    for campo in config_bloque(bloque)["campos"]:
        salida.append(
            {
                "id": str(campo["id"]),
                "label": str(campo["label"]),
                "grupo": str(campo.get("grupo") or ""),
            }
        )
    for campo in campos_desde_modelos(modelos or {}):
        salida.append(
            {
                "id": str(campo["id"]),
                "label": str(campo["label"]),
                "grupo": str(campo.get("grupo") or ""),
            }
        )
    return salida


def comprobar_documento_para_campo(
    bloque: str,
    documento: dict[str, Any],
    *,
    campo_id: str,
    campo_label: str,
    exigencias: str = "",
    documentos_pliego: list[dict[str, Any]] | None = None,
    modelos: dict[str, Any] | None = None,
) -> str:
    """Valida si un documento aportado corresponde al campo del formulario."""
    if not documento or not documento.get("bytes"):
        raise pdf_summary.PdfSummaryError("No hay documento para comprobar.")
    if not (campo_id or campo_label):
        raise pdf_summary.PdfSummaryError(
            "Indica a qué campo del formulario corresponde el documento."
        )

    cfg = config_bloque(bloque)
    utiles = pdf_summary._validar_pdfs([documento], etiqueta="documento aportado")
    doc = utiles[0]
    estructura = ""
    if modelos and modelos.get("anexos"):
        estructura = "MODELOS/ANEXOS DEL PLIEGO:\n" + json.dumps(
            modelos.get("anexos"), ensure_ascii=False, indent=2
        )[:10000]

    contexto = (
        f"Bloque: {cfg['etiqueta']}\n"
        f"Campo del formulario (id): {campo_id or '—'}\n"
        f"Campo del formulario (etiqueta): {campo_label or '—'}\n"
        f"Nombre del fichero: {doc.get('nombre', 'documento')}\n\n"
        "EXIGENCIAS DEL PLIEGO (bloque):\n"
        f"{(exigencias or 'No disponibles').strip()[:12000]}\n\n"
        f"{estructura}"
    )
    partes: list[Any] = [
        "Comprueba si el documento adjunto corresponde y es válido "
        f"para el campo «{campo_label or campo_id}»."
    ]
    partes.extend(pdf_summary._partes_gemini_pdfs([doc], max_docs=1))
    if documentos_pliego:
        try:
            pliegos = _docs_pliego(documentos_pliego)[:2]
            partes.append("Pliego de referencia (modelos oficiales):")
            partes.extend(pdf_summary._partes_gemini_pdfs(pliegos, max_docs=2))
        except pdf_summary.PdfSummaryError:
            pass
    return pdf_summary._generar_con_gemini(
        partes,
        contexto=contexto,
        prompt_base=PROMPT_DOC_CAMPO,
    )


def generar_borrador(
    bloque: str,
    datos: dict[str, str],
    exigencias: str,
    *,
    documentos_pliego: list[dict[str, Any]] | None = None,
    documentos_apoyo: list[dict[str, Any]] | None = None,
    modelos: dict[str, Any] | None = None,
) -> str:
    cfg = config_bloque(bloque)
    # Incluye también campos dinámicos de anexos (anx_*)
    lineas_datos = [datos_formulario_a_texto(datos, bloque)]
    extras = [
        f"- {k}: {v}"
        for k, v in sorted(datos.items())
        if k.startswith("anx_") and str(v or "").strip()
    ]
    if extras:
        lineas_datos.append("VARIABLES DE ANEXOS/MODELOS:")
        lineas_datos.extend(extras)
    extracto_apoyo = str((datos or {}).get("_extracto_docs_apoyo") or "").strip()
    if extracto_apoyo:
        lineas_datos.append(
            "EXTRACTO DE DOCUMENTOS APORTADOS POR GREFA:\n" + extracto_apoyo[:20000]
        )
    estructura = ""
    if modelos and modelos.get("anexos"):
        estructura = "ESTRUCTURA OBLIGATORIA DE ANEXOS DEL PLIEGO:\n" + json.dumps(
            modelos.get("anexos"), ensure_ascii=False, indent=2
        )[:12000]
    contexto = (
        "DATOS DEL FORMULARIO (texto y/o documentos aportados):\n"
        f"{chr(10).join(lineas_datos)}\n\n"
        "EXIGENCIAS EXTRAÍDAS DEL PLIEGO:\n"
        f"{(exigencias or 'No disponibles').strip()[:16000]}\n\n"
        f"{estructura}"
    )
    partes: list[Any] = [
        f"Genera el borrador {cfg['etiqueta'].lower()} con la información anterior. "
        "Si hay documentos aportados por GREFA, úsalos como fuente de datos "
        "(junto o en lugar de los campos de texto)."
    ]
    if documentos_apoyo:
        try:
            utiles_ap = pdf_summary._validar_pdfs(
                documentos_apoyo, etiqueta="documentos aportados"
            )[:MAX_DOCS_APOYO]
            partes.append(
                "DOCUMENTOS APORTADOS POR GREFA (fuente de datos del formulario; "
                "NO son el pliego oficial):"
            )
            partes.extend(
                pdf_summary._partes_gemini_pdfs(utiles_ap, max_docs=MAX_DOCS_APOYO)
            )
        except pdf_summary.PdfSummaryError:
            pass
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


PROMPT_MODELOS_JSON = """Eres experto en pliegos de contratación pública española.
A partir del pliego (PCAP y/o PPT), identifica los **modelos/anexos numerados**
que el licitador debe rellenar y sus campos variables.

Responde SOLO con JSON válido (sin markdown) con esta forma:
{
  "anexos": [
    {
      "id": "Anexo I",
      "titulo": "título exacto del pliego",
      "origen": "PCAP|PPT",
      "campos": [
        {"id": "campo_slug", "label": "etiqueta legible", "tipo": "text|area|check"}
      ]
    }
  ],
  "fecha_limite_presentacion": "YYYY-MM-DD o vacío si no consta",
  "formato": {
    "fuente": "Arial u otra si consta",
    "tamano": 11,
    "margen_cm": 2.5,
    "interlineado": 1.15
  }
}

Reglas:
- Solo anexos/modelos que el pliego proponga (no inventes).
- id de campo en snake_case, único dentro del anexo.
- Máximo 40 campos en total.
- Si no hay anexos numerados, "anexos": [].
"""


def _parse_json_respuesta(texto: str) -> dict[str, Any]:
    crudo = (texto or "").strip()
    if crudo.startswith("```"):
        crudo = re.sub(r"^```(?:json)?\s*", "", crudo)
        crudo = re.sub(r"\s*```$", "", crudo)
    try:
        data = json.loads(crudo)
        return data if isinstance(data, dict) else {}
    except Exception:
        m = re.search(r"\{.*\}", crudo, flags=re.DOTALL)
        if not m:
            return {}
        try:
            data = json.loads(m.group(0))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}


def extraer_modelos_estructurados(
    documentos_pliego: list[dict[str, Any]],
    *,
    bloque: str = "admin",
    expediente: str = "",
    titulo: str = "",
) -> dict[str, Any]:
    """Detecta anexos numerados y campos a rellenar (JSON estructurado)."""
    utiles = _docs_pliego(documentos_pliego)
    cfg = config_bloque(bloque)
    contexto = (
        f"Expediente: {expediente or '—'}\n"
        f"Título: {titulo or '—'}\n"
        f"Bloque: {cfg['etiqueta']}\n"
        f"Enfoque: {cfg['enfoque']}"
    )
    try:
        texto = pdf_summary._generar_con_gemini(
            pdf_summary._partes_gemini_pdfs(utiles, max_docs=4),
            contexto=contexto,
            prompt_base=PROMPT_MODELOS_JSON,
        )
    except pdf_summary.PdfSummaryError:
        extracto = pdf_summary._texto_desde_pdfs(utiles)
        if len(extracto.strip()) < 200:
            raise
        texto = pdf_summary._generar_con_gemini(
            [f"Extracto pliego:\n---\n{extracto}\n---"],
            contexto=contexto,
            prompt_base=PROMPT_MODELOS_JSON,
        )
    data = _parse_json_respuesta(texto)
    anexos = data.get("anexos") if isinstance(data.get("anexos"), list) else []
    normalizados = []
    vistos: set[str] = set()
    for anx in anexos[:20]:
        if not isinstance(anx, dict):
            continue
        aid = str(anx.get("id") or "").strip() or "Anexo"
        titulo_a = str(anx.get("titulo") or "").strip()
        origen = str(anx.get("origen") or "").strip() or "PCAP"
        campos_out = []
        for campo in anx.get("campos") or []:
            if not isinstance(campo, dict):
                continue
            cid = re.sub(r"[^\w]+", "_", str(campo.get("id") or "").strip().lower()).strip("_")
            if not cid or cid in vistos:
                continue
            vistos.add(cid)
            tipo = str(campo.get("tipo") or "text").strip().lower()
            if tipo not in {"text", "area", "check"}:
                tipo = "text"
            campos_out.append(
                {
                    "id": cid[:60],
                    "label": str(campo.get("label") or cid)[:160],
                    "tipo": tipo,
                    "anexo_id": aid,
                }
            )
        normalizados.append(
            {
                "id": aid[:80],
                "titulo": titulo_a[:200],
                "origen": origen[:20],
                "campos": campos_out[:25],
            }
        )
    formato = data.get("formato") if isinstance(data.get("formato"), dict) else {}
    return {
        "anexos": normalizados,
        "fecha_limite_presentacion": str(data.get("fecha_limite_presentacion") or "").strip(),
        "formato": formato,
    }


def campos_desde_modelos(modelos: dict[str, Any]) -> list[dict[str, Any]]:
    """Aplana campos de anexos para el formulario dinámico."""
    salida: list[dict[str, Any]] = []
    for anx in modelos.get("anexos") or []:
        grupo = f"{anx.get('id')} — {anx.get('titulo') or anx.get('origen')}"
        for campo in anx.get("campos") or []:
            salida.append(
                {
                    "id": f"anx_{campo['id']}",
                    "label": f"[{anx.get('id')}] {campo['label']}",
                    "tipo": campo.get("tipo") or "text",
                    "grupo": grupo[:80],
                }
            )
    return salida


def parse_fecha_limite(texto: str) -> str:
    """Devuelve YYYY-MM-DD si encuentra una fecha de presentación en texto."""
    if not texto:
        return ""
    # ISO
    m = re.search(r"(20\d{2})-(\d{2})-(\d{2})", texto)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.search(
        r"(?:presentaci[oó]n|plazo|fecha\s*l[ií]mite)[^\d]{0,40}"
        r"(\d{1,2})[/\-.](\d{1,2})[/\-.](20\d{2})",
        texto,
        flags=re.IGNORECASE,
    )
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"
    return ""
