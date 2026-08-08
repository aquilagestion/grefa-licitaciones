"""Histórico diario y por años en Google Sheets."""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from typing import Any, Sequence

import pandas as pd

from modules import sheets_store as store
from modules.admin_ambito import classify_organo

LOGGER = logging.getLogger(__name__)

# Caché en proceso de la pestaña Config (evita 1 lectura Sheets por cada rerun de Streamlit).
_CONFIG_CACHE: dict[str, tuple[float, dict[str, str]]] = {}
_CONFIG_TTL_SEG = 600  # 10 minutos

HISTORICO_SHEET = "Historico"  # legado / sync reciente
CONFIG_SHEET = "Config"
YEAR_SHEET_PREFIX = "Historico_"

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
    "Adjudicatario",
    "NIF adjudicatario",
]

CONFIG_HEADERS = ["Clave", "Valor"]

CONFIG_ULTIMA_EJECUCION = "ultima_ejecucion"
CONFIG_CLAVES_ALTA = "claves_alta_vistas"

_YEAR_RE = re.compile(r"(20\d{2})")


def sheet_name_for_year(year: int) -> str:
    return f"{YEAR_SHEET_PREFIX}{int(year)}"


def _clave_expediente(expediente: str, enlace: str) -> str:
    return f"{str(expediente).strip().lower()}|{str(enlace).strip().lower()}"


def _hoy() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _worksheet_config(hoja_id: str | None = None):
    hoja = store.get_spreadsheet(hoja_id)
    return store._worksheet(hoja, CONFIG_SHEET, CONFIG_HEADERS)


def _find_worksheet(hoja, titulo: str, pestanas: list | None = None):
    """Localiza una pestaña por nombre (sin crearla)."""
    objetivo = str(titulo).strip().lower()
    for pestana in pestanas if pestanas is not None else _worksheets_cached(hoja):
        if str(pestana.title).strip().lower() == objetivo:
            return pestana
    return None


def _worksheet_historico(hoja_id: str | None = None):
    """Pestaña legado Historico (sync diario reciente)."""
    hoja = store.get_spreadsheet(hoja_id)
    return store._worksheet(hoja, HISTORICO_SHEET, HISTORICO_HEADERS)


def _worksheet_year(year: int, hoja_id: str | None = None):
    hoja = store.get_spreadsheet(hoja_id)
    return store._worksheet(hoja, sheet_name_for_year(year), HISTORICO_HEADERS)


def list_historico_years(hoja_id: str | None = None) -> list[int]:
    """Años con pestaña Historico_YYYY."""
    if not store.is_configured():
        return []
    hoja = store.get_spreadsheet(hoja_id)
    años: set[int] = set()
    for pestana in _worksheets_cached(hoja):
        titulo = str(pestana.title).strip()
        if titulo.lower().startswith(YEAR_SHEET_PREFIX.lower()):
            sufijo = titulo[len(YEAR_SHEET_PREFIX) :]
            if sufijo.isdigit():
                años.add(int(sufijo))
    return sorted(años)


def _worksheets_cached(hoja) -> list:
    """Una sola llamada worksheets() por spreadsheet en memoria de proceso."""
    clave = getattr(hoja, "id", None) or id(hoja)
    cache = getattr(_worksheets_cached, "_cache", {})
    if clave not in cache:
        cache[clave] = list(hoja.worksheets())
        _worksheets_cached._cache = cache  # type: ignore[attr-defined]
    return cache[clave]


def clear_worksheet_list_cache() -> None:
    _worksheets_cached._cache = {}  # type: ignore[attr-defined]


def _config_cache_key(hoja_id: str | None) -> str:
    return str(hoja_id or store.spreadsheet_id() or "default")


def clear_config_cache(hoja_id: str | None = None) -> None:
    """Invalida la caché de Config (tras escribir o al forzar sync)."""
    if hoja_id is None:
        _CONFIG_CACHE.clear()
        return
    _CONFIG_CACHE.pop(_config_cache_key(hoja_id), None)


def _leer_config_map(hoja_id: str | None = None, *, forzar: bool = False) -> dict[str, str]:
    clave = _config_cache_key(hoja_id)
    ahora = time.monotonic()
    if not forzar:
        cached = _CONFIG_CACHE.get(clave)
        if cached and (ahora - cached[0]) < _CONFIG_TTL_SEG:
            return dict(cached[1])
    try:
        pestana = _worksheet_config(hoja_id)
        filas = pestana.get_all_records()
    except store.SheetsError:
        raise
    except Exception as exc:
        raise store.SheetsError(f"No se pudo leer la pestaña Config: {exc}") from exc
    mapa = {
        str(store._campo(fila, "Clave", "clave")).strip(): str(
            store._campo(fila, "Valor", "valor")
        ).strip()
        for fila in filas
        if str(store._campo(fila, "Clave", "clave")).strip()
    }
    _CONFIG_CACHE[clave] = (ahora, mapa)
    return dict(mapa)


def _escribir_config(clave: str, valor: str, hoja_id: str | None = None) -> None:
    pestana = _worksheet_config(hoja_id)
    filas = pestana.get_all_values()
    if not filas:
        pestana.update([CONFIG_HEADERS, [clave, valor]], "A1")
        clear_config_cache(hoja_id)
        return
    for indice, fila in enumerate(filas[1:], start=2):
        if fila and str(fila[0]).strip() == clave:
            pestana.update([[valor]], f"B{indice}")
            clear_config_cache(hoja_id)
            return
    pestana.append_row([clave, valor], value_input_option="USER_ENTERED")
    clear_config_cache(hoja_id)


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
        texto(fila.get("adjudicatario")),
        texto(fila.get("nif_adjudicatario")),
    ]


def _indice_cabeceras(fila_cabecera: list[str]) -> dict[str, int]:
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


def _ano_desde_texto(*textos: str, default: int | None = None) -> int | None:
    for texto in textos:
        if not texto:
            continue
        # dd/mm/yyyy o yyyy-mm-dd
        m = re.search(r"(\d{1,2})/(\d{1,2})/(20\d{2})", str(texto))
        if m:
            return int(m.group(3))
        m = re.search(r"(20\d{2})-\d{2}-\d{2}", str(texto))
        if m:
            return int(m.group(1))
        m = _YEAR_RE.search(str(texto))
        if m:
            year = int(m.group(1))
            if 2000 <= year <= 2100:
                return year
    return default


def _valores_a_filas(valores: list[list[Any]], *, fuente: str = "") -> list[dict[str, Any]]:
    if not valores or len(valores) < 2:
        return []
    indices = _indice_cabeceras(valores[0])
    if "id expediente" not in indices and "expediente" not in indices:
        return []

    filas: list[dict[str, Any]] = []
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
        fecha_snapshot = _celda(fila, indices, "Fecha snapshot", "fecha_snapshot")
        filas.append(
            {
                "fecha_snapshot": fecha_snapshot,
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
                "adjudicatario": _celda(fila, indices, "Adjudicatario", "adjudicatario"),
                "nif_adjudicatario": _celda(
                    fila, indices, "NIF adjudicatario", "nif_adjudicatario"
                ),
                "_fuente_sheet": fuente,
            }
        )
    return filas


def _leer_pestana_valores(pestana, *, reintentos: int = 5) -> list[list[Any]]:
    import time

    ultimo: Exception | None = None
    for intento in range(reintentos):
        try:
            return pestana.get_all_values()
        except Exception as exc:
            ultimo = exc
            texto = str(exc).lower()
            if "429" in texto or "quota" in texto:
                time.sleep(min(2 ** intento, 30))
                continue
            raise store.SheetsError(f"No se pudo leer {pestana.title}: {exc}") from exc
    raise store.SheetsError(
        f"Cuota de Google Sheets agotada al leer {pestana.title}. "
        "Espera un minuto y pulsa Cargar de nuevo."
    ) from ultimo


def load_historico_dataframe(
    hoja_id: str | None = None,
    *,
    years: Sequence[int] | None = None,
    include_legacy: bool = True,
) -> pd.DataFrame:
    """Lee Historico_YYYY (+ legado Historico si hace falta)."""
    if not store.is_configured():
        return pd.DataFrame()

    try:
        hoja = store.get_spreadsheet(hoja_id)
        pestanas = _worksheets_cached(hoja)
        disponibles = sorted(
            {
                int(str(p.title)[len(YEAR_SHEET_PREFIX) :])
                for p in pestanas
                if str(p.title).strip().lower().startswith(YEAR_SHEET_PREFIX.lower())
                and str(p.title)[len(YEAR_SHEET_PREFIX) :].isdigit()
            }
        )
        if years:
            seleccion = [int(y) for y in years]
        elif disponibles:
            seleccion = disponibles
        else:
            seleccion = []

        filas: list[dict[str, Any]] = []
        for year in seleccion:
            pestana = _find_worksheet(hoja, sheet_name_for_year(year), pestanas)
            if pestana is None:
                continue
            filas.extend(
                _valores_a_filas(_leer_pestana_valores(pestana), fuente=sheet_name_for_year(year))
            )

        if include_legacy and not filas:
            legado = _find_worksheet(hoja, HISTORICO_SHEET, pestanas)
            if legado is not None:
                filas.extend(_valores_a_filas(_leer_pestana_valores(legado), fuente=HISTORICO_SHEET))
    except store.SheetsError:
        raise
    except Exception as exc:
        raise store.SheetsError(f"No se pudo leer el histórico en Sheets: {exc}") from exc

    if not filas:
        return pd.DataFrame()

    df = pd.DataFrame(filas)
    if "url" in df.columns:
        df = df.drop_duplicates(subset=["expediente", "url"], keep="first")
    else:
        df = df.drop_duplicates(subset=["expediente"], keep="first")
    return df.reset_index(drop=True)


def load_claves_historico(
    hoja_id: str | None = None,
    *,
    years: Sequence[int] | None = None,
) -> set[str]:
    """Claves expediente|url en pestañas de histórico (años o legado)."""
    df = load_historico_dataframe(hoja_id, years=years, include_legacy=True)
    if df.empty:
        return set()
    return {
        _clave_expediente(fila.get("expediente", ""), fila.get("url", ""))
        for _, fila in df.iterrows()
    }


def _momento_importacion(fila: pd.Series, etiqueta: str) -> str:
    fecha = fila.get("fecha_actualizacion")
    if fecha is not None and not (isinstance(fecha, float) and pd.isna(fecha)):
        try:
            return pd.to_datetime(fecha).strftime("%d/%m/%Y")
        except (TypeError, ValueError):
            pass
    return etiqueta


def _ano_fila_import(fila: pd.Series, default_year: int | None) -> int:
    fecha = fila.get("fecha_actualizacion")
    if fecha is not None and not (isinstance(fecha, float) and pd.isna(fecha)):
        try:
            return int(pd.to_datetime(fecha).year)
        except (TypeError, ValueError):
            pass
    year = _ano_desde_texto(str(fila.get("expediente", "")), default=default_year)
    return int(year or default_year or datetime.now().year)


def _append_rows(pestana, filas: list[list[str]], chunk_size: int = 500) -> None:
    for inicio in range(0, len(filas), chunk_size):
        pestana.append_rows(filas[inicio : inicio + chunk_size], value_input_option="USER_ENTERED")


def _bulk_write(pestana, valores: list[list[Any]], chunk: int = 4000) -> None:
    pestana.clear()
    if not valores:
        return
    for inicio in range(0, len(valores), chunk):
        trozo = valores[inicio : inicio + chunk]
        pestana.update(trozo, f"A{inicio + 1}", value_input_option="USER_ENTERED")


def enrich_adjudicatarios_year(
    year: int,
    lookup: dict[str, dict[str, str]],
    *,
    hoja_id: str | None = None,
    fill_nif_organo: bool = True,
) -> dict[str, int]:
    """Rellena Adjudicatario / NIF adjudicatario en Historico_YYYY desde un lookup.

    No toca el resto de columnas. Devuelve contadores de filas actualizadas.
    """
    if not store.is_configured() or not lookup:
        return {"filas": 0, "con_nombre": 0, "con_nif": 0, "actualizadas": 0}

    pestana = _worksheet_year(year, hoja_id)
    valores = _leer_pestana_valores(pestana)
    if not valores or len(valores) < 2:
        return {"filas": 0, "con_nombre": 0, "con_nif": 0, "actualizadas": 0}

    cabecera = [str(c or "").strip() for c in valores[0]]
    # Asegurar columnas de adjudicatario (imports antiguos podían no tenerlas)
    for nombre in ("Adjudicatario", "NIF adjudicatario", "NIF órgano"):
        if nombre not in cabecera:
            cabecera.append(nombre)
    indices = {nombre.lower(): i for i, nombre in enumerate(cabecera)}
    idx_exp = indices.get("id expediente", indices.get("expediente"))
    if idx_exp is None:
        return {"filas": 0, "con_nombre": 0, "con_nif": 0, "actualizadas": 0}

    idx_adj = indices["adjudicatario"]
    idx_nif = indices["nif adjudicatario"]
    idx_org = indices.get("nif órgano", indices.get("nif organo"))

    actualizadas = 0
    con_nombre = 0
    con_nif = 0
    matriz = [cabecera]
    ancho = len(cabecera)

    for fila in valores[1:]:
        fila = list(fila) + [""] * max(0, ancho - len(fila))
        fila = fila[:ancho]
        expediente = str(fila[idx_exp] or "").strip()
        datos = lookup.get(expediente.casefold()) if expediente else None
        if datos:
            cambiado = False
            nombre = str(datos.get("adjudicatario") or "").strip()
            nif = str(datos.get("nif_adjudicatario") or "").strip()
            if nombre and str(fila[idx_adj] or "").strip() != nombre:
                fila[idx_adj] = nombre
                cambiado = True
            if nif and str(fila[idx_nif] or "").strip() != nif:
                fila[idx_nif] = nif
                cambiado = True
            if (
                fill_nif_organo
                and idx_org is not None
                and datos.get("nif_organo")
                and not str(fila[idx_org] or "").strip()
            ):
                fila[idx_org] = str(datos["nif_organo"]).strip()
                cambiado = True
            if cambiado:
                actualizadas += 1
        if str(fila[idx_adj] or "").strip():
            con_nombre += 1
        if str(fila[idx_nif] or "").strip():
            con_nif += 1
        matriz.append(fila)

    if actualizadas:
        _bulk_write(pestana, matriz)

    return {
        "filas": max(len(matriz) - 1, 0),
        "con_nombre": con_nombre,
        "con_nif": con_nif,
        "actualizadas": actualizadas,
    }


def replace_year_historico(
    df: pd.DataFrame,
    year: int,
    *,
    categorias: tuple[str, ...] = ("Alta", "Media"),
    hoja_id: str | None = None,
    etiqueta_snapshot: str | None = None,
) -> int:
    """Sustituye Historico_YYYY con el DF puntuado (Alta/Media)."""
    if not store.is_configured():
        return 0
    filtrado = df[df["categoria"].isin(list(categorias))].copy() if not df.empty else df
    etiqueta = etiqueta_snapshot or f"Importación PLACSP {year}"
    pestana = _worksheet_year(year, hoja_id)

    matriz = [HISTORICO_HEADERS]
    for _, fila in filtrado.iterrows():
        momento = _momento_importacion(fila, etiqueta)
        matriz.append(_fila_historico(fila, momento))

    _bulk_write(pestana, matriz)
    return max(len(matriz) - 1, 0)


def append_historico_bulk(
    df: pd.DataFrame,
    *,
    categorias: tuple[str, ...] = ("Alta", "Media"),
    hoja_id: str | None = None,
    claves_existentes: set[str] | None = None,
    etiqueta_snapshot: str = "Importación histórica PLACSP",
    chunk_size: int = 500,
    default_year: int | None = None,
    replace_year: bool = False,
) -> tuple[int, set[str]]:
    """Importación masiva; escribe en Historico_YYYY según la fecha de cada fila."""
    if df.empty or not store.is_configured():
        return 0, claves_existentes or set()

    filtrado = df[df["categoria"].isin(list(categorias))].copy()
    if filtrado.empty:
        return 0, claves_existentes or set()

    if replace_year and default_year is not None:
        escritas = replace_year_historico(
            filtrado,
            default_year,
            categorias=categorias,
            hoja_id=hoja_id,
            etiqueta_snapshot=etiqueta_snapshot,
        )
        claves = {
            _clave_expediente(fila.get("expediente", ""), fila.get("url", ""))
            for _, fila in filtrado.iterrows()
        }
        if claves_existentes is not None:
            claves_existentes |= claves
            return escritas, claves_existentes
        return escritas, claves

    existentes = (
        claves_existentes
        if claves_existentes is not None
        else load_claves_historico(hoja_id)
    )

    por_ano: dict[int, list[list[str]]] = {}
    for _, fila in filtrado.iterrows():
        clave = _clave_expediente(fila.get("expediente", ""), fila.get("url", ""))
        if clave in existentes:
            continue
        existentes.add(clave)
        year = _ano_fila_import(fila, default_year)
        momento = _momento_importacion(fila, etiqueta_snapshot)
        por_ano.setdefault(year, []).append(_fila_historico(fila, momento))

    total = 0
    for year, nuevas in sorted(por_ano.items()):
        pestana = _worksheet_year(year, hoja_id)
        _append_rows(pestana, nuevas, chunk_size=chunk_size)
        total += len(nuevas)

    return total, existentes


def migrate_legacy_to_year_sheets(hoja_id: str | None = None) -> dict[int, int]:
    """Copia la pestaña legado Historico a Historico_YYYY (sin borrar el legado)."""
    if not store.is_configured():
        return {}

    hoja = store.get_spreadsheet(hoja_id)
    legado = _find_worksheet(hoja, HISTORICO_SHEET)
    if legado is None:
        return {}

    filas = _valores_a_filas(_leer_pestana_valores(legado), fuente=HISTORICO_SHEET)
    if not filas:
        return {}

    por_ano: dict[int, list[dict[str, Any]]] = {}
    for fila in filas:
        year = _ano_desde_texto(
            fila.get("fecha_snapshot", ""),
            fila.get("expediente", ""),
            default=datetime.now().year,
        ) or datetime.now().year
        por_ano.setdefault(int(year), []).append(fila)

    resultado: dict[int, int] = {}
    for year, items in sorted(por_ano.items()):
        pestana = _worksheet_year(year, hoja_id)
        existentes = {
            _clave_expediente(r.get("expediente", ""), r.get("url", ""))
            for r in _valores_a_filas(_leer_pestana_valores(pestana))
        }
        nuevas: list[list[str]] = []
        for item in items:
            clave = _clave_expediente(item.get("expediente", ""), item.get("url", ""))
            if clave in existentes:
                continue
            existentes.add(clave)
            serie = pd.Series(item)
            nuevas.append(_fila_historico(serie, item.get("fecha_snapshot") or f"Migrado {year}"))
        if nuevas:
            _append_rows(pestana, nuevas)
        resultado[year] = len(nuevas)
    return resultado


def append_historico_snapshot(
    df: pd.DataFrame,
    *,
    categorias: tuple[str, ...] = ("Alta", "Media"),
    hoja_id: str | None = None,
) -> int:
    """Snapshot diario Alta/Media → Historico_{año actual} (+ legado Historico)."""
    if df.empty or not store.is_configured():
        return 0

    filtrado = df[df["categoria"].isin(list(categorias))].copy()
    if filtrado.empty:
        return 0

    momento = datetime.now().strftime("%d/%m/%Y %H:%M")
    prefijo_hoy = datetime.now().strftime("%d/%m/%Y")
    year = datetime.now().year
    pestana_ano = _worksheet_year(year, hoja_id)
    pestana_legado = _worksheet_historico(hoja_id)

    existentes_hoy = {
        _clave_expediente(
            store._campo(reg, "ID Expediente", "expediente"),
            store._campo(reg, "Enlace", "enlace"),
        )
        for reg in pestana_ano.get_all_records()
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
        pestana_ano.append_rows(nuevas_filas, value_input_option="USER_ENTERED")
        pestana_legado.append_rows(nuevas_filas, value_input_option="USER_ENTERED")
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
