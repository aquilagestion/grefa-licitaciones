"""Catálogo de entidades a vigilar en ayudas/premios (BDNS + web).

Cada entidad es una cadena que debe aparecer en título/snippet/órgano para
contarse como acierto. El usuario puede añadir más desde la UI.
"""

from __future__ import annotations

from typing import TypedDict


class EntidadCatalogo(TypedDict):
    nombre: str
    notas: str
    activo: bool


DEFAULT_ENTIDADES: list[EntidadCatalogo] = [
    {"nombre": "Fundación Biodiversidad", "notas": "MITECO / ayudas ambientales", "activo": True},
    {"nombre": "Fundación BBVA", "notas": "Premios Biodiversidad y Conservación", "activo": True},
    {"nombre": "Fundación Iberdrola", "notas": "Premios y ayudas ambientales", "activo": True},
    {"nombre": "Fundación la Caixa", "notas": "Convocatorias sociales y ambientales", "activo": True},
    {"nombre": "SEO/BirdLife", "notas": "Premios y alianzas ornitología", "activo": True},
    {"nombre": "WWF España", "notas": "Premios y alianzas conservación", "activo": False},
    {"nombre": "Fundación Aquae", "notas": "Premios agua y sostenibilidad", "activo": False},
    {"nombre": "Premios Nacionales de Medio Ambiente", "notas": "Administración General del Estado", "activo": True},
]


def default_entidades() -> list[EntidadCatalogo]:
    return [dict(e) for e in DEFAULT_ENTIDADES]  # type: ignore[misc]


def active_entidades(catalogo: list[EntidadCatalogo] | list[dict]) -> list[str]:
    out: list[str] = []
    vistos: set[str] = set()
    for item in catalogo:
        if not item.get("activo", True):
            continue
        nombre = str(item.get("nombre") or "").strip()
        clave = nombre.lower()
        if not nombre or clave in vistos:
            continue
        vistos.add(clave)
        out.append(nombre)
    return out
