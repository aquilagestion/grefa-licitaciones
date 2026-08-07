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

from modules.ingestion import COLUMNS, build_dataframe, empty_dataframe, _parse_feed_bytes

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
                df[columna] = "" if columna not in {"presupuesto_sin_iva", "presupuesto_con_iva", "cpvs"} else (
                    [] if columna == "cpvs" else None
                )
        return df[list(COLUMNS)]
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
