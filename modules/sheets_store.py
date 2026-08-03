"""Persistencia compartida en Google Sheets.

Pestañas principales:

* ``CatalogoCPV`` / ``CatalogoTerminos`` → catálogos completos seleccionables
  (Activo = sí/no). Los términos llevan columnas en castellano, euskera, catalán
  y gallego.
* ``CPV`` / ``PalabrasClave`` → resumen de lo que está activo (para lectura rápida).
* ``Oportunidades`` → volcado de licitaciones relevantes con seguimiento editable.
* ``Instrucciones`` → guía de uso.

Si no hay hoja configurada, la aplicación sigue funcionando solo en memoria.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime
from typing import Any

import pandas as pd

LOGGER = logging.getLogger(__name__)

SCOPES = (
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
)

CPV_SHEET = "CPV"
KEYWORDS_SHEET = "PalabrasClave"
OPPORTUNITIES_SHEET = "Oportunidades"
README_SHEET = "Instrucciones"

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
        try:
            import gspread

            cliente = gspread.authorize(_credentials())
            hoja = cliente.open_by_key(identificador)
        except Exception as exc:
            raise SheetsError(
                "No se pudo abrir la hoja de cálculo. Revisa el ID y que la hoja esté "
                f"compartida como Editor con la cuenta de servicio. Detalle: {exc}"
            ) from exc
        _SPREADSHEET_CACHE[identificador] = hoja
        return hoja


def reset_cache() -> None:
    with _LOCK:
        _SPREADSHEET_CACHE.clear()


# ---------------------------------------------------------------------------
# Utilidades internas
# ---------------------------------------------------------------------------
def _worksheet(hoja, titulo: str, cabeceras: list[str]):
    """Devuelve la pestaña pedida, creándola con cabeceras si no existe."""
    try:
        pestana = hoja.worksheet(titulo)
    except Exception:
        pestana = hoja.add_worksheet(title=titulo, rows=200, cols=max(len(cabeceras), 10))
        pestana.update([cabeceras], "A1")
        return pestana

    valores = pestana.row_values(1)
    if [v.strip().lower() for v in valores] != [c.lower() for c in cabeceras]:
        pestana.update([cabeceras], "A1")
    return pestana


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
        ["- Edita solo las columnas «Seguimiento» y «Notas»."],
        ["- Seguimiento: Pendiente de revisar / En estudio / Presentada /"],
        ["  Descartada / Adjudicada a terceros / Ganada."],
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
    pestanas = {p.title: p for p in hoja.worksheets()}
    orden = [
        pestanas.get(README_SHEET),
        pestanas.get("CatalogoCPV"),
        pestanas.get("CatalogoTerminos"),
        pestanas.get(CPV_SHEET),
        pestanas.get(KEYWORDS_SHEET),
        pestanas.get(OPPORTUNITIES_SHEET),
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
