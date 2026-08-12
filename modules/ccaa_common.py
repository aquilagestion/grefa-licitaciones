"""Utilidades compartidas para conectores CCAA."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

import pandas as pd

FUENTES_PLACSP_IDS: frozenset[str] = frozenset(
    {"placsp_643", "placsp_1044", "placsp_local", "placsp"}
)


def texto(valor: Any) -> str:
    if valor is None:
        return ""
    if isinstance(valor, dict):
        return texto(valor.get("url") or valor.get("href") or "")
    return " ".join(str(valor).split())


def pick_field(row: dict[str, Any], *candidatos: str) -> str:
    """Devuelve el primer campo no vacío (comparación sin tildes / mayúsculas)."""
    if not row:
        return ""
    indice = {sin_tildes(str(k)): k for k in row.keys()}
    for cand in candidatos:
        clave = indice.get(sin_tildes(cand))
        if clave is None:
            continue
        valor = texto(row.get(clave))
        if valor:
            return valor
    return ""


def sin_tildes(valor: str) -> str:
    des = unicodedata.normalize("NFKD", str(valor or "").lower())
    return "".join(c for c in des if not unicodedata.combining(c))


def map_estado(nombre: str, tabla: dict[str, str]) -> str:
    bruto = texto(nombre)
    if not bruto:
        return ""
    clave = sin_tildes(bruto)
    for patron, destino in tabla.items():
        p = sin_tildes(patron)
        if clave == p or p in clave:
            return destino
    return bruto


def to_float_eu(valor: Any) -> float | None:
    """Parsea importes europeos (1.234,56) o anglosajones."""
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    limpio = str(valor).replace("\u00a0", "").replace(" ", "").strip()
    if not limpio or limpio in {"-", "—", "null", "None"}:
        return None
    limpio = re.sub(r"[€$]", "", limpio)
    if "," in limpio and "." in limpio:
        if limpio.rfind(",") > limpio.rfind("."):
            limpio = limpio.replace(".", "").replace(",", ".")
        else:
            limpio = limpio.replace(",", "")
    elif "," in limpio:
        limpio = limpio.replace(",", ".")
    try:
        return float(limpio)
    except ValueError:
        return None


def cpvs_desde_texto(valor: Any) -> tuple[list[str], str]:
    bruto = texto(valor)
    if not bruto:
        return [], ""
    codigos = re.findall(r"\b\d{8}(?:-\d)?\b", bruto)
    if not codigos:
        # a veces viene solo el código base
        codigos = re.findall(r"\b\d{8}\b", bruto)
    unicos: list[str] = []
    for c in codigos:
        if c not in unicos:
            unicos.append(c)
    return unicos, ", ".join(unicos) if unicos else bruto


def _norm_clave(valor: Any) -> str:
    return texto(valor).casefold()


def _norm_url(valor: Any) -> str:
    url = _norm_clave(valor)
    if not url:
        return ""
    url = re.sub(r"/+$", "", url)
    url = url.replace("http://", "https://")
    return url


def es_fuente_placsp(fuente: Any) -> bool:
    return _norm_clave(fuente) in FUENTES_PLACSP_IDS


def dedupe_licitaciones(df: pd.DataFrame) -> pd.DataFrame:
    """Elimina duplicados al mezclar PLACSP y conectores nativos.

    1. Clave principal: expediente + url (normalizados).
    2. Si el mismo expediente aparece en fuente nativa y PLACSP, se conserva la nativa.
    """
    if df is None or df.empty:
        return df

    out = df.copy()
    out["_exp_n"] = (
        out["expediente"].map(_norm_clave) if "expediente" in out.columns else ""
    )
    out["_url_n"] = out["url"].map(_norm_url) if "url" in out.columns else ""
    if "fuente" in out.columns:
        out["_prio"] = out["fuente"].map(
            lambda f: 0 if es_fuente_placsp(f) else 1
        )
    else:
        out["_prio"] = 0

    # Más prioridad + título más largo gana en empates.
    if "titulo" in out.columns:
        out["_tit_len"] = out["titulo"].fillna("").astype(str).str.len()
    else:
        out["_tit_len"] = 0

    out = out.sort_values(
        ["_prio", "_tit_len"], ascending=[False, False], kind="mergesort"
    )

    subset = ["_exp_n", "_url_n"] if "url" in df.columns else ["_exp_n"]
    out = out.drop_duplicates(subset=subset, keep="first")

    # Colisión nativa vs PLACSP con mismo expediente (URLs distintas).
    if "fuente" in df.columns and "expediente" in df.columns:
        con_exp = out["_exp_n"].astype(str).str.len() > 0
        if con_exp.any():
            bloques: list[pd.DataFrame] = []
            for _, grupo in out[con_exp].groupby("_exp_n", sort=False):
                if len(grupo) == 1:
                    bloques.append(grupo)
                    continue
                fuentes = {
                    _norm_clave(f) for f in grupo["fuente"].tolist() if texto(f)
                }
                hay_nativa = any(f not in FUENTES_PLACSP_IDS for f in fuentes)
                hay_placsp = any(f in FUENTES_PLACSP_IDS for f in fuentes)
                if hay_nativa and hay_placsp:
                    bloques.append(grupo[grupo["_prio"] == 1].head(1))
                else:
                    bloques.append(grupo)
            out = pd.concat(bloques + [out[~con_exp]], ignore_index=True, sort=False)

    return out.drop(
        columns=[
            c
            for c in ("_exp_n", "_url_n", "_prio", "_tit_len")
            if c in out.columns
        ]
    ).reset_index(drop=True)
