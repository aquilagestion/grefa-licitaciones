"""Catálogo completo de códigos CPV (vocabulario oficial 2008, etiquetas ES)."""

from __future__ import annotations

import csv
from pathlib import Path

from config.default_criteria import DEFAULT_CPVS

DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "cpv_es.csv"

# Prefijos que se activan por defecto además de DEFAULT_CPVS.
# El resto del catálogo (~9.450) queda disponible para seleccionar.
DEFAULT_ACTIVE_PREFIXES = (
    "0341",    # madera
    "0342",    # gomas y resinas; productos forestales varios
    "0343",    # plantas vivas / productos forestales
    "0344",    # productos de la silvicultura
    "0345",    # productos forestales varios
    "7721",    # servicios de explotación forestal
    "7722",    # plantación / mantenimiento forestal
    "7723",    # servicios forestales
    "9071",    # gestión medioambiental
    "9072",    # protección de la naturaleza
    "9073",    # control / seguimiento de la contaminación
    "7300",    # I+D (raíz)
    "7310",    # servicios de I+D
    "7320",    # consultoría en I+D
    "7330",    # diseño y ejecución de I+D
    "8514",    # servicios veterinarios
)


def load_cpv_rows() -> list[dict[str, str]]:
    """Lee el CSV oficial (codigo, descripcion)."""
    if not DATA_FILE.exists():
        return [
            {"codigo": codigo, "descripcion": descripcion}
            for codigo, descripcion in DEFAULT_CPVS.items()
        ]
    filas: list[dict[str, str]] = []
    with DATA_FILE.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            codigo = (row.get("codigo") or "").strip()
            if not codigo:
                continue
            filas.append(
                {
                    "codigo": codigo,
                    "descripcion": (row.get("descripcion") or "").strip(),
                }
            )
    return filas


def is_default_active(codigo: str) -> bool:
    if codigo in DEFAULT_CPVS:
        return True
    digitos = "".join(c for c in codigo if c.isdigit())
    return any(digitos.startswith(prefijo) for prefijo in DEFAULT_ACTIVE_PREFIXES)


def default_cpv_catalog() -> list[dict]:
    """Catálogo completo con columna Activo preseleccionada."""
    return [
        {
            "codigo": fila["codigo"],
            "descripcion": fila["descripcion"],
            "activo": is_default_active(fila["codigo"]),
        }
        for fila in load_cpv_rows()
    ]


def active_cpvs(catalogo: list[dict]) -> dict[str, str]:
    return {
        str(fila["codigo"]): str(fila.get("descripcion") or "")
        for fila in catalogo
        if fila.get("activo")
    }
