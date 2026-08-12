"""Utilidades compartidas para conectores CCAA."""

from __future__ import annotations

import re
import unicodedata
from typing import Any


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
