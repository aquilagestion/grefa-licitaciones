"""Persistencia compartida en Google Sheets.

Pestañas principales:

* ``CatalogoCPV`` / ``CatalogoTerminos`` → catálogos completos seleccionables
  (Activo = sí/no). Los términos llevan columnas en castellano, euskera, catalán
  y gallego.
* ``CPV`` / ``PalabrasClave`` → resumen de lo que está activo (para lectura rápida).
* ``Oportunidades`` → volcado de licitaciones relevantes con seguimiento editable.
* ``Historico`` → snapshot diario de oportunidades Alta/Media.
* ``Config`` → estado de la sincronización diaria y claves Alta vistas.
* ``Instrucciones`` → guía de uso.

Si no hay hoja configurada, la aplicación sigue funcionando solo en memoria.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import datetime
from typing import Any

import pandas as pd

LOGGER = logging.getLogger(__name__)

SCOPES = (
    "https://www.googleapis.com/auth/spreadsheets",
    # drive (no solo drive.file): permite escribir en carpeta compartida con la SA
    "https://www.googleapis.com/auth/drive",
)

CPV_SHEET = "CPV"
KEYWORDS_SHEET = "PalabrasClave"
OPPORTUNITIES_SHEET = "Oportunidades"
PLIEGOS_SHEET = "Pliegos"
CHECKLIST_SHEET = "ChecklistDocs"
MIS_LICITACIONES_SHEET = "MisLicitaciones"
ASISTENTE_SHEET = "AsistenteDocs"
README_SHEET = "Instrucciones"
OPPORTUNITIES_AYUDAS_SHEET = "OportunidadesAyudas"
MIS_CONVOCATORIAS_SHEET = "MisConvocatorias"
ENTIDADES_SHEET = "EntidadesAyudas"

# Cabeceras en español (las lee el equipo en Drive y el código por nombre).
CPV_HEADERS = ["Código CPV", "Descripción", "Activo"]
KEYWORD_HEADERS = ["Término", "Categoría", "Activo"]
OPPORTUNITY_HEADERS = [
    "Fecha detección",
    "Relevancia (%)",
    "Categoría",
    "ID Expediente",
    "Título / Objeto",
    "Órgano de Contratación",
    "Presupuesto sin IVA",
    "Ubicación",
    "Códigos CPV",
    "Palabras clave",
    "Fecha límite",
    "Estado PLACSP",
    "Enlace",
    "Seguimiento",
    "Notas",
]
PLIEGO_HEADERS = [
    "ID Expediente",
    "Enlace",
    "Título",
    "Resumen",
    "Fecha análisis",
]
CHECKLIST_HEADERS = [
    "ID Expediente",
    "Enlace",
    "Título",
    "Documento",
    "Estado",
    "Notas",
    "Enlace Drive",
    "Fecha actualización",
]
MIS_LICITACIONES_HEADERS = [
    "ID Expediente",
    "Enlace",
    "Título",
    "Órgano de Contratación",
    "Presupuesto sin IVA",
    "Estado PLACSP",
    "Relevancia (%)",
    "Me interesa",
    "Me presento",
    "Fecha interés",
    "Notas",
]
OPPORTUNITY_AYUDAS_HEADERS = [
    "Fecha detección",
    "Relevancia (%)",
    "Categoría",
    "Código BDNS",
    "Título / Objeto",
    "Órgano convocante",
    "Presupuesto total",
    "Ámbito",
    "Instrumento",
    "Palabras clave",
    "Fin de solicitud",
    "Estado",
    "Enlace",
    "Seguimiento",
    "Notas",
]
MIS_CONVOCATORIAS_HEADERS = [
    "Código BDNS",
    "Enlace",
    "Título",
    "Órgano convocante",
    "Presupuesto total",
    "Estado",
    "Relevancia (%)",
    "Me interesa",
    "Me presento",
    "Fecha interés",
    "Notas",
]
ENTIDADES_HEADERS = ["Nombre", "Notas", "Activo"]
ASISTENTE_HEADERS = [
    "ID Expediente",
    "Enlace",
    "Título",
    "Órgano",
    "Bloque",
    "Datos JSON",
    "Formato JSON",
    "Exigencias Drive",
    "Borrador Drive",
    "Verificación Drive",
    "Paquete Drive",
    "Actualizado",
]

#: Valor inicial de la columna editable de seguimiento.
DEFAULT_TRACKING = "Pendiente de revisar"

SEGUIMIENTO_OPTIONS = (
    "Pendiente de revisar",
    "En estudio",
    "Presentada",
    "Descartada",
    "Adjudicada a terceros",
    "Ganada",
)

CHECKLIST_ESTADOS = (
    "Pendiente",
    "En preparación",
    "Preparado",
    "No aplica",
)

#: Plantilla base de documentación a preparar al interesarse por una licitación.
CHECKLIST_PLANTILLA = (
    "DEUC / Declaración responsable",
    "Solvencia económica",
    "Solvencia técnica / experiencia",
    "Oferta económica",
    "Oferta técnica / memoria",
    "Garantías / seguros",
    "Documentación societaria (poderes, estatutos)",
    "Certificados AEAT y Seguridad Social",
    "Otros requisitos del pliego",
)

ACTIVO_OPTIONS = ("sí", "no")

HEADER_COLOR = {"red": 0.106, "green": 0.263, "blue": 0.196}  # #1B4332
HEADER_TEXT = {"red": 1.0, "green": 1.0, "blue": 1.0}

_LOCK = threading.Lock()
_SPREADSHEET_CACHE: dict[str, Any] = {}


class SheetsError(RuntimeError):
    """Fallo al hablar con la API de Google Sheets."""


# ---------------------------------------------------------------------------
# Configuración y credenciales
# ---------------------------------------------------------------------------
def _secret(*ruta: str) -> Any:
    """Lee un valor de ``st.secrets`` sin romper si no hay fichero de secretos."""
    try:
        import streamlit as st

        valor: Any = st.secrets
        for clave in ruta:
            if clave not in valor:
                return None
            valor = valor[clave]
        return valor
    except Exception:  # secrets.toml ausente o Streamlit fuera de contexto
        return None


def spreadsheet_id() -> str | None:
    """ID de la hoja, tomado de los secretos o de la variable de entorno."""
    return (
        _secret("sheets", "spreadsheet_id")
        or os.environ.get("GREFA_SPREADSHEET_ID")
        or None
    )


def is_configured() -> bool:
    return bool(spreadsheet_id())


def _credentials():
    """Credenciales de servicio, por orden de preferencia.

    1. Bloque ``[gcp_service_account]`` de ``.streamlit/secrets.toml``.
    2. Variable ``GOOGLE_SERVICE_ACCOUNT_JSON`` con el JSON completo.
    3. Variable ``GOOGLE_APPLICATION_CREDENTIALS`` con la ruta al fichero.
    4. Credenciales por defecto del entorno (ADC).
    """
    from google.oauth2.service_account import Credentials

    info = _secret("gcp_service_account")
    if info:
        return Credentials.from_service_account_info(dict(info), scopes=list(SCOPES))

    bruto = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if bruto:
        return Credentials.from_service_account_info(json.loads(bruto), scopes=list(SCOPES))

    ruta = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if ruta and os.path.exists(ruta):
        return Credentials.from_service_account_file(ruta, scopes=list(SCOPES))

    import google.auth

    credenciales, _ = google.auth.default(scopes=list(SCOPES))
    return credenciales


def get_spreadsheet(hoja_id: str | None = None):
    """Abre (y cachea) la hoja de cálculo configurada."""
    identificador = hoja_id or spreadsheet_id()
    if not identificador:
        raise SheetsError(
            "No hay hoja de Google configurada. Define GREFA_SPREADSHEET_ID o el "
            "bloque [sheets] en .streamlit/secrets.toml."
        )

    with _LOCK:
        if identificador in _SPREADSHEET_CACHE:
            return _SPREADSHEET_CACHE[identificador]
        import time

        import gspread

        ultimo: Exception | None = None
        for intento in range(6):
            try:
                cliente = gspread.authorize(_credentials())
                hoja = cliente.open_by_key(identificador)
                _SPREADSHEET_CACHE[identificador] = hoja
                return hoja
            except Exception as exc:
                ultimo = exc
                texto = str(exc).lower()
                if "429" in texto or "quota" in texto:
                    time.sleep(min(20 * (intento + 1), 90))
                    continue
                break
        raise SheetsError(
            "No se pudo abrir la hoja de cálculo. Revisa el ID y que la hoja esté "
            f"compartida como Editor con la cuenta de servicio. Detalle: {ultimo}"
        ) from ultimo


def reset_cache() -> None:
    with _LOCK:
        _SPREADSHEET_CACHE.clear()


# ---------------------------------------------------------------------------
# Utilidades internas
# ---------------------------------------------------------------------------
def _mensaje_api_sheets(exc: BaseException) -> str:
    texto = str(exc)
    bajo = texto.lower()
    if "429" in texto or "quota" in bajo or "rate" in bajo:
        return (
            "Cuota de Google Sheets agotada (demasiadas lecturas). "
            "Espera 60–90 segundos y reintenta."
        )
    if "403" in texto or "permission" in bajo or "forbidden" in bajo:
        return (
            "Sin permiso en Google Sheets. Comparte la hoja como Editor con la "
            "cuenta de servicio."
        )
    return texto or type(exc).__name__


def _worksheet(hoja, titulo: str, cabeceras: list[str]):
    """Devuelve la pestaña pedida, creándola con cabeceras si no existe."""
    pestana = None
    objetivo = str(titulo).strip().lower()
    try:
        try:
            for candidata in hoja.worksheets():
                if str(candidata.title).strip().lower() == objetivo:
                    pestana = candidata
                    break
        except Exception:
            pestana = None

        if pestana is None:
            try:
                pestana = hoja.worksheet(titulo)
            except Exception:
                pestana = None

        if pestana is None:
            try:
                pestana = hoja.add_worksheet(
                    title=titulo, rows=2000, cols=max(len(cabeceras), 10)
                )
                pestana.update([cabeceras], "A1")
                return pestana
            except Exception as exc:
                # Carrera típica: la pestaña existe pero worksheet() falló antes.
                msg = str(exc).lower()
                if "already exists" in msg:
                    try:
                        pestana = hoja.worksheet(titulo)
                    except Exception:
                        try:
                            for candidata in hoja.worksheets():
                                if str(candidata.title).strip().lower() == objetivo:
                                    pestana = candidata
                                    break
                        except Exception as exc2:
                            raise SheetsError(
                                f"No se pudo abrir la pestaña {titulo}: "
                                f"{_mensaje_api_sheets(exc2)}"
                            ) from exc2
                if pestana is None:
                    raise SheetsError(
                        f"No se pudo abrir/crear la pestaña {titulo}: "
                        f"{_mensaje_api_sheets(exc)}"
                    ) from exc

        try:
            valores = [v.strip() for v in pestana.row_values(1) if str(v).strip()]
        except Exception as exc:
            raise SheetsError(
                f"No se pudo leer cabeceras de {titulo}: {_mensaje_api_sheets(exc)}"
            ) from exc
        esperadas = [c.strip() for c in cabeceras]
        if [v.lower() for v in valores] != [c.lower() for c in esperadas]:
            # Solo reescribe cabeceras; no toca el resto de filas.
            try:
                pestana.update([cabeceras], "A1")
            except Exception as exc:
                LOGGER.warning("No se pudieron actualizar cabeceras de %s: %s", titulo, exc)
        return pestana
    except SheetsError:
        raise
    except Exception as exc:
        raise SheetsError(
            f"Error de Google Sheets con la pestaña {titulo}: {_mensaje_api_sheets(exc)}"
        ) from exc


def _es_activo(valor: Any) -> bool:
    return str(valor).strip().lower() not in {"no", "false", "0", "inactivo", "n"}


# ---------------------------------------------------------------------------
# Criterios: CPV y palabras clave
# ---------------------------------------------------------------------------
def load_criteria(hoja_id: str | None = None) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Lee los criterios activos (preferentemente desde los catálogos)."""
    try:
        from modules.sheets_catalog import load_selection

        cpvs, keywords, _, _ = load_selection(hoja_id)
        if cpvs or keywords:
            return cpvs, keywords
    except Exception as exc:
        LOGGER.debug("Catálogos no disponibles, se usa resumen CPV/PalabrasClave: %s", exc)

    hoja = get_spreadsheet(hoja_id)
    try:
        cpv_ws = _worksheet(hoja, CPV_SHEET, CPV_HEADERS)
        kw_ws = _worksheet(hoja, KEYWORDS_SHEET, KEYWORD_HEADERS)
        filas_cpv = cpv_ws.get_all_records()
        filas_kw = kw_ws.get_all_records()
    except SheetsError:
        raise
    except Exception as exc:
        raise SheetsError(f"Error leyendo los criterios de la hoja: {exc}") from exc

    cpvs: dict[str, str] = {}
    for fila in filas_cpv:
        codigo = str(_campo(fila, "Código CPV", "codigo")).strip()
        if codigo and _es_activo(_campo(fila, "Activo", "activo", default="sí")):
            cpvs[codigo] = (
                str(_campo(fila, "Descripción", "descripcion")).strip() or "Sin descripción"
            )

    keywords: dict[str, list[str]] = {}
    for fila in filas_kw:
        termino = str(_campo(fila, "Término", "Castellano", "termino")).strip()
        if not termino or not _es_activo(_campo(fila, "Activo", "activo", default="sí")):
            continue
        categoria = str(_campo(fila, "Categoría", "categoria")).strip() or "Sin categoría"
        keywords.setdefault(categoria, []).append(termino)

    return cpvs, keywords


def _campo(fila: dict[str, Any], *claves: str, default: Any = "") -> Any:
    """Lee un campo tolerando cabeceras en español o en snake_case antiguo."""
    for clave in claves:
        if clave in fila and fila[clave] not in (None, ""):
            return fila[clave]
    for clave in claves:
        if clave in fila:
            return fila[clave]
    return default


def save_criteria(
    cpvs: dict[str, str],
    keywords: dict[str, list[str]],
    hoja_id: str | None = None,
) -> None:
    """Vuelca los criterios actuales a la hoja (sobrescribe ambas pestañas)."""
    hoja = get_spreadsheet(hoja_id)
    try:
        cpv_ws = _worksheet(hoja, CPV_SHEET, CPV_HEADERS)
        kw_ws = _worksheet(hoja, KEYWORDS_SHEET, KEYWORD_HEADERS)

        filas_cpv = [[codigo, descripcion, "sí"] for codigo, descripcion in cpvs.items()]
        filas_kw = [
            [termino, categoria, "sí"]
            for categoria, terminos in keywords.items()
            for termino in terminos
        ]

        cpv_ws.clear()
        cpv_ws.update([CPV_HEADERS] + filas_cpv, "A1")
        kw_ws.clear()
        kw_ws.update([KEYWORD_HEADERS] + filas_kw, "A1")
    except SheetsError:
        raise
    except Exception as exc:
        raise SheetsError(f"Error guardando los criterios en la hoja: {exc}") from exc


# ---------------------------------------------------------------------------
# Oportunidades detectadas
# ---------------------------------------------------------------------------
def _clave(expediente: str, enlace: str) -> str:
    return f"{str(expediente).strip().lower()}|{str(enlace).strip().lower()}"


def _fila_oportunidad(fila: pd.Series, momento: str) -> list[str]:
    def texto(valor: Any) -> str:
        if valor is None or (isinstance(valor, float) and pd.isna(valor)):
            return ""
        if isinstance(valor, (list, tuple)):
            return ", ".join(str(elemento) for elemento in valor)
        return str(valor)

    presupuesto = fila.get("presupuesto_sin_iva")
    return [
        momento,
        texto(fila.get("relevancia")),
        texto(fila.get("categoria")),
        texto(fila.get("expediente")),
        texto(fila.get("titulo")),
        texto(fila.get("organo_contratacion")),
        "" if presupuesto is None or pd.isna(presupuesto) else f"{float(presupuesto):.2f}",
        texto(fila.get("ubicacion")),
        texto(fila.get("cpvs")),
        texto(fila.get("keywords_match")),
        texto(fila.get("fecha_limite")),
        texto(fila.get("estado")),
        texto(fila.get("url")),
        DEFAULT_TRACKING,
        "",
    ]


def append_opportunities(df: pd.DataFrame, hoja_id: str | None = None) -> tuple[int, int]:
    """Añade las oportunidades que aún no estén en la hoja.

    Returns:
        Tupla (añadidas, omitidas por duplicado).
    """
    if df.empty:
        return 0, 0

    hoja = get_spreadsheet(hoja_id)
    try:
        pestana = _worksheet(hoja, OPPORTUNITIES_SHEET, OPPORTUNITY_HEADERS)
        existentes = {
            _clave(
                _campo(registro, "ID Expediente", "expediente"),
                _campo(registro, "Enlace", "enlace"),
            )
            for registro in pestana.get_all_records()
        }

        momento = datetime.now().strftime("%d/%m/%Y %H:%M")
        nuevas: list[list[str]] = []
        omitidas = 0
        for _, fila in df.iterrows():
            if _clave(fila.get("expediente", ""), fila.get("url", "")) in existentes:
                omitidas += 1
                continue
            nuevas.append(_fila_oportunidad(fila, momento))

        if nuevas:
            pestana.append_rows(nuevas, value_input_option="USER_ENTERED")
        return len(nuevas), omitidas
    except SheetsError:
        raise
    except Exception as exc:
        raise SheetsError(f"Error escribiendo las oportunidades en la hoja: {exc}") from exc


def spreadsheet_url(hoja_id: str | None = None) -> str:
    identificador = hoja_id or spreadsheet_id() or ""
    return f"https://docs.google.com/spreadsheets/d/{identificador}" if identificador else ""


def load_opportunities_tracking(hoja_id: str | None = None) -> dict[str, dict[str, Any]]:
    """Lee la pestaña Oportunidades indexada por clave expediente|enlace."""
    hoja = get_spreadsheet(hoja_id)
    try:
        pestana = _worksheet(hoja, OPPORTUNITIES_SHEET, OPPORTUNITY_HEADERS)
        registros = pestana.get_all_records()
    except SheetsError:
        raise
    except Exception as exc:
        raise SheetsError(f"Error leyendo oportunidades de la hoja: {exc}") from exc

    resultado: dict[str, dict[str, Any]] = {}
    for indice, registro in enumerate(registros, start=2):
        expediente = str(_campo(registro, "ID Expediente", "expediente")).strip()
        enlace = str(_campo(registro, "Enlace", "enlace")).strip()
        if not expediente and not enlace:
            continue
        clave = _clave(expediente, enlace)
        resultado[clave] = {
            "row": indice,
            "expediente": expediente,
            "titulo": str(_campo(registro, "Título / Objeto", "titulo")).strip(),
            "seguimiento": str(
                _campo(registro, "Seguimiento", default=DEFAULT_TRACKING) or DEFAULT_TRACKING
            ).strip(),
            "notas": str(_campo(registro, "Notas", "notas")).strip(),
            "categoria": str(_campo(registro, "Categoría", "categoria")).strip(),
            "relevancia": str(_campo(registro, "Relevancia (%)", "relevancia")).strip(),
            "url": enlace,
            "organo": str(_campo(registro, "Órgano de Contratación", "organo")).strip(),
            "fecha_deteccion": str(_campo(registro, "Fecha detección", "fecha_deteccion")).strip(),
        }
    return resultado


def update_opportunity_tracking(
    expediente: str,
    enlace: str,
    *,
    seguimiento: str,
    notas: str,
    hoja_id: str | None = None,
) -> None:
    """Actualiza Seguimiento y Notas de una fila existente."""
    if seguimiento not in SEGUIMIENTO_OPTIONS:
        raise SheetsError(f"Estado de seguimiento no válido: {seguimiento}")

    hoja = get_spreadsheet(hoja_id)
    try:
        pestana = _worksheet(hoja, OPPORTUNITIES_SHEET, OPPORTUNITY_HEADERS)
        clave_objetivo = _clave(expediente, enlace)
        fila_encontrada: int | None = None
        for indice, registro in enumerate(pestana.get_all_records(), start=2):
            clave = _clave(
                _campo(registro, "ID Expediente", "expediente"),
                _campo(registro, "Enlace", "enlace"),
            )
            if clave == clave_objetivo:
                fila_encontrada = indice
                break
        if fila_encontrada is None:
            raise SheetsError("Expediente no encontrado en la pestaña Oportunidades.")

        pestana.update_cell(fila_encontrada, 14, seguimiento)
        pestana.update_cell(fila_encontrada, 15, notas)
    except SheetsError:
        raise
    except Exception as exc:
        raise SheetsError(f"Error actualizando el seguimiento: {exc}") from exc


def load_pliego_resumen(
    expediente: str,
    enlace: str,
    hoja_id: str | None = None,
) -> str | None:
    """Devuelve el resumen guardado para un expediente, o None."""
    hoja = get_spreadsheet(hoja_id)
    try:
        pestana = _worksheet(hoja, PLIEGOS_SHEET, PLIEGO_HEADERS)
        clave_objetivo = _clave(expediente, enlace)
        for registro in pestana.get_all_records():
            clave = _clave(
                _campo(registro, "ID Expediente", "expediente"),
                _campo(registro, "Enlace", "enlace"),
            )
            if clave == clave_objetivo:
                resumen = str(_campo(registro, "Resumen", "resumen")).strip()
                return resumen or None
    except Exception as exc:
        LOGGER.debug("No se pudo leer resumen de pliego: %s", exc)
    return None


def save_pliego_resumen(
    expediente: str,
    enlace: str,
    titulo: str,
    resumen: str,
    hoja_id: str | None = None,
) -> None:
    """Guarda o actualiza el resumen IA en la pestaña Pliegos."""
    if not resumen.strip():
        raise SheetsError("El resumen está vacío.")

    hoja = get_spreadsheet(hoja_id)
    momento = datetime.now().strftime("%d/%m/%Y %H:%M")
    fila = [expediente, enlace, titulo, resumen.strip(), momento]
    clave_objetivo = _clave(expediente, enlace)

    try:
        pestana = _worksheet(hoja, PLIEGOS_SHEET, PLIEGO_HEADERS)
        registros = pestana.get_all_records()
        for indice, registro in enumerate(registros, start=2):
            clave = _clave(
                _campo(registro, "ID Expediente", "expediente"),
                _campo(registro, "Enlace", "enlace"),
            )
            if clave == clave_objetivo:
                pestana.update(f"A{indice}:E{indice}", [fila], value_input_option="USER_ENTERED")
                return
        pestana.append_row(fila, value_input_option="USER_ENTERED")
    except SheetsError:
        raise
    except Exception as exc:
        raise SheetsError(f"Error guardando el resumen del pliego: {exc}") from exc


def delete_pliego_resumen(
    expediente: str,
    enlace: str,
    hoja_id: str | None = None,
) -> bool:
    """Elimina el resumen guardado del expediente. Devuelve True si había fila."""
    hoja = get_spreadsheet(hoja_id)
    clave_objetivo = _clave(expediente, enlace)
    try:
        pestana = _worksheet(hoja, PLIEGOS_SHEET, PLIEGO_HEADERS)
        registros = pestana.get_all_records()
        for indice, registro in enumerate(registros, start=2):
            clave = _clave(
                _campo(registro, "ID Expediente", "expediente"),
                _campo(registro, "Enlace", "enlace"),
            )
            if clave == clave_objetivo:
                pestana.delete_rows(indice)
                return True
    except SheetsError:
        raise
    except Exception as exc:
        raise SheetsError(f"Error borrando el resumen del pliego: {exc}") from exc
    return False


def load_pliegos_index(hoja_id: str | None = None) -> dict[str, str]:
    """Mapa clave expediente|enlace → fecha del último análisis."""
    hoja = get_spreadsheet(hoja_id)
    try:
        pestana = _worksheet(hoja, PLIEGOS_SHEET, PLIEGO_HEADERS)
        indice: dict[str, str] = {}
        for registro in pestana.get_all_records():
            clave = _clave(
                _campo(registro, "ID Expediente", "expediente"),
                _campo(registro, "Enlace", "enlace"),
            )
            if clave.strip("|"):
                indice[clave] = str(_campo(registro, "Fecha análisis", "fecha_analisis")).strip()
        return indice
    except Exception as exc:
        LOGGER.debug("Pestaña Pliegos no disponible: %s", exc)
        return {}


def _normalizar_item_checklist(texto: str) -> str:
    return " ".join(str(texto or "").strip().split())


def parse_documentacion_desde_resumen(resumen: str) -> list[str]:
    """Extrae viñetas de la sección «Documentación a presentar» de un resumen IA."""
    if not resumen or not str(resumen).strip():
        return []
    texto = str(resumen)
    m = re.search(
        r"##\s*Documentaci[oó]n a presentar\s*\n(.*?)(?=\n##\s|\Z)",
        texto,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return []
    bloque = m.group(1)
    items: list[str] = []
    for linea in bloque.splitlines():
        limpia = linea.strip()
        limpia = re.sub(r"^[-*•]\s+", "", limpia)
        limpia = re.sub(r"^\d+[.)]\s+", "", limpia).strip()
        if len(limpia) < 4:
            continue
        if limpia.lower() in {"no consta", "ninguno", "n/a"}:
            continue
        items.append(_normalizar_item_checklist(limpia)[:200])
    # Deduplicar preservando orden
    vistos: set[str] = set()
    out: list[str] = []
    for item in items:
        clave = item.lower()
        if clave in vistos:
            continue
        vistos.add(clave)
        out.append(item)
    return out[:25]


def load_checklist(
    expediente: str,
    enlace: str,
    hoja_id: str | None = None,
) -> list[dict[str, str]]:
    """Ítems de checklist de documentación para un expediente."""
    try:
        hoja = get_spreadsheet(hoja_id)
        pestana = _worksheet(hoja, CHECKLIST_SHEET, CHECKLIST_HEADERS)
        clave_objetivo = _clave(expediente, enlace)
        filas: list[dict[str, str]] = []
        registros = pestana.get_all_records()
        for i, registro in enumerate(registros, start=2):
            if _clave(
                _campo(registro, "ID Expediente", "expediente"),
                _campo(registro, "Enlace", "enlace"),
            ) != clave_objetivo:
                continue
            filas.append(
                {
                    "expediente": str(_campo(registro, "ID Expediente", "expediente")),
                    "url": str(_campo(registro, "Enlace", "enlace")),
                    "titulo": str(_campo(registro, "Título", "titulo")),
                    "documento": str(_campo(registro, "Documento", "documento")),
                    "estado": str(_campo(registro, "Estado", "estado")) or "Pendiente",
                    "notas": str(_campo(registro, "Notas", "notas")),
                    "enlace_drive": str(
                        _campo(registro, "Enlace Drive", "enlace_drive", "drive")
                    ),
                    "fecha": str(
                        _campo(registro, "Fecha actualización", "fecha_actualizacion")
                    ),
                    "_row": str(i),
                }
            )
        return filas
    except SheetsError:
        raise
    except Exception as exc:
        raise SheetsError(
            f"No se pudo leer ChecklistDocs: {_mensaje_api_sheets(exc)}"
        ) from exc


def ensure_checklist(
    expediente: str,
    enlace: str,
    titulo: str = "",
    *,
    items: list[str] | None = None,
    hoja_id: str | None = None,
) -> list[dict[str, str]]:
    """Crea el checklist si no existe (plantilla + ítems extra del pliego)."""
    existentes = load_checklist(expediente, enlace, hoja_id=hoja_id)
    if existentes:
        return existentes

    plantilla = list(CHECKLIST_PLANTILLA)
    extras = [_normalizar_item_checklist(x) for x in (items or []) if str(x).strip()]
    vistos = {p.lower() for p in plantilla}
    for extra in extras:
        if extra.lower() not in vistos:
            plantilla.append(extra)
            vistos.add(extra.lower())

    hoja = get_spreadsheet(hoja_id)
    pestana = _worksheet(hoja, CHECKLIST_SHEET, CHECKLIST_HEADERS)
    momento = datetime.now().strftime("%d/%m/%Y %H:%M")
    filas = [
        [expediente, enlace, titulo, doc, "Pendiente", "", "", momento]
        for doc in plantilla
    ]
    try:
        pestana.append_rows(filas, value_input_option="USER_ENTERED")
    except Exception:
        for fila in filas:
            pestana.append_row(fila, value_input_option="USER_ENTERED")
    return load_checklist(expediente, enlace, hoja_id=hoja_id)


def load_mis_licitaciones(hoja_id: str | None = None) -> list[dict[str, str]]:
    """Licitaciones marcadas como de interés por el equipo."""
    try:
        hoja = get_spreadsheet(hoja_id)
        pestana = _worksheet(hoja, MIS_LICITACIONES_SHEET, MIS_LICITACIONES_HEADERS)
        filas: list[dict[str, str]] = []
        for i, registro in enumerate(pestana.get_all_records(), start=2):
            expediente = str(_campo(registro, "ID Expediente", "expediente")).strip()
            enlace = str(_campo(registro, "Enlace", "enlace", "url")).strip()
            if not expediente and not enlace:
                continue
            interesa = str(_campo(registro, "Me interesa", "me_interesa")).strip().lower()
            if interesa in {"no", "false", "0", "n"}:
                continue
            filas.append(
                {
                    "expediente": expediente,
                    "url": enlace,
                    "titulo": str(_campo(registro, "Título", "titulo")),
                    "organo": str(
                        _campo(registro, "Órgano de Contratación", "organo", "organo_contratacion")
                    ),
                    "presupuesto": str(
                        _campo(registro, "Presupuesto sin IVA", "presupuesto")
                    ),
                    "estado": str(_campo(registro, "Estado PLACSP", "estado")),
                    "relevancia": str(_campo(registro, "Relevancia (%)", "relevancia")),
                    "me_interesa": "sí",
                    "me_presento": (
                        "sí"
                        if str(_campo(registro, "Me presento", "me_presento")).strip().lower()
                        in {"sí", "si", "yes", "true", "1"}
                        else "no"
                    ),
                    "fecha_interes": str(_campo(registro, "Fecha interés", "fecha_interes")),
                    "notas": str(_campo(registro, "Notas", "notas")),
                    "_row": str(i),
                }
            )
        return filas
    except SheetsError:
        raise
    except Exception as exc:
        raise SheetsError(
            f"No se pudo leer MisLicitaciones: {_mensaje_api_sheets(exc)}"
        ) from exc


def upsert_mi_licitacion(
    expediente: str,
    enlace: str,
    *,
    titulo: str = "",
    organo: str = "",
    presupuesto: str = "",
    estado: str = "",
    relevancia: str = "",
    me_interesa: bool = True,
    me_presento: bool | None = None,
    notas: str | None = None,
    hoja_id: str | None = None,
) -> None:
    """Añade o actualiza una licitación en MisLicitaciones."""
    hoja = get_spreadsheet(hoja_id)
    pestana = _worksheet(hoja, MIS_LICITACIONES_SHEET, MIS_LICITACIONES_HEADERS)
    clave_objetivo = _clave(expediente, enlace)
    momento = datetime.now().strftime("%d/%m/%Y %H:%M")
    try:
        registros = pestana.get_all_records()
        for indice, registro in enumerate(registros, start=2):
            if _clave(
                _campo(registro, "ID Expediente", "expediente"),
                _campo(registro, "Enlace", "enlace", "url"),
            ) != clave_objetivo:
                continue
            presento_actual = str(_campo(registro, "Me presento", "me_presento")).strip()
            notas_actual = str(_campo(registro, "Notas", "notas"))
            fecha_actual = str(_campo(registro, "Fecha interés", "fecha_interes")) or momento
            presento = (
                ("sí" if me_presento else "no")
                if me_presento is not None
                else (
                    "sí"
                    if presento_actual.lower() in {"sí", "si", "yes", "true", "1"}
                    else "no"
                )
            )
            fila = [
                expediente,
                enlace,
                titulo or str(_campo(registro, "Título", "titulo")),
                organo
                or str(_campo(registro, "Órgano de Contratación", "organo")),
                presupuesto
                or str(_campo(registro, "Presupuesto sin IVA", "presupuesto")),
                estado or str(_campo(registro, "Estado PLACSP", "estado")),
                relevancia or str(_campo(registro, "Relevancia (%)", "relevancia")),
                "sí" if me_interesa else "no",
                presento,
                fecha_actual if me_interesa else "",
                notas if notas is not None else notas_actual,
            ]
            pestana.update(
                f"A{indice}:K{indice}",
                [fila],
                value_input_option="USER_ENTERED",
            )
            return
        if not me_interesa:
            return
        fila = [
            expediente,
            enlace,
            titulo,
            organo,
            presupuesto,
            estado,
            relevancia,
            "sí",
            "sí" if me_presento else "no",
            momento,
            notas or "",
        ]
        pestana.append_row(fila, value_input_option="USER_ENTERED")
    except SheetsError:
        raise
    except Exception as exc:
        raise SheetsError(
            f"Error guardando MisLicitaciones: {_mensaje_api_sheets(exc)}"
        ) from exc


def claves_mis_licitaciones(hoja_id: str | None = None) -> set[str]:
    """Conjunto de claves expediente|url marcadas como interés."""
    try:
        return {
            _clave(f.get("expediente", ""), f.get("url", ""))
            for f in load_mis_licitaciones(hoja_id=hoja_id)
        }
    except Exception:
        return set()


# ---------------------------------------------------------------------------
# Convocatorias BDNS (ayudas y premios)
# ---------------------------------------------------------------------------
def _fila_oportunidad_ayuda(fila: pd.Series, momento: str) -> list[str]:
    def texto(valor: Any) -> str:
        if valor is None or (isinstance(valor, float) and pd.isna(valor)):
            return ""
        if isinstance(valor, (list, tuple)):
            return ", ".join(str(elemento) for elemento in valor)
        return str(valor)

    presupuesto = fila.get("presupuesto_sin_iva")
    return [
        momento,
        texto(fila.get("relevancia")),
        texto(fila.get("categoria")),
        texto(fila.get("expediente")),
        texto(fila.get("titulo")),
        texto(fila.get("organo_contratacion")),
        "" if presupuesto is None or pd.isna(presupuesto) else f"{float(presupuesto):.2f}",
        texto(fila.get("ubicacion") or fila.get("nivel_admin")),
        texto(fila.get("tipo_contrato") or fila.get("instrumentos")),
        texto(fila.get("keywords_match")),
        texto(fila.get("fecha_limite")),
        texto(fila.get("estado")),
        texto(fila.get("url")),
        DEFAULT_TRACKING,
        "",
    ]


def append_opportunities_ayudas(
    df: pd.DataFrame, hoja_id: str | None = None
) -> tuple[int, int]:
    """Añade oportunidades de ayudas/premios sin duplicar código+enlace."""
    if df.empty:
        return 0, 0

    hoja = get_spreadsheet(hoja_id)
    try:
        pestana = _worksheet(hoja, OPPORTUNITIES_AYUDAS_SHEET, OPPORTUNITY_AYUDAS_HEADERS)
        existentes = {
            _clave(
                _campo(registro, "Código BDNS", "ID Expediente", "expediente"),
                _campo(registro, "Enlace", "enlace"),
            )
            for registro in pestana.get_all_records()
        }
        momento = datetime.now().strftime("%d/%m/%Y %H:%M")
        nuevas: list[list[str]] = []
        omitidas = 0
        for _, fila in df.iterrows():
            if _clave(fila.get("expediente", ""), fila.get("url", "")) in existentes:
                omitidas += 1
                continue
            nuevas.append(_fila_oportunidad_ayuda(fila, momento))
        if nuevas:
            pestana.append_rows(nuevas, value_input_option="USER_ENTERED")
        return len(nuevas), omitidas
    except SheetsError:
        raise
    except Exception as exc:
        raise SheetsError(f"Error escribiendo OportunidadesAyudas: {exc}") from exc


def load_opportunities_tracking_ayudas(
    hoja_id: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Lee OportunidadesAyudas indexada por clave código|enlace."""
    hoja = get_spreadsheet(hoja_id)
    try:
        pestana = _worksheet(hoja, OPPORTUNITIES_AYUDAS_SHEET, OPPORTUNITY_AYUDAS_HEADERS)
        registros = pestana.get_all_records()
    except SheetsError:
        raise
    except Exception as exc:
        raise SheetsError(f"Error leyendo OportunidadesAyudas: {exc}") from exc

    resultado: dict[str, dict[str, Any]] = {}
    for indice, registro in enumerate(registros, start=2):
        expediente = str(
            _campo(registro, "Código BDNS", "ID Expediente", "expediente")
        ).strip()
        enlace = str(_campo(registro, "Enlace", "enlace")).strip()
        if not expediente and not enlace:
            continue
        clave = _clave(expediente, enlace)
        resultado[clave] = {
            "row": indice,
            "expediente": expediente,
            "titulo": str(_campo(registro, "Título / Objeto", "titulo")).strip(),
            "seguimiento": str(
                _campo(registro, "Seguimiento", default=DEFAULT_TRACKING) or DEFAULT_TRACKING
            ).strip(),
            "notas": str(_campo(registro, "Notas", "notas")).strip(),
            "categoria": str(_campo(registro, "Categoría", "categoria")).strip(),
            "relevancia": str(_campo(registro, "Relevancia (%)", "relevancia")).strip(),
            "url": enlace,
            "organo": str(_campo(registro, "Órgano convocante", "organo")).strip(),
            "fecha_deteccion": str(
                _campo(registro, "Fecha detección", "fecha_deteccion")
            ).strip(),
        }
    return resultado


def update_opportunity_tracking_ayudas(
    expediente: str,
    enlace: str,
    *,
    seguimiento: str,
    notas: str,
    hoja_id: str | None = None,
) -> None:
    if seguimiento not in SEGUIMIENTO_OPTIONS:
        raise SheetsError(f"Estado de seguimiento no válido: {seguimiento}")

    hoja = get_spreadsheet(hoja_id)
    try:
        pestana = _worksheet(hoja, OPPORTUNITIES_AYUDAS_SHEET, OPPORTUNITY_AYUDAS_HEADERS)
        clave_objetivo = _clave(expediente, enlace)
        fila_encontrada: int | None = None
        for indice, registro in enumerate(pestana.get_all_records(), start=2):
            clave = _clave(
                _campo(registro, "Código BDNS", "ID Expediente", "expediente"),
                _campo(registro, "Enlace", "enlace"),
            )
            if clave == clave_objetivo:
                fila_encontrada = indice
                break
        if fila_encontrada is None:
            raise SheetsError("Convocatoria no encontrada en OportunidadesAyudas.")
        pestana.update_cell(fila_encontrada, 14, seguimiento)
        pestana.update_cell(fila_encontrada, 15, notas)
    except SheetsError:
        raise
    except Exception as exc:
        raise SheetsError(f"Error actualizando seguimiento de ayudas: {exc}") from exc


def load_mis_convocatorias(hoja_id: str | None = None) -> list[dict[str, str]]:
    try:
        hoja = get_spreadsheet(hoja_id)
        pestana = _worksheet(hoja, MIS_CONVOCATORIAS_SHEET, MIS_CONVOCATORIAS_HEADERS)
        filas: list[dict[str, str]] = []
        for i, registro in enumerate(pestana.get_all_records(), start=2):
            expediente = str(
                _campo(registro, "Código BDNS", "ID Expediente", "expediente")
            ).strip()
            enlace = str(_campo(registro, "Enlace", "enlace", "url")).strip()
            if not expediente and not enlace:
                continue
            interesa = str(_campo(registro, "Me interesa", "me_interesa")).strip().lower()
            if interesa in {"no", "false", "0", "n"}:
                continue
            filas.append(
                {
                    "expediente": expediente,
                    "url": enlace,
                    "titulo": str(_campo(registro, "Título", "titulo")),
                    "organo": str(
                        _campo(registro, "Órgano convocante", "organo", "organo_contratacion")
                    ),
                    "presupuesto": str(
                        _campo(registro, "Presupuesto total", "Presupuesto sin IVA", "presupuesto")
                    ),
                    "estado": str(_campo(registro, "Estado", "estado")),
                    "relevancia": str(_campo(registro, "Relevancia (%)", "relevancia")),
                    "me_interesa": "sí",
                    "me_presento": (
                        "sí"
                        if str(_campo(registro, "Me presento", "me_presento")).strip().lower()
                        in {"sí", "si", "yes", "true", "1"}
                        else "no"
                    ),
                    "fecha_interes": str(_campo(registro, "Fecha interés", "fecha_interes")),
                    "notas": str(_campo(registro, "Notas", "notas")),
                    "_row": str(i),
                }
            )
        return filas
    except SheetsError:
        raise
    except Exception as exc:
        raise SheetsError(
            f"No se pudo leer MisConvocatorias: {_mensaje_api_sheets(exc)}"
        ) from exc


def upsert_mi_convocatoria(
    expediente: str,
    enlace: str,
    *,
    titulo: str = "",
    organo: str = "",
    presupuesto: str = "",
    estado: str = "",
    relevancia: str = "",
    me_interesa: bool = True,
    me_presento: bool | None = None,
    notas: str | None = None,
    hoja_id: str | None = None,
) -> None:
    hoja = get_spreadsheet(hoja_id)
    pestana = _worksheet(hoja, MIS_CONVOCATORIAS_SHEET, MIS_CONVOCATORIAS_HEADERS)
    clave_objetivo = _clave(expediente, enlace)
    momento = datetime.now().strftime("%d/%m/%Y %H:%M")
    try:
        registros = pestana.get_all_records()
        for indice, registro in enumerate(registros, start=2):
            if _clave(
                _campo(registro, "Código BDNS", "ID Expediente", "expediente"),
                _campo(registro, "Enlace", "enlace", "url"),
            ) != clave_objetivo:
                continue
            presento_actual = str(_campo(registro, "Me presento", "me_presento")).strip()
            notas_actual = str(_campo(registro, "Notas", "notas"))
            fecha_actual = str(_campo(registro, "Fecha interés", "fecha_interes")) or momento
            presento = (
                ("sí" if me_presento else "no")
                if me_presento is not None
                else (
                    "sí"
                    if presento_actual.lower() in {"sí", "si", "yes", "true", "1"}
                    else "no"
                )
            )
            fila = [
                expediente,
                enlace,
                titulo or str(_campo(registro, "Título", "titulo")),
                organo or str(_campo(registro, "Órgano convocante", "organo")),
                presupuesto
                or str(_campo(registro, "Presupuesto total", "presupuesto")),
                estado or str(_campo(registro, "Estado", "estado")),
                relevancia or str(_campo(registro, "Relevancia (%)", "relevancia")),
                "sí" if me_interesa else "no",
                presento,
                fecha_actual if me_interesa else "",
                notas if notas is not None else notas_actual,
            ]
            pestana.update(
                f"A{indice}:K{indice}",
                [fila],
                value_input_option="USER_ENTERED",
            )
            return
        if not me_interesa:
            return
        fila = [
            expediente,
            enlace,
            titulo,
            organo,
            presupuesto,
            estado,
            relevancia,
            "sí",
            "sí" if me_presento else "no",
            momento,
            notas or "",
        ]
        pestana.append_row(fila, value_input_option="USER_ENTERED")
    except SheetsError:
        raise
    except Exception as exc:
        raise SheetsError(
            f"Error guardando MisConvocatorias: {_mensaje_api_sheets(exc)}"
        ) from exc


def load_entidades_ayudas(hoja_id: str | None = None) -> list[dict[str, Any]]:
    """Lee el catálogo de entidades vigiladas (BDNS + web)."""
    hoja = get_spreadsheet(hoja_id)
    try:
        pestana = _worksheet(hoja, ENTIDADES_SHEET, ENTIDADES_HEADERS)
        filas: list[dict[str, Any]] = []
        for registro in pestana.get_all_records():
            nombre = str(_campo(registro, "Nombre", "nombre")).strip()
            if not nombre:
                continue
            filas.append(
                {
                    "nombre": nombre,
                    "notas": str(_campo(registro, "Notas", "notas")).strip(),
                    "activo": _es_activo(_campo(registro, "Activo", "activo", default="sí")),
                }
            )
        return filas
    except SheetsError:
        raise
    except Exception as exc:
        raise SheetsError(
            f"No se pudo leer EntidadesAyudas: {_mensaje_api_sheets(exc)}"
        ) from exc


def save_entidades_ayudas(
    entidades: list[dict[str, Any]],
    hoja_id: str | None = None,
) -> None:
    """Sobrescribe la pestaña EntidadesAyudas."""
    hoja = get_spreadsheet(hoja_id)
    try:
        pestana = _worksheet(hoja, ENTIDADES_SHEET, ENTIDADES_HEADERS)
        filas = [
            [
                str(e.get("nombre") or "").strip(),
                str(e.get("notas") or "").strip(),
                "sí" if e.get("activo", True) else "no",
            ]
            for e in entidades
            if str(e.get("nombre") or "").strip()
        ]
        pestana.clear()
        pestana.update([ENTIDADES_HEADERS] + filas, "A1")
    except SheetsError:
        raise
    except Exception as exc:
        raise SheetsError(
            f"Error guardando EntidadesAyudas: {_mensaje_api_sheets(exc)}"
        ) from exc


def upsert_checklist_item(
    expediente: str,
    enlace: str,
    documento: str,
    *,
    titulo: str = "",
    estado: str = "Pendiente",
    notas: str = "",
    enlace_drive: str = "",
    row: int | None = None,
    hoja_id: str | None = None,
) -> None:
    """Crea o actualiza un ítem del checklist."""
    documento = _normalizar_item_checklist(documento)
    if not documento:
        raise SheetsError("El nombre del documento está vacío.")
    if estado not in CHECKLIST_ESTADOS:
        estado = "Pendiente"

    hoja = get_spreadsheet(hoja_id)
    pestana = _worksheet(hoja, CHECKLIST_SHEET, CHECKLIST_HEADERS)
    momento = datetime.now().strftime("%d/%m/%Y %H:%M")
    fila = [
        expediente,
        enlace,
        titulo,
        documento,
        estado,
        notas,
        enlace_drive,
        momento,
    ]
    clave_objetivo = _clave(expediente, enlace)
    try:
        if row and int(row) >= 2:
            pestana.update(
                f"A{int(row)}:H{int(row)}",
                [fila],
                value_input_option="USER_ENTERED",
            )
            return
        registros = pestana.get_all_records()
        for indice, registro in enumerate(registros, start=2):
            misma = _clave(
                _campo(registro, "ID Expediente", "expediente"),
                _campo(registro, "Enlace", "enlace"),
            ) == clave_objetivo
            mismo_doc = _normalizar_item_checklist(
                _campo(registro, "Documento", "documento")
            ).lower() == documento.lower()
            if misma and mismo_doc:
                pestana.update(
                    f"A{indice}:H{indice}",
                    [fila],
                    value_input_option="USER_ENTERED",
                )
                return
        pestana.append_row(fila, value_input_option="USER_ENTERED")
    except SheetsError:
        raise
    except Exception as exc:
        raise SheetsError(f"Error guardando checklist: {exc}") from exc


# ---------------------------------------------------------------------------
# Inicialización completa del libro
# ---------------------------------------------------------------------------
def _format_header(pestana, num_columnas: int) -> None:
    from gspread.utils import rowcol_to_a1

    rango = f"A1:{rowcol_to_a1(1, num_columnas)}"
    pestana.format(
        rango,
        {
            "backgroundColor": HEADER_COLOR,
            "textFormat": {"foregroundColor": HEADER_TEXT, "bold": True},
            "horizontalAlignment": "CENTER",
            "verticalAlignment": "MIDDLE",
        },
    )
    pestana.freeze(rows=1)
    try:
        pestana.set_basic_filter(rango)
    except Exception:
        LOGGER.debug("No se pudo activar el filtro automático en %s", pestana.title)


def _resize_columns(pestana, anchos: list[int]) -> None:
    peticiones = []
    for indice, ancho in enumerate(anchos):
        peticiones.append(
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": pestana.id,
                        "dimension": "COLUMNS",
                        "startIndex": indice,
                        "endIndex": indice + 1,
                    },
                    "properties": {"pixelSize": ancho},
                    "fields": "pixelSize",
                }
            }
        )
    if peticiones:
        pestana.spreadsheet.batch_update({"requests": peticiones})


def _data_validation(pestana, columna: int, opciones: tuple[str, ...], filas: int = 1000) -> None:
    from gspread.utils import rowcol_to_a1

    inicio = rowcol_to_a1(2, columna)
    fin = rowcol_to_a1(filas, columna)
    regla = {
        "requests": [
            {
                "setDataValidation": {
                    "range": {
                        "sheetId": pestana.id,
                        "startRowIndex": 1,
                        "endRowIndex": filas,
                        "startColumnIndex": columna - 1,
                        "endColumnIndex": columna,
                    },
                    "rule": {
                        "condition": {
                            "type": "ONE_OF_LIST",
                            "values": [{"userEnteredValue": opcion} for opcion in opciones],
                        },
                        "showCustomUi": True,
                        "strict": True,
                    },
                }
            }
        ]
    }
    pestana.spreadsheet.batch_update(regla)
    LOGGER.debug("Validación %s:%s -> %s", inicio, fin, opciones)


def _ensure_named_sheets(hoja) -> dict[str, Any]:
    """Garantiza las pestañas de trabajo y elimina la hoja vacía por defecto si sobra."""
    existentes = {p.title: p for p in hoja.worksheets()}
    resultado: dict[str, Any] = {}

    for titulo, cabeceras, filas in (
        (CPV_SHEET, CPV_HEADERS, 100),
        (KEYWORDS_SHEET, KEYWORD_HEADERS, 200),
        (OPPORTUNITIES_SHEET, OPPORTUNITY_HEADERS, 2000),
        (PLIEGOS_SHEET, PLIEGO_HEADERS, 500),
        (CHECKLIST_SHEET, CHECKLIST_HEADERS, 2000),
        (MIS_LICITACIONES_SHEET, MIS_LICITACIONES_HEADERS, 1000),
        (ASISTENTE_SHEET, ASISTENTE_HEADERS, 2000),
        (README_SHEET, ["Instrucciones"], 40),
    ):
        if titulo in existentes:
            pestana = existentes[titulo]
        else:
            pestana = hoja.add_worksheet(title=titulo, rows=filas, cols=max(len(cabeceras), 8))
        resultado[titulo] = pestana

    # Si queda la hoja "Hoja 1" vacía y ya tenemos las nuestras, la borramos.
    for sobrante in list(hoja.worksheets()):
        if sobrante.title in resultado:
            continue
        if sobrante.title.lower() in {"hoja 1", "sheet1", "hoja1"} and len(hoja.worksheets()) > 1:
            try:
                hoja.del_worksheet(sobrante)
            except Exception:
                LOGGER.debug("No se pudo eliminar la pestaña sobrante %s", sobrante.title)

    return resultado


def initialize_spreadsheet(
    hoja_id: str | None = None,
    sembrar_criterios: bool = True,
) -> dict[str, int]:
    """Crea pestañas, cabeceras, validaciones y datos iniciales de GREFA.

    Returns:
        Contadores: ``{"cpvs": N, "keywords": N, "oportunidades": 0}``.
    """
    from config.default_criteria import default_criteria

    reset_cache()
    hoja = get_spreadsheet(hoja_id)
    pestanas = _ensure_named_sheets(hoja)

    # --- CPV ---
    cpv_ws = pestanas[CPV_SHEET]
    cpvs, keywords = default_criteria() if sembrar_criterios else ({}, {})
    filas_cpv = [[codigo, descripcion, "sí"] for codigo, descripcion in cpvs.items()]
    cpv_ws.clear()
    cpv_ws.update([CPV_HEADERS] + filas_cpv, "A1")
    _format_header(cpv_ws, len(CPV_HEADERS))
    _resize_columns(cpv_ws, [140, 360, 90])
    _data_validation(cpv_ws, 3, ACTIVO_OPTIONS)

    # --- Palabras clave ---
    kw_ws = pestanas[KEYWORDS_SHEET]
    filas_kw = [
        [termino, categoria, "sí"]
        for categoria, terminos in keywords.items()
        for termino in terminos
    ]
    kw_ws.clear()
    kw_ws.update([KEYWORD_HEADERS] + filas_kw, "A1")
    _format_header(kw_ws, len(KEYWORD_HEADERS))
    _resize_columns(kw_ws, [260, 220, 90])
    _data_validation(kw_ws, 3, ACTIVO_OPTIONS)

    # --- Oportunidades ---
    opp_ws = pestanas[OPPORTUNITIES_SHEET]
    # Conserva filas ya existentes si la hoja ya tenía datos.
    existentes = []
    try:
        registros = opp_ws.get_all_records()
        if registros and set(OPPORTUNITY_HEADERS).issubset(set(opp_ws.row_values(1))):
            existentes = [
                [_campo(r, h, default="") for h in OPPORTUNITY_HEADERS] for r in registros
            ]
    except Exception:
        existentes = []
    opp_ws.clear()
    opp_ws.update([OPPORTUNITY_HEADERS] + existentes, "A1")
    _format_header(opp_ws, len(OPPORTUNITY_HEADERS))
    _resize_columns(
        opp_ws,
        [120, 110, 100, 140, 320, 220, 140, 120, 160, 200, 110, 120, 180, 150, 220],
    )
    _data_validation(opp_ws, 14, SEGUIMIENTO_OPTIONS, filas=2000)

    # --- Instrucciones ---
    readme = pestanas[README_SHEET]
    instrucciones = [
        ["GREFA · Monitor de Licitaciones — Instrucciones de uso"],
        [""],
        ["Esta hoja es el almacén compartido de la aplicación web."],
        ["Cualquier miembro con cuenta @grefa.org puede editarla desde Drive."],
        [""],
        ["Pestaña CatalogoCPV"],
        ["- Contiene los ~9.450 códigos CPV oficiales en español."],
        ["- Pon Activo = sí en los que te interesen. El resto no puntúa."],
        [""],
        ["Pestaña CatalogoTerminos"],
        ["- Castellano / Euskera / Catalán / Gallego: formas de búsqueda."],
        ["- Si un término está Activo, la app busca en los cuatro idiomas."],
        ["- Al añadir un término nuevo, rellena las traducciones si las conoces."],
        [""],
        ["Pestañas CPV y PalabrasClave"],
        ["- Son el resumen de lo que está Activo en los catálogos."],
        [""],
        ["Pestaña Oportunidades"],
        ["- La aplicación añade filas nuevas (nunca duplica expediente+enlace)."],
        ["- Edita «Seguimiento» y «Notas» desde la app (pestaña Seguimiento) o en Drive."],
        ["- Seguimiento: Pendiente de revisar / En estudio / Presentada /"],
        ["  Descartada / Adjudicada a terceros / Ganada."],
        [""],
        ["Pestaña Pliegos"],
        ["- Resúmenes IA de pliegos PDF generados desde la aplicación."],
        ["- Una fila por expediente (se actualiza si se vuelve a analizar)."],
        [""],
        ["Pestaña ChecklistDocs"],
        ["- Documentación a preparar por expediente (Pendiente / En preparación / Preparado)."],
        ["- Enlace Drive: fichero subido desde la app o pegado a mano."],
        ["- Carpeta Drive docs: sheets.drive_folder_id (subcarpetas por expediente — órgano)."],
        ["- Compartir esa carpeta como Editor con la cuenta de servicio de GCP."],
        [""],
        ["Pestaña Historico"],
        ["- Snapshot diario automático de oportunidades Alta y Media."],
        ["- No editar manualmente salvo correcciones puntuales."],
        [""],
        ["Pestaña Config"],
        ["- ultima_ejecucion: control interno de la sync diaria."],
        ["- claves_alta_vistas: expedientes Alta ya notificados."],
        [""],
        ["Alertas Google Chat"],
        ["- Opción recomendada: email del espacio (Configuración → Email → Generar)."],
        ["- Configura space_email + smtp_* en secrets.toml o Streamlit Cloud."],
        ["- Alternativa: webhook si el admin lo permite."],
        [""],
        ["Resúmenes IA (Gemini)"],
        ["- Configura [gemini] api_key en secrets.toml (Google AI Studio, tier gratuito)."],
        [""],
        ["URL de la hoja"],
        [spreadsheet_url(hoja_id)],
    ]
    readme.clear()
    readme.update(instrucciones, "A1")
    readme.format("A1", {"textFormat": {"bold": True, "fontSize": 14}})
    _resize_columns(readme, [720])

    # Catálogos completos seleccionables (CPV oficial + términos multiidioma).
    from modules.sheets_catalog import initialize_catalogs

    resumen_catalogos = initialize_catalogs(hoja_id)

    # Relee pestañas tras crear los catálogos.
    from modules import sheets_historico as hist

    pestanas = {p.title: p for p in hoja.worksheets()}
    orden = [
        pestanas.get(README_SHEET),
        pestanas.get("CatalogoCPV"),
        pestanas.get("CatalogoTerminos"),
        pestanas.get(CPV_SHEET),
        pestanas.get(KEYWORDS_SHEET),
        pestanas.get(OPPORTUNITIES_SHEET),
        hist._worksheet_historico(hoja_id),
        hist._worksheet_config(hoja_id),
    ]
    try:
        hoja.reorder_worksheets([p for p in orden if p is not None])
    except Exception:
        LOGGER.debug("No se pudo reordenar las pestañas.")

    try:
        hoja.update_title("GREFA · Licitaciones PLACSP")
    except Exception:
        LOGGER.debug("No se pudo renombrar el libro.")

    reset_cache()
    return {
        "cpvs": resumen_catalogos.get("cpv_activos", len(filas_cpv)),
        "keywords": resumen_catalogos.get("terminos_activos", len(filas_kw)),
        "oportunidades": len(existentes),
        **resumen_catalogos,
    }
