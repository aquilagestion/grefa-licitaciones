"""Catálogos seleccionables en Google Sheets (CPV completo + términos multiidioma)."""

from __future__ import annotations

import logging
from typing import Any

from config.cpv_catalog import active_cpvs, default_cpv_catalog
from config.keyword_catalog import (
    active_keywords_grouped,
    active_search_terms,
    default_term_catalog,
)
from modules import sheets_store as store

LOGGER = logging.getLogger(__name__)

CATALOG_CPV_SHEET = "CatalogoCPV"
CATALOG_TERMS_SHEET = "CatalogoTerminos"

CATALOG_CPV_HEADERS = ["Código CPV", "Descripción", "Activo"]
CATALOG_TERMS_HEADERS = [
    "Castellano",
    "Euskera",
    "Catalán",
    "Gallego",
    "Categoría",
    "Activo",
]


def _bulk_write(pestana, valores: list[list], chunk: int = 4000) -> None:
    """Escribe una matriz grande por trozos (límite práctico de la API)."""
    pestana.clear()
    if not valores:
        return
    for inicio in range(0, len(valores), chunk):
        trozo = valores[inicio : inicio + chunk]
        pestana.update(trozo, f"A{inicio + 1}", value_input_option="USER_ENTERED")


def _activo_cell(valor: Any) -> str:
    return "sí" if store._es_activo(valor if valor not in (None, "") else "sí") else "no"


def load_cpv_catalog(hoja_id: str | None = None) -> list[dict]:
    hoja = store.get_spreadsheet(hoja_id)
    try:
        pestana = hoja.worksheet(CATALOG_CPV_SHEET)
        filas = pestana.get_all_records()
    except Exception:
        return default_cpv_catalog()

    if not filas:
        return default_cpv_catalog()

    catalogo: list[dict] = []
    for fila in filas:
        codigo = str(store._campo(fila, "Código CPV", "codigo")).strip()
        if not codigo:
            continue
        catalogo.append(
            {
                "codigo": codigo,
                "descripcion": str(store._campo(fila, "Descripción", "descripcion")).strip(),
                "activo": store._es_activo(store._campo(fila, "Activo", "activo", default="no")),
            }
        )
    return catalogo or default_cpv_catalog()


def load_term_catalog(hoja_id: str | None = None) -> list[dict]:
    hoja = store.get_spreadsheet(hoja_id)
    try:
        pestana = hoja.worksheet(CATALOG_TERMS_SHEET)
        filas = pestana.get_all_records()
    except Exception:
        return default_term_catalog()

    if not filas:
        return default_term_catalog()

    catalogo: list[dict] = []
    for fila in filas:
        castellano = str(store._campo(fila, "Castellano", "castellano", "termino")).strip()
        if not castellano:
            continue
        catalogo.append(
            {
                "castellano": castellano,
                "euskera": str(store._campo(fila, "Euskera", "euskera")).strip(),
                "catalan": str(store._campo(fila, "Catalán", "Catalan", "catalan")).strip(),
                "gallego": str(store._campo(fila, "Gallego", "gallego")).strip(),
                "categoria": str(
                    store._campo(fila, "Categoría", "categoria", default="Sin categoría")
                ).strip()
                or "Sin categoría",
                "activo": store._es_activo(store._campo(fila, "Activo", "activo", default="sí")),
            }
        )
    return catalogo or default_term_catalog()


def load_selection(hoja_id: str | None = None) -> tuple[dict[str, str], dict[str, list[str]], list[dict], list[dict]]:
    """Devuelve (cpvs_activos, keywords_agrupados, catalogo_cpv, catalogo_terminos)."""
    catalogo_cpv = load_cpv_catalog(hoja_id)
    catalogo_terminos = load_term_catalog(hoja_id)
    return (
        active_cpvs(catalogo_cpv),
        active_keywords_grouped(catalogo_terminos),
        catalogo_cpv,
        catalogo_terminos,
    )


def save_cpv_catalog(catalogo: list[dict], hoja_id: str | None = None) -> None:
    hoja = store.get_spreadsheet(hoja_id)
    pestana = store._worksheet(hoja, CATALOG_CPV_SHEET, CATALOG_CPV_HEADERS)
    valores = [CATALOG_CPV_HEADERS] + [
        [f["codigo"], f.get("descripcion", ""), "sí" if f.get("activo") else "no"]
        for f in catalogo
    ]
    _bulk_write(pestana, valores)
    store._format_header(pestana, len(CATALOG_CPV_HEADERS))
    store._resize_columns(pestana, [140, 420, 90])
    store._data_validation(pestana, 3, store.ACTIVO_OPTIONS, filas=min(len(valores) + 50, 10000))


def save_term_catalog(catalogo: list[dict], hoja_id: str | None = None) -> None:
    hoja = store.get_spreadsheet(hoja_id)
    pestana = store._worksheet(hoja, CATALOG_TERMS_SHEET, CATALOG_TERMS_HEADERS)
    valores = [CATALOG_TERMS_HEADERS] + [
        [
            f.get("castellano", ""),
            f.get("euskera", ""),
            f.get("catalan", ""),
            f.get("gallego", ""),
            f.get("categoria", ""),
            "sí" if f.get("activo") else "no",
        ]
        for f in catalogo
    ]
    _bulk_write(pestana, valores)
    store._format_header(pestana, len(CATALOG_TERMS_HEADERS))
    store._resize_columns(pestana, [220, 220, 220, 220, 180, 90])
    store._data_validation(pestana, 6, store.ACTIVO_OPTIONS, filas=min(len(valores) + 50, 2000))


def sync_active_summary_sheets(
    catalogo_cpv: list[dict],
    catalogo_terminos: list[dict],
    hoja_id: str | None = None,
) -> None:
    """Mantiene las pestañas CPV / PalabrasClave como resumen de lo activo."""
    cpvs = active_cpvs(catalogo_cpv)
    keywords = active_keywords_grouped(catalogo_terminos)
    store.save_criteria(cpvs, keywords, hoja_id=hoja_id)


def initialize_catalogs(hoja_id: str | None = None) -> dict[str, int]:
    """Crea/rellena CatalogoCPV y CatalogoTerminos y sincroniza los resúmenes activos."""
    catalogo_cpv = default_cpv_catalog()
    catalogo_terminos = default_term_catalog()

    # Asegura espacio suficiente en CatalogoCPV.
    hoja = store.get_spreadsheet(hoja_id)
    try:
        pestana = hoja.worksheet(CATALOG_CPV_SHEET)
    except Exception:
        pestana = hoja.add_worksheet(title=CATALOG_CPV_SHEET, rows=10000, cols=4)
    if pestana.row_count < 10000:
        try:
            pestana.resize(rows=10000)
        except Exception:
            LOGGER.debug("No se pudo ampliar CatalogoCPV")

    save_cpv_catalog(catalogo_cpv, hoja_id=hoja_id)
    save_term_catalog(catalogo_terminos, hoja_id=hoja_id)
    sync_active_summary_sheets(catalogo_cpv, catalogo_terminos, hoja_id=hoja_id)

    return {
        "cpv_total": len(catalogo_cpv),
        "cpv_activos": sum(1 for c in catalogo_cpv if c.get("activo")),
        "terminos_total": len(catalogo_terminos),
        "terminos_activos": sum(1 for t in catalogo_terminos if t.get("activo")),
        "variantes_busqueda": len(active_search_terms(catalogo_terminos)),
    }
