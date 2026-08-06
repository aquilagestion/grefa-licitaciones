"""Histórico diario y configuración de sincronización en Google Sheets."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

import pandas as pd

from modules import sheets_store as store

LOGGER = logging.getLogger(__name__)

HISTORICO_SHEET = "Historico"
CONFIG_SHEET = "Config"

HISTORICO_HEADERS = [
    "Fecha snapshot",
    "Relevancia (%)",
    "Categoría",
    "ID Expediente",
    "Título / Objeto",
    "Órgano de Contratación",
    "Presupuesto sin IVA",
    "Estado PLACSP",
    "Fecha límite",
    "Enlace",
    "CPV coincidentes",
    "Palabras clave",
]

CONFIG_HEADERS = ["Clave", "Valor"]

CONFIG_ULTIMA_EJECUCION = "ultima_ejecucion"
CONFIG_CLAVES_ALTA = "claves_alta_vistas"


def _clave_expediente(expediente: str, enlace: str) -> str:
    return f"{str(expediente).strip().lower()}|{str(enlace).strip().lower()}"


def _hoy() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _worksheet_config(hoja_id: str | None = None):
    hoja = store.get_spreadsheet(hoja_id)
    return store._worksheet(hoja, CONFIG_SHEET, CONFIG_HEADERS)


def _worksheet_historico(hoja_id: str | None = None):
    hoja = store.get_spreadsheet(hoja_id)
    return store._worksheet(hoja, HISTORICO_SHEET, HISTORICO_HEADERS)


def _leer_config_map(hoja_id: str | None = None) -> dict[str, str]:
    try:
        pestana = _worksheet_config(hoja_id)
        filas = pestana.get_all_records()
    except store.SheetsError:
        raise
    except Exception as exc:
        raise store.SheetsError(f"No se pudo leer la pestaña Config: {exc}") from exc
    return {
        str(store._campo(fila, "Clave", "clave")).strip(): str(
            store._campo(fila, "Valor", "valor")
        ).strip()
        for fila in filas
        if str(store._campo(fila, "Clave", "clave")).strip()
    }


def _escribir_config(clave: str, valor: str, hoja_id: str | None = None) -> None:
    pestana = _worksheet_config(hoja_id)
    filas = pestana.get_all_values()
    if not filas:
        pestana.update([CONFIG_HEADERS, [clave, valor]], "A1")
        return
    for indice, fila in enumerate(filas[1:], start=2):
        if fila and str(fila[0]).strip() == clave:
            pestana.update([[valor]], f"B{indice}")
            return
    pestana.append_row([clave, valor], value_input_option="USER_ENTERED")


def get_config(clave: str, default: str = "", hoja_id: str | None = None) -> str:
    if not store.is_configured():
        return default
    try:
        return _leer_config_map(hoja_id).get(clave, default)
    except store.SheetsError:
        return default


def ya_ejecutado_hoy(hoja_id: str | None = None) -> bool:
    return get_config(CONFIG_ULTIMA_EJECUCION, hoja_id=hoja_id) == _hoy()


def load_claves_alta_vistas(hoja_id: str | None = None) -> set[str]:
    bruto = get_config(CONFIG_CLAVES_ALTA, "[]", hoja_id=hoja_id)
    try:
        lista = json.loads(bruto)
        if isinstance(lista, list):
            return {str(item) for item in lista}
    except json.JSONDecodeError:
        LOGGER.debug("claves_alta_vistas no es JSON válido; se reinicia.")
    return set()


def save_claves_alta_vistas(claves: set[str], hoja_id: str | None = None) -> None:
    _escribir_config(CONFIG_CLAVES_ALTA, json.dumps(sorted(claves), ensure_ascii=False), hoja_id)


def marcar_ejecutado_hoy(hoja_id: str | None = None) -> None:
    momento = datetime.now().strftime("%d/%m/%Y %H:%M")
    _escribir_config(CONFIG_ULTIMA_EJECUCION, _hoy(), hoja_id)
    _escribir_config("ultima_ejecucion_hora", momento, hoja_id)


def _fila_historico(fila: pd.Series, momento: str) -> list[str]:
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
        texto(fila.get("estado")),
        texto(fila.get("fecha_limite")),
        texto(fila.get("url")),
        texto(fila.get("cpvs_match")),
        texto(fila.get("keywords_match")),
    ]


def append_historico_snapshot(
    df: pd.DataFrame,
    *,
    categorias: tuple[str, ...] = ("Alta", "Media"),
    hoja_id: str | None = None,
) -> int:
    """Añade filas del snapshot diario (Alta/Media). Devuelve filas añadidas."""
    if df.empty or not store.is_configured():
        return 0

    filtrado = df[df["categoria"].isin(list(categorias))].copy()
    if filtrado.empty:
        return 0

    momento = datetime.now().strftime("%d/%m/%Y %H:%M")
    prefijo_hoy = datetime.now().strftime("%d/%m/%Y")
    pestana = _worksheet_historico(hoja_id)

    existentes_hoy = {
        _clave_expediente(
            store._campo(reg, "ID Expediente", "expediente"),
            store._campo(reg, "Enlace", "enlace"),
        )
        for reg in pestana.get_all_records()
        if str(store._campo(reg, "Fecha snapshot", "fecha_snapshot", default="")).startswith(
            prefijo_hoy
        )
    }

    nuevas_filas: list[list[str]] = []
    for _, fila in filtrado.iterrows():
        clave = _clave_expediente(fila.get("expediente", ""), fila.get("url", ""))
        if clave in existentes_hoy:
            continue
        nuevas_filas.append(_fila_historico(fila, momento))

    if nuevas_filas:
        pestana.append_rows(nuevas_filas, value_input_option="USER_ENTERED")
    return len(nuevas_filas)


def detectar_nuevas_alta(
    df: pd.DataFrame,
    claves_vistas: set[str] | None = None,
    hoja_id: str | None = None,
) -> tuple[list[dict[str, Any]], set[str]]:
    """Oportunidades Alta que no estaban en el conjunto de claves vistas."""
    if df.empty:
        return [], claves_vistas or set()

    vistas = claves_vistas if claves_vistas is not None else load_claves_alta_vistas(hoja_id)
    altas = df[df["categoria"] == "Alta"]
    nuevas: list[dict[str, Any]] = []
    claves_actuales: set[str] = set()

    for _, fila in altas.iterrows():
        clave = _clave_expediente(fila.get("expediente", ""), fila.get("url", ""))
        claves_actuales.add(clave)
        if clave not in vistas:
            nuevas.append(fila.to_dict())

    return nuevas, claves_actuales
