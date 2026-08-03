"""Criterios de búsqueda predeterminados para GREFA.

Este módulo centraliza los CPV y las palabras clave que definen el perfil de
interés de GREFA (Grupo de Rehabilitación de la Fauna Autóctona y su Hábitat).
Los valores aquí definidos son solo el punto de partida: la aplicación los copia
a `st.session_state` y el usuario puede añadirlos o eliminarlos en caliente.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Códigos CPV (Common Procurement Vocabulary)
# ---------------------------------------------------------------------------
# El matching es jerárquico: '77200000-2' también captura '77211500', '77231900',
# etc., porque comparte la raíz significativa del código ('772').
DEFAULT_CPVS: dict[str, str] = {
    "77200000-2": "Servicios forestales y de silvicultura",
    "90700000-4": "Servicios medioambientales",
    "90710000-7": "Gestión medioambiental",
    "90720000-0": "Protección de la naturaleza",
    "73000000-2": "Servicios de investigación y desarrollo",
}

# ---------------------------------------------------------------------------
# Palabras clave agrupadas por categoría temática
# ---------------------------------------------------------------------------
DEFAULT_KEYWORDS: dict[str, list[str]] = {
    "Fauna y conservación": [
        "fauna salvaje",
        "biodiversidad",
        "recuperación de fauna",
        "estudio de poblaciones",
        "marcado de aves",
        "telemetría",
        "control biológico",
    ],
    "Especies específicas": [
        "buitre negro",
        "águila de Bonelli",
        "cernícalo primilla",
        "topillo campesino",
        "galápago europeo",
    ],
    "Servicios y divulgación": [
        "educación ambiental",
        "centro de interpretación",
        "voluntariado ambiental",
    ],
}

# Categoría donde se depositan los términos que añade el usuario sin indicar grupo.
CUSTOM_KEYWORD_CATEGORY = "Añadidas por el usuario"

# ---------------------------------------------------------------------------
# Parámetros de scoring del Índice de Relevancia GREFA
# ---------------------------------------------------------------------------
CPV_WEIGHT = 50.0          # Puntos máximos por coincidencia de CPV
KEYWORD_WEIGHT = 50.0      # Puntos máximos por coincidencia de palabras clave

# Peso relativo según el campo donde aparece la palabra clave.
TITLE_HIT_WEIGHT = 1.0
DESCRIPTION_HIT_WEIGHT = 0.6

# Nº de coincidencias ponderadas necesarias para saturar los 50 puntos de keywords.
KEYWORD_SATURATION = 3.0

# Umbrales de categorización (en %)
HIGH_RELEVANCE_THRESHOLD = 70
MEDIUM_RELEVANCE_THRESHOLD = 40

RELEVANCE_LEVELS: dict[str, dict[str, str]] = {
    "Alta": {"badge": "Oportunidad GREFA", "color": "#1B873F", "emoji": "🟢"},
    "Media": {"badge": "Revisar", "color": "#B58100", "emoji": "🟡"},
    "Baja": {"badge": "Descartable", "color": "#6B7280", "emoji": "⚪"},
}

# Estados PLACSP considerados «abiertos» (filtro por defecto).
ESTADOS_ABIERTOS_DEFAULT: tuple[str, ...] = (
    "Publicada",
    "En evaluación",
    "Anuncio previo",
)


def flatten_keywords(keywords: dict[str, list[str]]) -> list[str]:
    """Devuelve la lista plana y sin duplicados de todas las palabras clave."""
    plano: list[str] = []
    vistos: set[str] = set()
    for terminos in keywords.values():
        for termino in terminos:
            clave = termino.strip().lower()
            if clave and clave not in vistos:
                vistos.add(clave)
                plano.append(termino.strip())
    return plano


def default_criteria() -> tuple[dict[str, str], dict[str, list[str]]]:
    """Copias independientes de los criterios por defecto (evita mutar el módulo)."""
    return (
        dict(DEFAULT_CPVS),
        {categoria: list(terminos) for categoria, terminos in DEFAULT_KEYWORDS.items()},
    )
