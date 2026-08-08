"""Histórico GREFA en fichero local (Parquet): consultas sin cuota Google Sheets.

La app lee y filtra este fichero. Se reconstruye con:
  python -u scripts/build_historico_local.py --from-year 2021 --to-year 2026 --skip-download
o exportando una vez desde Sheets:
  python -u scripts/build_historico_local.py --from-sheets --from-year 2021 --to-year 2026
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

LOGGER = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
PARQUET_PATH = DATA_DIR / "historico_grefa.parquet"
META_PATH = DATA_DIR / "historico_grefa.meta.json"

#: Columnas mínimas para búsqueda NIF / expediente / ámbito.
COLUMNAS_BUSQUEDA = (
    "expediente",
    "titulo",
    "organo_contratacion",
    "nif_organo",
    "adjudicatario",
    "nif_adjudicatario",
    "estado",
    "presupuesto_sin_iva",
    "ubicacion",
    "fecha_actualizacion",
    "fecha_limite",
    "url",
    "cpvs_texto",
    "relevancia",
    "categoria",
    "nivel_administracion",
    "año",
    "fuente",
)


def parquet_path() -> Path:
    custom = os.environ.get("GREFA_HISTORICO_LOCAL")
    return Path(custom) if custom else PARQUET_PATH


def meta_path() -> Path:
    ruta = parquet_path()
    if ruta == PARQUET_PATH:
        return META_PATH
    return ruta.with_suffix(".meta.json")


def is_available() -> bool:
    return parquet_path().is_file()


def metadata() -> dict[str, Any]:
    ruta = meta_path()
    if not ruta.is_file():
        return {}
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load(*, years: Sequence[int] | None = None) -> pd.DataFrame:
    """Carga el Parquet local; opcionalmente filtra por año."""
    ruta = parquet_path()
    if not ruta.is_file():
        return pd.DataFrame()
    try:
        df = pd.read_parquet(ruta)
    except Exception as exc:
        LOGGER.warning("No se pudo leer %s: %s", ruta, exc)
        return pd.DataFrame()

    if years and not df.empty and "año" in df.columns:
        años = {int(y) for y in years}
        df = df[df["año"].fillna(0).astype(int).isin(años)].copy()
    return df.reset_index(drop=True)


def save(df: pd.DataFrame, meta: dict[str, Any] | None = None) -> Path:
    """Persiste el DataFrame y metadatos."""
    ruta = parquet_path()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    salida = df.copy()
    if "año" not in salida.columns:
        salida["año"] = pd.NA
    if "fuente" not in salida.columns:
        salida["fuente"] = "local"
    # Listas → texto (Parquet/pyarrow a veces falla con object lists)
    for col in ("cpvs", "documentos", "cpvs_match", "keywords_match"):
        if col in salida.columns:
            salida[col] = salida[col].map(
                lambda v: ", ".join(str(x) for x in v)
                if isinstance(v, (list, tuple))
                else ("" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v))
            )
    # Tipos estables para pyarrow
    if "relevancia" in salida.columns:
        salida["relevancia"] = pd.to_numeric(salida["relevancia"], errors="coerce")
    if "presupuesto_sin_iva" in salida.columns:
        salida["presupuesto_sin_iva"] = pd.to_numeric(
            salida["presupuesto_sin_iva"], errors="coerce"
        )
    if "año" in salida.columns:
        salida["año"] = pd.to_numeric(salida["año"], errors="coerce").astype("Int64")
    for col in salida.select_dtypes(include=["object"]).columns:
        salida[col] = salida[col].map(
            lambda v: ""
            if v is None or (isinstance(v, float) and pd.isna(v))
            else (", ".join(str(x) for x in v) if isinstance(v, (list, tuple)) else str(v))
        )
    salida.to_parquet(ruta, index=False)
    info = {
        "actualizado": datetime.now(timezone.utc).isoformat(),
        "filas": int(len(salida)),
        "ruta": str(ruta),
        "con_nif_adjudicatario": int(
            (salida["nif_adjudicatario"].astype(str).str.strip() != "").sum()
        )
        if "nif_adjudicatario" in salida.columns
        else 0,
        "años": sorted(
            {int(a) for a in salida["año"].dropna().unique().tolist()}
        )
        if "año" in salida.columns
        else [],
    }
    if meta:
        info.update(meta)
    meta_path().write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    return ruta


def resumen() -> str:
    if not is_available():
        return "Sin fichero local (data/historico_grefa.parquet)."
    meta = metadata()
    filas = meta.get("filas", "?")
    nif = meta.get("con_nif_adjudicatario", "?")
    años = meta.get("años") or []
    act = (meta.get("actualizado") or "")[:19].replace("T", " ")
    años_txt = ", ".join(str(a) for a in años) if años else "—"
    return f"Local: {filas:,} filas · {nif:,} con NIF adjudicatario · años {años_txt} · {act} UTC"


def _ano_fila(fila: pd.Series, default: int | None = None) -> int | None:
    for clave in ("año", "ano", "year"):
        if clave in fila.index and pd.notna(fila.get(clave)):
            try:
                return int(fila.get(clave))
            except (TypeError, ValueError):
                pass
    fecha = fila.get("fecha_actualizacion") or fila.get("fecha_snapshot")
    if fecha is not None and not (isinstance(fecha, float) and pd.isna(fecha)):
        try:
            return int(pd.to_datetime(fecha, dayfirst=True, format="mixed").year)
        except (TypeError, ValueError):
            pass
    exp = str(fila.get("expediente") or "")
    import re

    m = re.search(r"(20\d{2})", exp)
    if m:
        return int(m.group(1))
    return default


def normalize_for_store(df: pd.DataFrame, *, fuente: str = "local", default_year: int | None = None) -> pd.DataFrame:
    """Asegura columnas de búsqueda y año."""
    if df is None or df.empty:
        return pd.DataFrame(columns=list(COLUMNAS_BUSQUEDA))
    out = df.copy()
    if "cpvs_texto" not in out.columns and "cpvs" in out.columns:
        out["cpvs_texto"] = out["cpvs"].map(
            lambda v: ", ".join(str(x) for x in v) if isinstance(v, (list, tuple)) else str(v or "")
        )
    if "año" not in out.columns:
        out["año"] = [_ano_fila(fila, default_year) for _, fila in out.iterrows()]
    else:
        out["año"] = out.apply(
            lambda fila: fila["año"] if pd.notna(fila.get("año")) else _ano_fila(fila, default_year),
            axis=1,
        )
    out["fuente"] = fuente
    for col in COLUMNAS_BUSQUEDA:
        if col not in out.columns:
            out[col] = pd.NA if col in {"presupuesto_sin_iva", "relevancia", "año"} else ""
    return out
