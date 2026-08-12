"""Catálogo de fuentes de licitaciones por comunidad autónoma.

Fase 0–3: cobertura de las 17 CCAA vía PLACSP (643/1044) + conectores nativos
donde hay API/ATOM/RSS/CKAN estable. El resto se filtra por territorio/órgano.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

import pandas as pd

#: Identificadores de fuente PLACSP (columna ``fuente`` del DataFrame).
FUENTE_PLACSP_643 = "placsp_643"
FUENTE_PLACSP_1044 = "placsp_1044"
FUENTE_PLACSP_LOCAL = "placsp_local"
FUENTE_PLACSP = "placsp"
FUENTE_EUSKADI = "euskadi"
FUENTE_CATALUNYA = "catalunya"
FUENTE_MADRID = "madrid"
FUENTE_NAVARRA = "navarra"
FUENTE_GALICIA = "galicia"
FUENTE_ANDALUCIA = "andalucia"
# Versión de catálogo CCAA (fuerza recarga en Streamlit Cloud si cachea .py antiguos).
CCAA_SOURCES_VERSION = "2026-08-12-fase3-fix-import"

FUENTES_PLACSP: frozenset[str] = frozenset(
    {FUENTE_PLACSP_643, FUENTE_PLACSP_1044, FUENTE_PLACSP_LOCAL, FUENTE_PLACSP}
)

#: Etiquetas legibles de estado de cobertura (fase 3).
ETIQUETA_ESTADO_COBERTURA: dict[str, str] = {
    "nativa": "Nativa (API/feed propio)",
    "placsp_643": "PLACSP · perfiles (643)",
    "placsp_1044": "PLACSP · agregadas (1044)",
    "parcial": "Parcial",
}

#: Etiqueta UI para contratos de ámbito estatal / no territorial.
CCAA_ESTATAL = "Estatal (AGE y otros)"

#: Etiqueta cuando no se puede inferir CCAA.
CCAA_SIN_CLASIFICAR = "Sin clasificar"

#: Las 17 comunidades autónomas (orden oficial habitual).
CCAA_NOMBRES: tuple[str, ...] = (
    "Andalucía",
    "Aragón",
    "Principado de Asturias",
    "Illes Balears",
    "Canarias",
    "Cantabria",
    "Castilla-La Mancha",
    "Castilla y León",
    "Cataluña",
    "Comunitat Valenciana",
    "Extremadura",
    "Galicia",
    "Comunidad de Madrid",
    "Región de Murcia",
    "Comunidad Foral de Navarra",
    "País Vasco",
    "La Rioja",
)

#: Estados de cobertura: nativa | placsp_643 | placsp_1044 | parcial
EstadoCobertura = str


def _norm(texto: str) -> str:
    if not texto:
        return ""
    descompuesto = unicodedata.normalize("NFKD", str(texto))
    sin_tildes = "".join(c for c in descompuesto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sin_tildes).strip().lower()


#: Alias / provincias / topónimos → nombre canónico de CCAA.
_ALIAS_A_CCAA: dict[str, str] = {}
for _nombre, _aliases in (
    (
        "Andalucía",
        (
            "andalucia",
            "junta de andalucia",
            "almeria",
            "cadiz",
            "cordoba",
            "granada",
            "huelva",
            "jaen",
            "malaga",
            "sevilla",
        ),
    ),
    (
        "Aragón",
        ("aragon", "gobierno de aragon", "huesca", "teruel", "zaragoza"),
    ),
    (
        "Principado de Asturias",
        (
            "asturias",
            "principado de asturias",
            "oviedo",
            "gijon",
            "aviles",
        ),
    ),
    (
        "Illes Balears",
        (
            "illes balears",
            "islas baleares",
            "baleares",
            "mallorca",
            "menorca",
            "ibiza",
            "eivissa",
            "palma",
            "govern de les illes balears",
        ),
    ),
    (
        "Canarias",
        (
            "canarias",
            "gobierno de canarias",
            "las palmas",
            "santa cruz de tenerife",
            "tenerife",
            "gran canaria",
            "lanzarote",
            "fuerteventura",
            "la palma",
            "la gomera",
            "el hierro",
        ),
    ),
    (
        "Cantabria",
        ("cantabria", "gobierno de cantabria", "santander"),
    ),
    (
        "Castilla-La Mancha",
        (
            "castilla-la mancha",
            "castilla la mancha",
            "junta de comunidades de castilla",
            "albacete",
            "ciudad real",
            "cuenca",
            "guadalajara",
            "toledo",
        ),
    ),
    (
        "Castilla y León",
        (
            "castilla y leon",
            "junta de castilla y leon",
            "avila",
            "burgos",
            "leon",
            "palencia",
            "salamanca",
            "segovia",
            "soria",
            "valladolid",
            "zamora",
        ),
    ),
    (
        "Cataluña",
        (
            "cataluna",
            "catalunya",
            "generalitat de catalunya",
            "barcelona",
            "girona",
            "gerona",
            "lleida",
            "lerida",
            "tarragona",
        ),
    ),
    (
        "Comunitat Valenciana",
        (
            "comunitat valenciana",
            "comunidad valenciana",
            "generalitat valenciana",
            "alicante",
            "alacant",
            "castellon",
            "castello",
            "valencia",
            "valencia",
        ),
    ),
    (
        "Extremadura",
        ("extremadura", "junta de extremadura", "badajoz", "caceres"),
    ),
    (
        "Galicia",
        (
            "galicia",
            "xunta de galicia",
            "a coruna",
            "la coruna",
            "lugo",
            "ourense",
            "orense",
            "pontevedra",
            "vigo",
            "santiago de compostela",
        ),
    ),
    (
        "Comunidad de Madrid",
        (
            "comunidad de madrid",
            "madrid",
            "comunidad madrid",
            "ayuntamiento de madrid",
        ),
    ),
    (
        "Región de Murcia",
        ("region de murcia", "murcia", "comunidad autonoma de la region de murcia"),
    ),
    (
        "Comunidad Foral de Navarra",
        (
            "navarra",
            "comunidad foral de navarra",
            "gobierno de navarra",
            "nafarroa",
            "pamplona",
            "iruna",
        ),
    ),
    (
        "País Vasco",
        (
            "pais vasco",
            "euskadi",
            "gobierno vasco",
            "alava",
            "araba",
            "bizkaia",
            "vizcaya",
            "gipuzkoa",
            "guipuzcoa",
            "bilbao",
            "donostia",
            "san sebastian",
            "vitoria",
            "gasteiz",
            "diputacion foral",
        ),
    ),
    (
        "La Rioja",
        ("la rioja", "gobierno de la rioja", "logrono"),
    ),
):
    for _alias in _aliases:
        _ALIAS_A_CCAA[_norm(_alias)] = _nombre


#: Patrones de órgano estatal (AGE y asimilados).
_PATRONES_ESTATAL: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bministerio\b",
        r"administraci[oó]n general del estado",
        r"\bage\b",
        r"agencia estatal",
        r"instituto nacional",
        r"delegaci[oó]n del gobierno",
        r"guardia civil",
        r"polic[ií]a nacional",
        r"fuerzas armadas",
        r"organismo aut[oó]nomo estatal",
        r"entidad p[uú]blica empresarial",
        r"seguridad social",
        r"tesorer[ií]a general",
        r"agencia tributaria",
        r"\baeat\b",
        r"renfe\b",
        r"adif\b",
        r"correos\b",
        r"puertos del estado",
        r"aena\b",
    )
)


#: Catálogo estático: una entrada por CCAA (+ metadatos de cobertura PLACSP).
CCAA_SOURCES: tuple[dict[str, Any], ...] = (
    {
        "id": "andalucia",
        "nombre": "Andalucía",
        "portal": "Junta de Andalucía · open data menores + PLACSP 1044",
        "tipo": "nativa",
        "estado": "nativa",
        "url_base": "https://www.juntadeandalucia.es/datosabiertos/portal/dataset/contratacion-menor-plataforma-de-contratacion-andalucia-2026",
        "notas": "Conector open data de menores adjudicados (modules.ingestion_andalucia). El CSV del portal suele devolver 503; licitaciones abiertas vía PLACSP 1044.",
    },
    {
        "id": "aragon",
        "nombre": "Aragón",
        "portal": "PLACSP (perfiles alojados; remite desde Aragón)",
        "tipo": "placsp_643",
        "estado": "placsp_643",
        "url_base": "https://contrataciondelestado.es",
        "notas": "Perfiles en PLACSP desde 2018; sin feed nativo de anuncios vivos (fase 3).",
    },
    {
        "id": "asturias",
        "nombre": "Principado de Asturias",
        "portal": "PLACSP (perfiles alojados)",
        "tipo": "placsp_643",
        "estado": "placsp_643",
        "url_base": "https://contrataciondelestado.es",
        "notas": "Cobertura vía sindicación 643 + filtro territorial (fase 3).",
    },
    {
        "id": "baleares",
        "nombre": "Illes Balears",
        "portal": "PLACSP (DIR3 / perfiles alojados)",
        "tipo": "placsp_643",
        "estado": "placsp_643",
        "url_base": "https://contrataciondelestado.es",
        "notas": "Publica en PLACSP; cobertura 643 + filtro territorial (fase 3).",
    },
    {
        "id": "canarias",
        "nombre": "Canarias",
        "portal": "PLACSP (perfiles alojados)",
        "tipo": "placsp_643",
        "estado": "placsp_643",
        "url_base": "https://contrataciondelestado.es",
        "notas": "Cobertura vía sindicación 643 + filtro territorial (fase 3).",
    },
    {
        "id": "cantabria",
        "nombre": "Cantabria",
        "portal": "PLACSP (perfiles alojados)",
        "tipo": "placsp_643",
        "estado": "placsp_643",
        "url_base": "https://contrataciondelestado.es",
        "notas": "Cobertura vía sindicación 643 + filtro territorial (fase 3).",
    },
    {
        "id": "clm",
        "nombre": "Castilla-La Mancha",
        "portal": "PLACSP (perfiles alojados)",
        "tipo": "placsp_643",
        "estado": "placsp_643",
        "url_base": "https://contrataciondelestado.es",
        "notas": "Cobertura vía sindicación 643 + filtro territorial (fase 3).",
    },
    {
        "id": "cyl",
        "nombre": "Castilla y León",
        "portal": "PLACSP (perfiles alojados)",
        "tipo": "placsp_643",
        "estado": "placsp_643",
        "url_base": "https://contrataciondelestado.es",
        "notas": "Cobertura vía sindicación 643 + filtro territorial (fase 3).",
    },
    {
        "id": "catalunya",
        "nombre": "Cataluña",
        "portal": "Transparència Catalunya / Socrata",
        "tipo": "nativa",
        "estado": "nativa",
        "url_base": "https://analisi.transparenciacatalunya.cat",
        "notas": "Conector Socrata activo (modules.ingestion_catalunya); también en PLACSP 1044.",
    },
    {
        "id": "valencia",
        "nombre": "Comunitat Valenciana",
        "portal": "PLACSP (perfiles alojados)",
        "tipo": "placsp_643",
        "estado": "placsp_643",
        "url_base": "https://contrataciondelestado.es",
        "notas": "Sin API de anuncios vivos reutilizable; cobertura 643 + filtro (fase 3).",
    },
    {
        "id": "extremadura",
        "nombre": "Extremadura",
        "portal": "PLACSP (perfiles alojados)",
        "tipo": "placsp_643",
        "estado": "placsp_643",
        "url_base": "https://contrataciondelestado.es",
        "notas": "Cobertura vía sindicación 643 + filtro territorial (fase 3).",
    },
    {
        "id": "galicia",
        "nombre": "Galicia",
        "portal": "Contratos de Galicia (RSS) / PLACSP 1044",
        "tipo": "nativa",
        "estado": "nativa",
        "url_base": "https://www.contratosdegalicia.gal",
        "notas": "Conector RSS (modules.ingestion_galicia); si el portal no responde desde Cloud, cobertura vía PLACSP 1044.",
    },
    {
        "id": "madrid",
        "nombre": "Comunidad de Madrid",
        "portal": "Contratos Públicos Comunidad de Madrid (ATOM)",
        "tipo": "nativa",
        "estado": "nativa",
        "url_base": "https://contratos-publicos.comunidad.madrid/feed/licitaciones2",
        "notas": "Conector ATOM activo (modules.ingestion_madrid); también en PLACSP 1044.",
    },
    {
        "id": "murcia",
        "nombre": "Región de Murcia",
        "portal": "PLACSP agregación (1044)",
        "tipo": "placsp_1044",
        "estado": "placsp_1044",
        "url_base": "https://contrataciondelestado.es",
        "notas": "Agregación a PLACSP 1044; sin API nativa documentada (fase 3).",
    },
    {
        "id": "navarra",
        "nombre": "Comunidad Foral de Navarra",
        "portal": "datosabiertos.navarra.es (CKAN)",
        "tipo": "nativa",
        "estado": "nativa",
        "url_base": "https://datosabiertos.navarra.es/dataset/anuncios-licitaciones",
        "notas": "Conector CKAN/CSV activo (modules.ingestion_navarra); también en PLACSP 1044.",
    },
    {
        "id": "euskadi",
        "nombre": "País Vasco",
        "portal": "api.euskadi.eus / contracting-notices",
        "tipo": "nativa",
        "estado": "nativa",
        "url_base": "https://api.euskadi.eus/procurements/contracting-notices",
        "notas": "Conector REST activo (modules.ingestion_euskadi); también en PLACSP 1044.",
    },
    {
        "id": "rioja",
        "nombre": "La Rioja",
        "portal": "PLACSP (remite a la plataforma estatal)",
        "tipo": "placsp_643",
        "estado": "placsp_643",
        "url_base": "https://contrataciondelestado.es",
        "notas": "Remite a PLACSP; cobertura vía sindicación 643 (fase 3).",
    },
)


def ccaa_por_nombre() -> dict[str, dict[str, Any]]:
    return {entrada["nombre"]: entrada for entrada in CCAA_SOURCES}


def etiqueta_estado_cobertura(estado: str) -> str:
    """Etiqueta legible del estado de cobertura de una CCAA."""
    clave = str(estado or "").strip()
    return ETIQUETA_ESTADO_COBERTURA.get(clave, clave or "—")


def nombres_nativas() -> tuple[str, ...]:
    """CCAA con conector nativo activo."""
    return tuple(
        e["nombre"] for e in CCAA_SOURCES if e.get("estado") == "nativa"
    )


def tabla_cobertura() -> pd.DataFrame:
    """Tabla de estado de cobertura de las 17 CCAA (para UI)."""
    filas = [
        {
            "Comunidad": e["nombre"],
            "Cobertura": etiqueta_estado_cobertura(str(e.get("estado") or "")),
            "Portal": e.get("portal") or "—",
            "Notas": e.get("notas") or "",
        }
        for e in CCAA_SOURCES
    ]
    return pd.DataFrame(filas)


def opciones_filtro_buscador() -> list[str]:
    """Opciones del multiselect del Buscador: Estatal + 17 CCAA + Sin clasificar."""
    return [CCAA_ESTATAL, *CCAA_NOMBRES, CCAA_SIN_CLASIFICAR]


def etiqueta_fuente(fuente: str) -> str:
    """Etiqueta legible para la columna ``fuente``."""
    mapa = {
        FUENTE_PLACSP_643: "PLACSP · perfiles (643)",
        FUENTE_PLACSP_1044: "PLACSP · agregadas (1044)",
        FUENTE_PLACSP_LOCAL: "PLACSP · fichero local",
        FUENTE_PLACSP: "PLACSP",
        FUENTE_EUSKADI: "País Vasco · API Euskadi",
        FUENTE_CATALUNYA: "Cataluña · PSCP/Socrata",
        FUENTE_MADRID: "Madrid · ATOM",
        FUENTE_NAVARRA: "Navarra · open data CSV",
        FUENTE_GALICIA: "Galicia · RSS Contratos",
        FUENTE_ANDALUCIA: "Andalucía · open data menores",
    }
    return mapa.get(str(fuente or "").strip(), str(fuente or "").strip() or "—")


def debe_consultar_nativa(comunidades: list[str] | None, ccaa_nombre: str) -> bool:
    """True si el filtro CCAA implica consultar el conector nativo de ``ccaa_nombre``.

    Vacío = todas las CCAA → sí se consulta (para enriquecer el resultado).
    """
    seleccion = [str(c).strip() for c in (comunidades or []) if str(c).strip()]
    if not seleccion:
        return True
    return ccaa_nombre in seleccion


def fuente_desde_url_feed(url: str) -> str:
    """Infiere el código de fuente a partir de la URL del feed ATOM."""
    u = (url or "").lower()
    if "sindicacion_643" in u or "perfilescontratante" in u:
        return FUENTE_PLACSP_643
    if "sindicacion_1044" in u or "plataformasagregadas" in u:
        return FUENTE_PLACSP_1044
    if not u:
        return FUENTE_PLACSP_LOCAL
    return FUENTE_PLACSP


def _resolver_alias(texto: str) -> str:
    """Busca coincidencia de alias en el texto (más largo primero)."""
    normalizado = _norm(texto)
    if not normalizado:
        return ""
    if normalizado in _ALIAS_A_CCAA:
        return _ALIAS_A_CCAA[normalizado]
    # Coincidencia por contención: prioriza alias más largos.
    candidatos = sorted(_ALIAS_A_CCAA.items(), key=lambda kv: len(kv[0]), reverse=True)
    for alias, nombre in candidatos:
        if len(alias) < 4:
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", normalizado):
            return nombre
    return ""


def infer_comunidad_autonoma(
    ubicacion: str = "",
    organo: str = "",
    *,
    incluir_estatal: bool = True,
) -> str:
    """Infiere la CCAA a partir de ubicación y/o órgano de contratación.

    Orden: ubicación → órgano → patrones estatales → sin clasificar.
    """
    for campo in (ubicacion, organo):
        hallado = _resolver_alias(campo)
        if hallado:
            return hallado

    if incluir_estatal:
        organo_n = _norm(organo)
        if organo_n and any(p.search(organo_n) for p in _PATRONES_ESTATAL):
            return CCAA_ESTATAL

    return CCAA_SIN_CLASIFICAR if (ubicacion or organo) else CCAA_SIN_CLASIFICAR


def enrich_comunidad_autonoma(df: pd.DataFrame) -> pd.DataFrame:
    """Asegura la columna ``comunidad_autonoma`` en un DataFrame de licitaciones."""
    if df is None or df.empty:
        if df is not None and "comunidad_autonoma" not in df.columns:
            out = df.copy()
            out["comunidad_autonoma"] = pd.Series(dtype=str)
            return out
        return df

    out = df.copy()
    if "comunidad_autonoma" not in out.columns:
        out["comunidad_autonoma"] = ""

    vacios = out["comunidad_autonoma"].fillna("").astype(str).str.strip() == ""
    if vacios.any():
        ubic = (
            out.loc[vacios, "ubicacion"]
            if "ubicacion" in out.columns
            else pd.Series("", index=out.index[vacios])
        )
        organo = (
            out.loc[vacios, "organo_contratacion"]
            if "organo_contratacion" in out.columns
            else pd.Series("", index=out.index[vacios])
        )
        out.loc[vacios, "comunidad_autonoma"] = [
            infer_comunidad_autonoma(str(u or ""), str(o or ""))
            for u, o in zip(ubic.tolist(), organo.tolist())
        ]
    out["comunidad_autonoma"] = out["comunidad_autonoma"].fillna("").astype(str).str.strip()
    return out


def enrich_fuente(df: pd.DataFrame, fuente_default: str = FUENTE_PLACSP) -> pd.DataFrame:
    """Asegura la columna ``fuente`` con un valor por defecto si falta."""
    if df is None:
        return df
    out = df.copy()
    if "fuente" not in out.columns:
        out["fuente"] = fuente_default
    else:
        vacios = out["fuente"].fillna("").astype(str).str.strip() == ""
        if vacios.any():
            out.loc[vacios, "fuente"] = fuente_default
    out["fuente"] = out["fuente"].fillna("").astype(str).str.strip()
    return out
