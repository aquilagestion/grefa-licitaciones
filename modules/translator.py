"""Traducción automática de términos entre lenguas cooficiales del Estado.

Al añadir un concepto al catálogo, basta con escribirlo en castellano, euskera,
catalán o gallego: Google Translate detecta el idioma de origen y rellena las
otras columnas (vía ``deep-translator``, sin API key propia).
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache

LOGGER = logging.getLogger(__name__)

AUTO = "auto"
CASTELLANO = "es"
EUSKERA = "eu"
CATALAN = "ca"
GALEGO = "gl"

CAMPOS = ("castellano", "euskera", "catalan", "gallego")
CODIGO_POR_CAMPO = {
    "castellano": CASTELLANO,
    "euskera": EUSKERA,
    "catalan": CATALAN,
    "gallego": GALEGO,
}

PROPER_NOUN_RE = re.compile(r"^[A-Z0-9][A-Z0-9\s\-./]{0,24}$")


@lru_cache(maxsize=512)
def _translate_cached(texto: str, origen: str, destino: str) -> str:
    if not texto.strip():
        return ""
    if origen == destino:
        return texto.strip()
    try:
        from deep_translator import GoogleTranslator

        return GoogleTranslator(source=origen, target=destino).translate(texto.strip()) or texto.strip()
    except Exception as exc:
        LOGGER.warning("Traducción %s→%s fallida (%s): %s", origen, destino, texto[:40], exc)
        return texto.strip() if destino == origen else ""


def translate_to(texto: str, destino: str, origen: str = AUTO) -> str:
    """Traduce ``texto`` al idioma destino (es/eu/ca/gl). Origen ``auto`` detecta el idioma."""
    return _translate_cached(texto.strip(), origen, destino)


def complete_term_translations(
    castellano: str = "",
    euskera: str = "",
    catalan: str = "",
    gallego: str = "",
) -> dict[str, str]:
    """Completa las cuatro columnas a partir de la(s) rellenada(s) por el usuario."""
    entradas = {
        "castellano": castellano.strip(),
        "euskera": euskera.strip(),
        "catalan": catalan.strip(),
        "gallego": gallego.strip(),
    }
    rellenos = {k: v for k, v in entradas.items() if v}
    if not rellenos:
        return {campo: "" for campo in CAMPOS}

    # Texto fuente: castellano si existe; si no, el único campo rellenado.
    if "castellano" in rellenos:
        texto_fuente = rellenos["castellano"]
    elif len(rellenos) == 1:
        texto_fuente = next(iter(rellenos.values()))
    else:
        texto_fuente = rellenos.get("castellano") or next(iter(rellenos.values()))

    # Siglas / nombres propios: replicar en las cuatro columnas.
    if PROPER_NOUN_RE.match(texto_fuente):
        return {campo: texto_fuente for campo in CAMPOS}

    resultado: dict[str, str] = {}
    for campo in CAMPOS:
        if campo in rellenos:
            resultado[campo] = rellenos[campo]
            continue
        codigo_destino = CODIGO_POR_CAMPO[campo]
        resultado[campo] = translate_to(texto_fuente, codigo_destino, origen=AUTO)

    # Castellano canónico del catálogo.
    if not resultado.get("castellano"):
        resultado["castellano"] = translate_to(texto_fuente, CASTELLANO, origen=AUTO) or texto_fuente
    elif "castellano" not in rellenos:
        resultado["castellano"] = translate_to(texto_fuente, CASTELLANO, origen=AUTO) or resultado["castellano"]

    # Si el usuario escribió en otro idioma, conservar su texto en esa columna.
    for campo, valor in rellenos.items():
        resultado[campo] = valor

    return resultado


def complete_from_any(texto: str) -> dict[str, str]:
    """Atajo: un solo campo de entrada en cualquier idioma oficial."""
    texto = texto.strip()
    if not texto:
        return {campo: "" for campo in CAMPOS}
    if PROPER_NOUN_RE.match(texto):
        return {campo: texto for campo in CAMPOS}
    return {
        campo: translate_to(texto, CODIGO_POR_CAMPO[campo], origen=AUTO) or texto
        for campo in CAMPOS
    }


def a_espanol(texto: str) -> str:
    """Traduce un título/anuncio a castellano (origen auto: eu/ca/gl/es…)."""
    bruto = (texto or "").strip()
    if not bruto:
        return ""
    if PROPER_NOUN_RE.match(bruto):
        return bruto
    trad = translate_to(bruto, CASTELLANO, origen=AUTO)
    return (trad or bruto).strip()
