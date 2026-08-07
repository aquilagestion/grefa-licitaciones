"""Histórico diario y configuración de sincronización en Google Sheets."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

import pandas as pd

from modules import sheets_store as store
from modules.admin_ambito import classify_organo

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
    "NIF órgano",
    "Ámbito administración",
    "Ubicación",
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


def _find_worksheet(hoja, titulo: str):
    """Localiza una pestaña por nombre (sin crearla). Tolera mayúsculas/espacios."""
    objetivo = str(titulo).strip().lower()
    for pestana in hoja.worksheets():
        if str(pestana.title).strip().lower() == objetivo:
            return pestana
    try:
        return hoja.worksheet(titulo)
    except Exception:
        return None


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
    organo = texto(fila.get("organo_contratacion"))
    ambito = texto(fila.get("nivel_administracion"))
    if not ambito and organo:
        ambito = classify_organo(organo)
    return [
        momento,
        texto(fila.get("relevancia")),
        texto(fila.get("categoria")),
        texto(fila.get("expediente")),
        texto(fila.get("titulo")),
        organo,
        "" if presupuesto is None or pd.isna(presupuesto) else f"{float(presupuesto):.2f}",
        texto(fila.get("estado")),
        texto(fila.get("fecha_limite")),
        texto(fila.get("url")),
        texto(fila.get("cpvs_match")),
        texto(fila.get("keywords_match")),
        texto(fila.get("nif_organo")),
        ambito,
        texto(fila.get("ubicacion")),
    ]


def _indice_cabeceras(fila_cabecera: list[str]) -> dict[str, int]:
    """Mapea nombre de cabecera (minúsculas) → índice de columna."""
    indices: dict[str, int] = {}
    for indice, nombre in enumerate(fila_cabecera):
        clave = str(nombre or "").strip().lower()
        if clave and clave not in indices:
            indices[clave] = indice
    return indices


def _celda(fila: list[Any], indices: dict[str, int], *nombres: str) -> str:
    for nombre in nombres:
        indice = indices.get(nombre.strip().lower())
        if indice is None or indice >= len(fila):
            continue
        valor = fila[indice]
        if valor is None:
            continue
        texto = str(valor).strip()
        if texto:
            return texto
    return ""


def _parse_presupuesto(valor: str) -> float | None:
    if not valor:
        return None
    limpio = valor.replace("€", "").replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return float(limpio)
    except ValueError:
        return None


def load_historico_dataframe(hoja_id: str | None = None) -> pd.DataFrame:
    """Lee la pestaña Histórico de Google Sheets como DataFrame unificado."""
    if not store.is_configured():
        return pd.DataFrame()

    try:
        hoja = store.get_spreadsheet(hoja_id)
        pestana = _find_worksheet(hoja, HISTORICO_SHEET)
        if pestana is None:
            raise store.SheetsError(
                'No existe la pestaña "Historico" en la hoja. '
                "Créala con scripts/ensure_extra_sheets.py."
            )
        # Solo lectura: nunca crear/renombrar pestañas aquí.
        valores = pestana.get_all_values()
    except store.SheetsError:
        raise
    except Exception as exc:
        raise store.SheetsError(f"No se pudo leer el histórico en Sheets: {exc}") from exc

    if not valores or len(valores) < 2:
        return pd.DataFrame()

    indices = _indice_cabeceras(valores[0])
    if "id expediente" not in indices and "expediente" not in indices:
        # Cabeceras ausentes o pestaña vacía tras un update parcial.
        raise store.SheetsError(
            "La pestaña Histórico no tiene cabeceras reconocibles. "
            "Recarga la hoja o ejecuta scripts/ensure_extra_sheets.py."
        )

    filas: list[dict[str, Any]] = []
    try:
        for fila in valores[1:]:
            if not fila or not any(str(c).strip() for c in fila):
                continue
            expediente = _celda(fila, indices, "ID Expediente", "expediente")
            if not expediente:
                continue
            organo = _celda(fila, indices, "Órgano de Contratación", "organo")
            ambito = _celda(fila, indices, "Ámbito administración", "ambito_administracion")
            if not ambito and organo:
                ambito = classify_organo(organo)
            filas.append(
                {
                    "fecha_snapshot": _celda(fila, indices, "Fecha snapshot", "fecha_snapshot"),
                    "relevancia": _celda(fila, indices, "Relevancia (%)", "relevancia"),
                    "categoria": _celda(fila, indices, "Categoría", "categoria"),
                    "expediente": expediente,
                    "titulo": _celda(fila, indices, "Título / Objeto", "titulo"),
                    "organo_contratacion": organo,
                    "presupuesto_sin_iva": _parse_presupuesto(
                        _celda(fila, indices, "Presupuesto sin IVA", "presupuesto")
                    ),
                    "estado": _celda(fila, indices, "Estado PLACSP", "estado"),
                    "fecha_limite": _celda(fila, indices, "Fecha límite", "fecha_limite"),
                    "url": _celda(fila, indices, "Enlace", "enlace", "url"),
                    "cpvs_match": _celda(fila, indices, "CPV coincidentes", "cpvs_match"),
                    "keywords_match": _celda(fila, indices, "Palabras clave", "keywords_match"),
                    "nif_organo": _celda(fila, indices, "NIF órgano", "nif_organo"),
                    "nivel_administracion": ambito,
                    "ubicacion": _celda(fila, indices, "Ubicación", "ubicacion"),
                }
            )
    except Exception as exc:
        raise store.SheetsError(f"Error al interpretar el histórico: {exc}") from exc

    return pd.DataFrame(filas)


def load_claves_historico(hoja_id: str | None = None) -> set[str]:
    """Claves expediente|url ya presentes en la pestaña Histórico."""
    if not store.is_configured():
        return set()
    try:
        pestana = _worksheet_historico(hoja_id)
        return {
            _clave_expediente(
                store._campo(reg, "ID Expediente", "expediente"),
                store._campo(reg, "Enlace", "enlace"),
            )
            for reg in pestana.get_all_records()
        }
    except store.SheetsError:
        raise
    except Exception as exc:
        raise store.SheetsError(f"No se pudo leer claves del histórico: {exc}") from exc


def _momento_importacion(fila: pd.Series, etiqueta: str) -> str:
    fecha = fila.get("fecha_actualizacion")
    if fecha is not None and not (isinstance(fecha, float) and pd.isna(fecha)):
        try:
            return pd.to_datetime(fecha).strftime("%d/%m/%Y")
        except (TypeError, ValueError):
            pass
    return etiqueta


def append_historico_bulk(
    df: pd.DataFrame,
    *,
    categorias: tuple[str, ...] = ("Alta", "Media"),
    hoja_id: str | None = None,
    claves_existentes: set[str] | None = None,
    etiqueta_snapshot: str = "Importación histórica PLACSP",
    chunk_size: int = 500,
) -> tuple[int, set[str]]:
    """Importación masiva al histórico; deduplica contra claves ya presentes."""
    if df.empty or not store.is_configured():
        return 0, claves_existentes or set()

    filtrado = df[df["categoria"].isin(list(categorias))].copy()
    if filtrado.empty:
        return 0, claves_existentes or set()

    existentes = claves_existentes if claves_existentes is not None else load_claves_historico(hoja_id)
    pestana = _worksheet_historico(hoja_id)

    nuevas_filas: list[list[str]] = []
    for _, fila in filtrado.iterrows():
        clave = _clave_expediente(fila.get("expediente", ""), fila.get("url", ""))
        if clave in existentes:
            continue
        existentes.add(clave)
        momento = _momento_importacion(fila, etiqueta_snapshot)
        nuevas_filas.append(_fila_historico(fila, momento))

    if not nuevas_filas:
        return 0, existentes

    for inicio in range(0, len(nuevas_filas), chunk_size):
        trozo = nuevas_filas[inicio : inicio + chunk_size]
        pestana.append_rows(trozo, value_input_option="USER_ENTERED")

    return len(nuevas_filas), existentes


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
