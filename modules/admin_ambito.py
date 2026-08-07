"""Clasificación heurística del órgano de contratación (local / autonómico / nacional)."""

from __future__ import annotations

import re
import unicodedata

NIVEL_NACIONAL = "Nacional"
NIVEL_AUTONOMICO = "Autonómico"
NIVEL_LOCAL = "Local"
NIVEL_OTROS = "Otros"

NIVELES_ADMIN = (NIVEL_NACIONAL, NIVEL_AUTONOMICO, NIVEL_LOCAL, NIVEL_OTROS)

_PATRONES_NACIONAL: tuple[re.Pattern[str], ...] = tuple(
    re.compile(patron, re.IGNORECASE)
    for patron in (
        r"\bministerio\b",
        r"secretar[ií]a de estado",
        r"subsecretar[ií]a",
        r"administraci[oó]n general del estado",
        r"\bage\b",
        r"agencia estatal",
        r"entidad p[uú]blica empresarial",
        r"instituto nacional",
        r"consejo superior de",
        r"delegaci[oó]n del gobierno",
        r"intervenci[oó]n general de la administraci[oó]n",
        r"tribunal superior de justicia",
        r"fuerzas armadas",
        r"defensa\b",
        r"guardia civil",
        r"polic[ií]a nacional",
        r"administraci[oó]n del estado",
        r"organismo aut[oó]nomo estatal",
    )
)

_PATRONES_AUTONOMICO: tuple[re.Pattern[str], ...] = tuple(
    re.compile(patron, re.IGNORECASE)
    for patron in (
        r"\bjunta de\b",
        r"\bgeneralitat\b",
        r"\bxunta de\b",
        r"gobierno (vasco|de navarra|de canarias|de arag[oó]n|de la rioja|de cantabria|de extremadura)",
        r"comunidad aut[oó]noma",
        r"comunidad de madrid",
        r"comunidad foral",
        r"diputaci[oó]n foral",
        r"\bconsell\b",
        r"conseller[ií]a",
        r"consejer[ií]a de",
        r"parlamento de",
        r"servicio (andaluz|madrile|vasco|catal|aragon|extreme|murciano|leon|asturiano)",
        r"salud de (castilla|galicia|andaluc|aragon|catalun|valencian)",
        r"presidencia de la (generalitat|junta|xunta)",
        r"vicepresidencia de",
        r"departament de",
        r"euskadi\b",
        r"pa[ií]s vasco",
        r"principado de asturias",
        r"regi[oó]n de murcia",
        r"ciudad aut[oó]noma de",
    )
)

_PATRONES_LOCAL: tuple[re.Pattern[str], ...] = tuple(
    re.compile(patron, re.IGNORECASE)
    for patron in (
        r"\bayuntamiento\b",
        r"\bmunicipio de\b",
        r"\bconcejo de\b",
        r"corporaci[oó]n municipal",
        r"alcald[ií]a de",
        r"diputaci[oó]n provincial",
        r"\bdiputaci[oó]n de\b",
        r"\bmancomunidad\b",
        r"\bcabildo\b",
        r"concello de",
        r"ajuntament de",
        r"excmo\.?\s*ayuntamiento",
        r"ilmo\.?\s*ayuntamiento",
        r"organismo aut[oó]nomo local",
        r"entidad local\b",
        r"consorcio de municipios",
    )
)


def _normalizar_nombre(organo: str) -> str:
    if not organo:
        return ""
    descompuesto = unicodedata.normalize("NFKD", str(organo))
    sin_tildes = "".join(c for c in descompuesto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sin_tildes).strip().lower()


def _coincide(texto: str, patrones: tuple[re.Pattern[str], ...]) -> bool:
    return any(patron.search(texto) for patron in patrones)


def classify_organo(organo: str) -> str:
    """Devuelve Nacional, Autonómico, Local u Otros según el nombre del órgano."""
    texto = _normalizar_nombre(organo)
    if not texto:
        return NIVEL_OTROS
    if _coincide(texto, _PATRONES_NACIONAL):
        return NIVEL_NACIONAL
    if _coincide(texto, _PATRONES_AUTONOMICO):
        return NIVEL_AUTONOMICO
    if _coincide(texto, _PATRONES_LOCAL):
        return NIVEL_LOCAL
    return NIVEL_OTROS
