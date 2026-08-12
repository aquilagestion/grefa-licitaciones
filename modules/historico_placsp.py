"""Histórico masivo PLACSP (datos abiertos) en Parquet local."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from lxml import etree

from modules.ingestion import (
    COLUMNS,
    build_dataframe,
    empty_dataframe,
    _adjudicatario,
    _find,
    _findall,
    _nif_organo,
    _parse_feed_bytes,
    _text,
)

LOGGER = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[1]
CACHE_DIR = BASE_DIR / "data" / "cache"
PARQUET_PATH = CACHE_DIR / "historico_placsp.parquet"
META_PATH = CACHE_DIR / "historico_placsp.meta.json"

ZIP_URL_TEMPLATE = (
    "https://contrataciondelestado.es/sindicacion/sindicacion_643/"
    "licitacionesPerfilesContratanteCompleto3_{year}.zip"
)


def _cache_path() -> Path:
    custom = os.environ.get("GREFA_HISTORICO_PARQUET")
    return Path(custom) if custom else PARQUET_PATH


def is_available() -> bool:
    return _cache_path().is_file()


def metadata() -> dict[str, Any]:
    meta_path = META_PATH if _cache_path() == PARQUET_PATH else _cache_path().with_suffix(".meta.json")
    if not meta_path.is_file():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load() -> pd.DataFrame:
    """Carga el histórico local; devuelve DataFrame vacío si no existe."""
    ruta = _cache_path()
    if not ruta.is_file():
        return empty_dataframe()
    try:
        df = pd.read_parquet(ruta)
        for columna in COLUMNS:
            if columna not in df.columns:
                if columna in {"cpvs", "documentos"}:
                    df[columna] = [[] for _ in range(len(df))]
                elif columna in {"presupuesto_sin_iva", "presupuesto_con_iva"}:
                    df[columna] = None
                else:
                    df[columna] = ""
        from config.ccaa_sources import (
            FUENTE_PLACSP_643,
            enrich_comunidad_autonoma,
            enrich_fuente,
        )

        df = enrich_fuente(df[list(COLUMNS)], FUENTE_PLACSP_643)
        return enrich_comunidad_autonoma(df)
    except Exception as exc:
        LOGGER.warning("No se pudo leer el histórico Parquet: %s", exc)
        return empty_dataframe()


def _save(df: pd.DataFrame, meta: dict[str, Any]) -> None:
    ruta = _cache_path()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(ruta, index=False)
    meta_path = META_PATH if ruta == PARQUET_PATH else ruta.with_suffix(".meta.json")
    meta["actualizado"] = datetime.now(timezone.utc).isoformat()
    meta["filas"] = int(len(df))
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def merge_with_live(live: pd.DataFrame, historico: pd.DataFrame) -> pd.DataFrame:
    """Combina histórico + feed vivo; el feed vivo prevalece en duplicados."""
    if historico.empty:
        return live.copy()
    if live.empty:
        return historico.copy()
    historico = historico.copy()
    historico["_fuente"] = "historico"
    live = live.copy()
    live["_fuente"] = "vivo"
    combinado = pd.concat([historico, live], ignore_index=True)
    combinado = combinado.drop_duplicates(subset=["expediente", "url"], keep="last")
    if "fecha_actualizacion" in combinado.columns:
        combinado = combinado.sort_values("fecha_actualizacion", ascending=False, na_position="last")
    return combinado.reset_index(drop=True)


def _parse_atom_file(ruta: Path) -> list[dict[str, Any]]:
    try:
        registros, _ = _parse_feed_bytes(ruta.read_bytes())
        return registros
    except Exception as exc:
        LOGGER.debug("Atom omitido %s: %s", ruta.name, exc)
        return []


def scan_adjudicatarios_from_zip(
    zip_path: Path,
    *,
    max_files: int | None = None,
) -> dict[str, dict[str, str]]:
    """Índice expediente → adjudicatario/NIF (y NIF órgano) leyendo el ZIP sin extraccion.

    Solo procesa ficheros ATOM que contienen WinningParty. Si hay varias versiones
    del mismo expediente, prioriza la que trae NIF de adjudicatario.
    """
    zip_path = Path(zip_path).expanduser().resolve()
    if not zip_path.is_file():
        raise FileNotFoundError(f"No existe el ZIP: {zip_path}")

    resultado: dict[str, dict[str, str]] = {}
    parser = etree.XMLParser(recover=True, huge_tree=True, resolve_entities=False)

    with zipfile.ZipFile(zip_path) as archivo:
        atomos = sorted(n for n in archivo.namelist() if n.lower().endswith(".atom"))
        if max_files:
            atomos = atomos[: int(max_files)]
        for indice, nombre in enumerate(atomos, start=1):
            raw = archivo.read(nombre)
            if b"WinningParty" not in raw and b"winningparty" not in raw.lower():
                continue
            try:
                root = etree.fromstring(raw, parser=parser)
            except etree.XMLSyntaxError:
                continue
            if root is None:
                continue
            for entry in _findall(root, "entry"):
                carpeta = _find(entry, "ContractFolderStatus")
                if carpeta is None:
                    continue
                if not _findall(carpeta, "WinningParty"):
                    continue
                expediente = (_text(carpeta, "ContractFolderID") or "").strip()
                if not expediente:
                    continue
                nif_adj, nombre_adj = _adjudicatario(carpeta)
                if not nif_adj and not nombre_adj:
                    continue
                clave = expediente.casefold()
                actual = resultado.get(clave)
                candidato = {
                    "expediente": expediente,
                    "adjudicatario": nombre_adj,
                    "nif_adjudicatario": nif_adj,
                    "nif_organo": _nif_organo(carpeta),
                }
                if actual is None:
                    resultado[clave] = candidato
                elif nif_adj and not actual.get("nif_adjudicatario"):
                    resultado[clave] = candidato
            if indice % 50 == 0:
                LOGGER.info(
                    "Escaneados %s/%s ATOM (%s con adjudicatario)",
                    indice,
                    len(atomos),
                    len(resultado),
                )
    return resultado


def import_from_directory(directorio: Path, *, max_files: int | None = None) -> pd.DataFrame:
    """Parsea todos los .atom de un directorio (p. ej. ZIP descomprimido)."""
    ficheros = sorted(directorio.glob("*.atom"))
    if max_files:
        ficheros = ficheros[: int(max_files)]
    registros: list[dict[str, Any]] = []
    for indice, atom in enumerate(ficheros, start=1):
        registros.extend(_parse_atom_file(atom))
        if indice % 20 == 0:
            LOGGER.info("Procesados %s ficheros ATOM (%s entradas)", indice, len(registros))
    return build_dataframe(registros)


def import_from_zip_bytes(
    zip_path: Path,
    *,
    max_files: int | None = None,
) -> pd.DataFrame:
    """Parsea el ZIP anual sin descomprimir a disco (más rápido y menos I/O)."""
    zip_path = Path(zip_path).expanduser().resolve()
    if not zip_path.is_file():
        raise FileNotFoundError(f"No existe el ZIP: {zip_path}")
    registros: list[dict[str, Any]] = []
    with zipfile.ZipFile(zip_path) as archivo:
        atomos = sorted(n for n in archivo.namelist() if n.lower().endswith(".atom"))
        if max_files:
            atomos = atomos[: int(max_files)]
        for indice, nombre in enumerate(atomos, start=1):
            try:
                filas, _ = _parse_feed_bytes(archivo.read(nombre))
                registros.extend(filas)
            except Exception as exc:
                LOGGER.debug("Atom omitido %s: %s", nombre, exc)
            if indice % 25 == 0:
                LOGGER.info(
                    "ZIP %s: %s/%s ATOM (%s entradas)",
                    zip_path.name,
                    indice,
                    len(atomos),
                    len(registros),
                )
                print(
                    f"    … {indice}/{len(atomos)} ATOM · {len(registros):,} entradas",
                    flush=True,
                )
    return build_dataframe(registros)


def import_score_zip_alta_media(
    zip_path: Path,
    *,
    cpvs: list[str],
    keywords: list[str],
    conceptos: list[dict] | None = None,
    max_files: int | None = None,
    batch_atoms: int = 20,
) -> pd.DataFrame:
    """Parsea el ZIP por lotes, puntúa y conserva solo Alta/Media (poca RAM)."""
    from modules import grefa_filter

    zip_path = Path(zip_path).expanduser().resolve()
    if not zip_path.is_file():
        raise FileNotFoundError(f"No existe el ZIP: {zip_path}")

    relevantes: list[pd.DataFrame] = []
    total_parseadas = 0
    conceptos_activos = [t for t in (conceptos or []) if t.get("activo")]

    with zipfile.ZipFile(zip_path) as archivo:
        atomos = sorted(n for n in archivo.namelist() if n.lower().endswith(".atom"))
        if max_files:
            atomos = atomos[: int(max_files)]
        lote: list[dict[str, Any]] = []
        for indice, nombre in enumerate(atomos, start=1):
            try:
                filas, _ = _parse_feed_bytes(archivo.read(nombre))
                lote.extend(filas)
            except Exception as exc:
                LOGGER.debug("Atom omitido %s: %s", nombre, exc)

            if indice % batch_atoms == 0 or indice == len(atomos):
                if lote:
                    df_lote = build_dataframe(lote)
                    total_parseadas += len(df_lote)
                    puntuadas = grefa_filter.score_licitaciones(
                        df_lote, cpvs, keywords, conceptos=conceptos_activos
                    )
                    keep = puntuadas[puntuadas["categoria"].isin(["Alta", "Media"])]
                    if not keep.empty:
                        relevantes.append(keep.copy())
                    lote = []
                print(
                    f"    … {indice}/{len(atomos)} ATOM · parseadas {total_parseadas:,} · "
                    f"Alta/Media acumuladas {sum(len(x) for x in relevantes):,}",
                    flush=True,
                )

    if not relevantes:
        return empty_dataframe()
    combinado = pd.concat(relevantes, ignore_index=True, sort=False)
    if "url" in combinado.columns:
        combinado = combinado.drop_duplicates(subset=["expediente", "url"], keep="last")
    else:
        combinado = combinado.drop_duplicates(subset=["expediente"], keep="last")
    return combinado.reset_index(drop=True)


def import_from_zip(
    zip_path: Path,
    *,
    max_files: int | None = None,
    append: bool = True,
) -> tuple[int, dict[str, Any]]:
    """Importa un ZIP oficial PLACSP al Parquet local."""
    zip_path = zip_path.expanduser().resolve()
    if not zip_path.is_file():
        raise FileNotFoundError(f"No existe el ZIP: {zip_path}")

    with tempfile.TemporaryDirectory(prefix="grefa_placsp_") as tmp:
        with zipfile.ZipFile(zip_path) as archivo:
            archivo.extractall(tmp)
        df_nuevo = import_from_directory(Path(tmp), max_files=max_files)

    if df_nuevo.empty:
        raise RuntimeError("El ZIP no produjo licitaciones parseables.")

    if append and is_available():
        df_final = build_dataframe(
            load().to_dict("records") + df_nuevo.to_dict("records")
        )
    else:
        df_final = df_nuevo

    meta = metadata()
    meta.setdefault("fuentes", [])
    meta["fuentes"].append({"zip": zip_path.name, "filas_nuevas": len(df_nuevo), "filas_total": len(df_final)})
    _save(df_final, meta)
    return len(df_nuevo), meta


def download_year_zip(year: int, destino: Path, session=None) -> Path:
    """Descarga el ZIP anual oficial de PLACSP."""
    import requests

    url = ZIP_URL_TEMPLATE.format(year=year)
    destino.parent.mkdir(parents=True, exist_ok=True)
    sesion = session or requests.Session()
    sesion.headers.update({"User-Agent": "GREFA-Licitaciones/1.0"})
    with sesion.get(url, stream=True, timeout=600) as respuesta:
        respuesta.raise_for_status()
        with destino.open("wb") as fichero:
            for chunk in respuesta.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    fichero.write(chunk)
    return destino
