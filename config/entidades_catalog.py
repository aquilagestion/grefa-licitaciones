"""Catálogo de entidades a vigilar en ayudas/premios (sitio propio + BDNS + web).

Cada entidad tiene un nombre (cadena a contener) y, opcionalmente, la URL de su
web oficial donde se busca primero premios/concursos/convocatorias.
"""

from __future__ import annotations

from typing import TypedDict


class EntidadCatalogo(TypedDict):
    nombre: str
    web: str
    notas: str
    activo: bool


DEFAULT_ENTIDADES: list[EntidadCatalogo] = [
    {
        "nombre": "Fundación Biodiversidad",
        "web": "https://fundacion-biodiversidad.es/",
        "notas": "MITECO / ayudas ambientales",
        "activo": True,
    },
    {
        "nombre": "Fundación BBVA",
        "web": "https://www.fbbva.es/",
        "notas": "Premios Biodiversidad y Conservación",
        "activo": True,
    },
    {
        "nombre": "Fundación Iberdrola",
        "web": "https://www.fundacioniberdrolaespana.org/",
        "notas": "Premios y ayudas ambientales",
        "activo": True,
    },
    {
        "nombre": "Fundación la Caixa",
        "web": "https://fundacionlacaixa.org/",
        "notas": "Convocatorias sociales y ambientales",
        "activo": True,
    },
    {
        "nombre": "SEO/BirdLife",
        "web": "https://seo.org/",
        "notas": "Premios y alianzas ornitología",
        "activo": True,
    },
    {
        "nombre": "WWF España",
        "web": "https://www.wwf.es/",
        "notas": "Premios y alianzas conservación",
        "activo": False,
    },
    {
        "nombre": "Fundación Aquae",
        "web": "https://www.fundacionaquae.org/",
        "notas": "Premios agua y sostenibilidad",
        "activo": False,
    },
    {
        "nombre": "Premios Nacionales de Medio Ambiente",
        "web": "https://www.miteco.gob.es/",
        "notas": "Administración General del Estado",
        "activo": True,
    },
]


def default_entidades() -> list[EntidadCatalogo]:
    return [dict(e) for e in DEFAULT_ENTIDADES]  # type: ignore[misc]


def _normalizar_web(url: str) -> str:
    texto = str(url or "").strip()
    if not texto:
        return ""
    if not texto.startswith(("http://", "https://")):
        texto = "https://" + texto
    return texto


def normalizar_entidad(item: dict) -> EntidadCatalogo:
    return {
        "nombre": str(item.get("nombre") or "").strip(),
        "web": _normalizar_web(str(item.get("web") or item.get("url") or "")),
        "notas": str(item.get("notas") or "").strip(),
        "activo": bool(item.get("activo", True)),
    }


def active_entidades(catalogo: list[EntidadCatalogo] | list[dict]) -> list[str]:
    return [e["nombre"] for e in active_entidades_detalle(catalogo)]


def active_entidades_detalle(
    catalogo: list[EntidadCatalogo] | list[dict],
) -> list[EntidadCatalogo]:
    out: list[EntidadCatalogo] = []
    vistos: set[str] = set()
    for item in catalogo:
        ent = normalizar_entidad(item)
        if not ent.get("activo", True):
            continue
        nombre = ent["nombre"]
        clave = nombre.lower()
        if not nombre or clave in vistos:
            continue
        vistos.add(clave)
        out.append(ent)
    return out
