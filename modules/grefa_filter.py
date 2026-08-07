"""Índice de Relevancia GREFA: scoring, categorización y filtrado.

El índice puntúa de 0 a 100 % cada licitación combinando dos bloques:

* **CPV (50 puntos):** coincidencia jerárquica con los CPV activos. El código
  ``77200000-2`` captura también ``77211500`` o ``77231900`` porque comparte la
  raíz significativa ``772`` (se ignoran los ceros de relleno del CPV).
* **Palabras clave (50 puntos):** reparto proporcional según cuántos términos
  distintos aparecen en el título o la descripción. Un acierto en el título pesa
  1,0 y en la descripción 0,6; con 3 puntos ponderados se satura el bloque.

Todas las funciones aceptan listas de criterios modificadas en caliente, por lo
que la interfaz puede recalcular el índice sin volver a descargar el feed.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Iterable, Sequence

import pandas as pd

from config.default_criteria import (
    CPV_WEIGHT,
    DESCRIPTION_HIT_WEIGHT,
    HIGH_RELEVANCE_THRESHOLD,
    KEYWORD_SATURATION,
    KEYWORD_WEIGHT,
    MEDIUM_RELEVANCE_THRESHOLD,
    RELEVANCE_LEVELS,
    TITLE_HIT_WEIGHT,
)

SCORING_COLUMNS: tuple[str, ...] = (
    "relevancia",
    "categoria",
    "badge",
    "color",
    "cpvs_match",
    "keywords_match",
    "justificacion",
)


# ---------------------------------------------------------------------------
# Normalización
# ---------------------------------------------------------------------------
def normalize_text(texto: str) -> str:
    """Minúsculas, sin tildes y con la puntuación convertida en separadores."""
    if texto is None:
        return ""
    try:
        if pd.isna(texto):
            return ""
    except (TypeError, ValueError):
        pass
    cadena = str(texto).strip()
    if not cadena:
        return ""
    descompuesto = unicodedata.normalize("NFKD", cadena)
    sin_tildes = "".join(caracter for caracter in descompuesto if not unicodedata.combining(caracter))
    limpio = re.sub(r"[^0-9a-zA-Z]+", " ", sin_tildes.lower())
    return f" {limpio.strip()} "


def normalize_cpv(codigo: str) -> str:
    """Deja el CPV en 8 dígitos, sin dígito de control ni separadores."""
    return re.sub(r"\D", "", str(codigo or ""))[:8]


def cpv_root(codigo: str) -> str:
    """Raíz significativa del CPV: '77200000' -> '772', '90710000' -> '9071'."""
    normalizado = normalize_cpv(codigo)
    if not normalizado:
        return ""
    raiz = normalizado.rstrip("0")
    return raiz or normalizado[:2]


def is_valid_cpv(codigo: str) -> bool:
    return len(normalize_cpv(codigo)) >= 2


# ---------------------------------------------------------------------------
# Coincidencias
# ---------------------------------------------------------------------------
@lru_cache(maxsize=256)
def _compiled_keywords(keywords: tuple[str, ...]) -> tuple[tuple[str, re.Pattern[str]], ...]:
    """Compila cada palabra clave a una expresión regular tolerante a plurales."""
    compiladas: list[tuple[str, re.Pattern[str]]] = []
    for termino in keywords:
        normalizado = normalize_text(termino).strip()
        if not normalizado:
            continue
        tokens = normalizado.split()
        patron = r"\s+".join(re.escape(token) for token in tokens)
        compiladas.append((termino, re.compile(rf"(?<![a-z0-9]){patron}(?:es|s)?(?![a-z0-9])")))
    return tuple(compiladas)


def matching_cpvs(cpvs_licitacion: Iterable[str], cpvs_criterio: Iterable[str]) -> list[str]:
    """CPV de la licitación que encajan (jerárquicamente) con los criterios."""
    raices = [raiz for raiz in (cpv_root(codigo) for codigo in cpvs_criterio) if raiz]
    coincidentes: list[str] = []
    for codigo in cpvs_licitacion or []:
        normalizado = normalize_cpv(codigo)
        if not normalizado:
            continue
        if any(normalizado.startswith(raiz) for raiz in raices) and normalizado not in coincidentes:
            coincidentes.append(normalizado)
    return coincidentes


def matching_keywords(titulo: str, descripcion: str, keywords: Sequence[str]) -> tuple[list[str], float]:
    """Palabras clave encontradas y su puntuación ponderada por campo."""
    titulo_norm = normalize_text(titulo)
    descripcion_norm = normalize_text(descripcion)
    encontradas: list[str] = []
    peso_total = 0.0
    for termino, patron in _compiled_keywords(tuple(keywords)):
        if patron.search(titulo_norm):
            encontradas.append(termino)
            peso_total += TITLE_HIT_WEIGHT
        elif patron.search(descripcion_norm):
            encontradas.append(termino)
            peso_total += DESCRIPTION_HIT_WEIGHT
    return encontradas, peso_total


def matching_keyword_concepts(
    titulo: str,
    descripcion: str,
    conceptos: Sequence[dict],
) -> tuple[list[str], float]:
    """Igual que ``matching_keywords``, pero cada concepto cuenta una sola vez.

    Un concepto puede tener varias formas (castellano, euskera, catalán, gallego).
    Si cualquiera coincide, se anota el castellano canónico y se suma el peso
    una sola vez (el máximo entre título y descripción).
    """
    from config.keyword_catalog import variants_of

    titulo_norm = normalize_text(titulo)
    descripcion_norm = normalize_text(descripcion)
    encontradas: list[str] = []
    peso_total = 0.0

    for concepto in conceptos:
        if not concepto.get("activo", True):
            continue
        variantes = variants_of(concepto)
        if not variantes:
            continue
        patrones = _compiled_keywords(tuple(variantes))
        en_titulo = any(patron.search(titulo_norm) for _, patron in patrones)
        en_descripcion = any(patron.search(descripcion_norm) for _, patron in patrones)
        if not en_titulo and not en_descripcion:
            continue
        canonico = str(concepto.get("castellano") or variantes[0])
        encontradas.append(canonico)
        peso_total += TITLE_HIT_WEIGHT if en_titulo else DESCRIPTION_HIT_WEIGHT
    return encontradas, peso_total


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def classify(relevancia: float) -> str:
    if relevancia >= HIGH_RELEVANCE_THRESHOLD:
        return "Alta"
    if relevancia >= MEDIUM_RELEVANCE_THRESHOLD:
        return "Media"
    return "Baja"


def score_row(
    titulo: str,
    descripcion: str,
    cpvs: Iterable[str],
    cpvs_criterio: Sequence[str],
    keywords: Sequence[str],
    conceptos: Sequence[dict] | None = None,
) -> dict[str, object]:
    """Calcula el Índice de Relevancia GREFA de una única licitación."""
    cpvs_coincidentes = matching_cpvs(cpvs, cpvs_criterio)
    puntos_cpv = CPV_WEIGHT if cpvs_coincidentes else 0.0

    if conceptos:
        keywords_coincidentes, peso_keywords = matching_keyword_concepts(
            titulo, descripcion, conceptos
        )
    else:
        keywords_coincidentes, peso_keywords = matching_keywords(titulo, descripcion, keywords)
    saturacion = max(KEYWORD_SATURATION, 1e-9)
    puntos_keywords = KEYWORD_WEIGHT * min(peso_keywords / saturacion, 1.0)

    relevancia = int(round(min(puntos_cpv + puntos_keywords, 100.0)))
    categoria = classify(relevancia)
    nivel = RELEVANCE_LEVELS[categoria]

    motivos: list[str] = []
    if cpvs_coincidentes:
        motivos.append(f"CPV {', '.join(cpvs_coincidentes)} (+{int(puntos_cpv)}%)")
    else:
        motivos.append("Sin CPV coincidente (+0%)")
    if keywords_coincidentes:
        motivos.append(
            f"{len(keywords_coincidentes)} palabra(s) clave: "
            f"{', '.join(keywords_coincidentes)} (+{int(round(puntos_keywords))}%)"
        )
    else:
        motivos.append("Sin palabras clave (+0%)")

    return {
        "relevancia": relevancia,
        "categoria": categoria,
        "badge": nivel["badge"],
        "color": nivel["color"],
        "cpvs_match": cpvs_coincidentes,
        "keywords_match": keywords_coincidentes,
        "justificacion": " · ".join(motivos),
    }


def score_licitaciones(
    df: pd.DataFrame,
    cpvs: Iterable[str],
    keywords: Iterable[str],
    conceptos: Sequence[dict] | None = None,
) -> pd.DataFrame:
    """Añade al DataFrame las columnas del Índice de Relevancia GREFA."""
    cpvs_criterio = [codigo for codigo in (str(c).strip() for c in cpvs) if is_valid_cpv(codigo)]
    lista_keywords = [termino.strip() for termino in keywords if str(termino).strip()]
    conceptos_activos = [
        c for c in (conceptos or []) if c.get("activo", True)
    ] or None

    resultado = df.copy()
    if resultado.empty:
        for columna in SCORING_COLUMNS:
            resultado[columna] = pd.Series(dtype="object")
        resultado["relevancia"] = pd.Series(dtype="int64")
        return resultado

    puntuaciones = [
        score_row(
            fila.get("titulo", ""),
            fila.get("descripcion", ""),
            fila.get("cpvs", []),
            cpvs_criterio,
            lista_keywords,
            conceptos=conceptos_activos,
        )
        for fila in resultado.to_dict("records")
    ]

    marcadores = pd.DataFrame(puntuaciones, index=resultado.index)
    for columna in SCORING_COLUMNS:
        resultado[columna] = marcadores[columna]

    resultado["relevancia"] = resultado["relevancia"].astype(int)
    resultado = resultado.sort_values(
        by=["relevancia", "fecha_actualizacion"],
        ascending=[False, False],
        na_position="last",
    ).reset_index(drop=True)
    return resultado


# ---------------------------------------------------------------------------
# Filtros de apoyo para la interfaz
# ---------------------------------------------------------------------------
def filter_opportunities(
    df: pd.DataFrame,
    min_relevancia: int = MEDIUM_RELEVANCE_THRESHOLD,
    categorias: Sequence[str] | None = None,
    estados: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Licitaciones que superan el umbral de relevancia solicitado."""
    if df.empty:
        return df
    filtrado = df[df["relevancia"] >= int(min_relevancia)]
    if categorias is not None:
        cats = [str(c).strip() for c in categorias if str(c).strip()]
        if not cats:
            return df.iloc[0:0].copy()
        filtrado = filtrado[filtrado["categoria"].astype(str).str.strip().isin(cats)]
    filtrado = filter_by_estado(filtrado, estados)
    return filtrado.reset_index(drop=True)


def filter_by_estado(df: pd.DataFrame, estados: Sequence[str] | None) -> pd.DataFrame:
    """Filtra por estado PLACSP. Lista vacía o ``None`` = sin filtrar."""
    if df.empty or not estados:
        return df
    lista = [str(e).strip() for e in estados if str(e).strip()]
    if not lista:
        return df
    return df[df["estado"].isin(lista)]


def _valor_texto(val) -> str:
    """Convierte celdas heterogéneas (NA, listas, NaN) a texto seguro."""
    if val is None:
        return ""
    try:
        if pd.isna(val):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(val, (list, tuple)):
        return " ".join(_valor_texto(item) for item in val)
    return str(val)


def _coerce_timestamp(val) -> pd.Timestamp | None:
    if val is None:
        return None
    try:
        if pd.isna(val):
            return None
    except (TypeError, ValueError):
        pass
    return pd.Timestamp(val)


def _columna_texto(df: pd.DataFrame, nombre: str) -> pd.Series:
    if nombre not in df.columns:
        return pd.Series("", index=df.index, dtype="object")
    return df[nombre].map(_valor_texto)


def filter_by_fechas(
    df: pd.DataFrame,
    campo: str = "fecha_actualizacion",
    desde: pd.Timestamp | None = None,
    hasta: pd.Timestamp | None = None,
    incluir_sin_fecha: bool = True,
) -> pd.DataFrame:
    """Filtra por rango de fechas en ``fecha_actualizacion`` o ``fecha_limite``."""
    if df.empty or campo not in df.columns or (desde is None and hasta is None):
        return df

    desde_ts = _coerce_timestamp(desde)
    hasta_ts = _coerce_timestamp(hasta)
    if desde_ts is None and hasta_ts is None:
        return df

    fechas = pd.to_datetime(df[campo], errors="coerce")
    mascara = pd.Series(True, index=df.index)
    if desde_ts is not None:
        cond_desde = fechas >= desde_ts.normalize()
        mascara &= cond_desde if not incluir_sin_fecha else (fechas.isna() | cond_desde)
    if hasta_ts is not None:
        limite = hasta_ts.normalize() + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
        cond_hasta = fechas <= limite
        mascara &= cond_hasta if not incluir_sin_fecha else (fechas.isna() | cond_hasta)
    return df[mascara].reset_index(drop=True)


def _campo_busqueda_texto(df: pd.DataFrame) -> pd.Series:
    """Texto concatenado y normalizado para búsqueda libre (sin depender del catálogo)."""
    blob = (
        _columna_texto(df, "titulo")
        + " "
        + _columna_texto(df, "descripcion")
        + " "
        + _columna_texto(df, "organo_contratacion")
        + " "
        + _columna_texto(df, "expediente")
        + " "
        + _columna_texto(df, "cpvs_texto")
        + " "
        + _columna_texto(df, "ubicacion")
        + " "
        + _columna_texto(df, "estado")
        + " "
        + _columna_texto(df, "tipo_contrato")
        + " "
        + _columna_texto(df, "keywords_match")
        + " "
        + _columna_texto(df, "nif_organo")
        + " "
        + _columna_texto(df, "nif_adjudicatario")
        + " "
        + _columna_texto(df, "adjudicatario")
    )
    return blob.map(normalize_text)


def filter_by_texto_libre(df: pd.DataFrame, texto: str = "") -> pd.DataFrame:
    """Búsqueda libre en todos los campos textuales, sin usar el catálogo de términos."""
    if df.empty or not texto or not texto.strip():
        return df
    terminos = [t for t in normalize_text(texto).split() if t]
    if not terminos:
        return df
    campos = _campo_busqueda_texto(df)
    mascara = pd.Series(True, index=df.index)
    for termino in terminos:
        mascara &= campos.str.contains(re.escape(termino), regex=True, na=False)
    return df[mascara].reset_index(drop=True)


def apply_filtros_busqueda(
    df: pd.DataFrame,
    texto: str = "",
    fecha_campo: str = "fecha_actualizacion",
    fecha_desde: pd.Timestamp | None = None,
    fecha_hasta: pd.Timestamp | None = None,
    incluir_sin_fecha: bool = True,
) -> pd.DataFrame:
    """Búsqueda libre + rango de fechas (global, independiente del scoring GREFA)."""
    filtrado = filter_by_texto_libre(df, texto)
    filtrado = filter_by_fechas(
        filtrado,
        campo=fecha_campo,
        desde=fecha_desde,
        hasta=fecha_hasta,
        incluir_sin_fecha=incluir_sin_fecha,
    )
    return filtrado


def with_nivel_administracion(df: pd.DataFrame) -> pd.DataFrame:
    """Añade o completa la columna ``nivel_administracion``."""
    if df.empty:
        return df
    from modules.admin_ambito import classify_organo

    copia = df.copy()
    if "nivel_administracion" not in copia.columns:
        copia["nivel_administracion"] = ""
    vacios = copia["nivel_administracion"].fillna("").astype(str).str.strip() == ""
    if vacios.any():
        copia.loc[vacios, "nivel_administracion"] = copia.loc[vacios, "organo_contratacion"].map(
            classify_organo
        )
    return copia


def filter_by_nivel_administracion(
    df: pd.DataFrame,
    niveles: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Filtra por ámbito del órgano: Nacional, Autonómico, Local u Otros."""
    if df.empty or not niveles:
        return df
    seleccion = {str(nivel).strip() for nivel in niveles if str(nivel).strip()}
    if not seleccion:
        return df
    enriquecido = with_nivel_administracion(df)
    return enriquecido[
        enriquecido["nivel_administracion"].astype(str).isin(seleccion)
    ].reset_index(drop=True)


def _normalizar_expediente(valor: str) -> str:
    """Minúsculas y solo alfanuméricos, para comparar IDs con distintos separadores."""
    return re.sub(r"[^0-9a-z]+", "", str(valor or "").strip().lower())


def filter_by_expediente(df: pd.DataFrame, expediente: str = "") -> pd.DataFrame:
    """Búsqueda por ID de expediente (parcial, tolerante a guiones/espacios/mayúsculas).

    También mira la URL PLACSP, porque a veces el código visible no coincide
    exactamente con el ContractFolderID del feed.
    """
    if df.empty or not expediente or not str(expediente).strip():
        return df

    objetivo_raw = str(expediente).strip().lower()
    objetivo_norm = _normalizar_expediente(objetivo_raw)
    if not objetivo_norm:
        return df

    serie_exp = df["expediente"].fillna("").astype(str)
    serie_url = df["url"].fillna("").astype(str) if "url" in df.columns else pd.Series("", index=df.index)
    serie_tit = df["titulo"].fillna("").astype(str) if "titulo" in df.columns else pd.Series("", index=df.index)

    exp_lower = serie_exp.str.lower()
    url_lower = serie_url.str.lower()
    mascara = exp_lower.str.contains(re.escape(objetivo_raw), regex=True, na=False)
    mascara |= url_lower.str.contains(re.escape(objetivo_raw), regex=True, na=False)

    if len(objetivo_norm) >= 4:
        exp_norm = serie_exp.map(_normalizar_expediente)
        url_norm = url_lower.map(_normalizar_expediente)
        tit_norm = serie_tit.map(_normalizar_expediente)
        mascara |= exp_norm.str.contains(objetivo_norm, regex=False, na=False)
        mascara |= url_norm.str.contains(objetivo_norm, regex=False, na=False)
        mascara |= tit_norm.str.contains(objetivo_norm, regex=False, na=False)

    return df[mascara].reset_index(drop=True)


def filter_by_nif(
    df: pd.DataFrame,
    nif: str = "",
    *,
    ambito: str = "ambos",
) -> pd.DataFrame:
    """Filtra por NIF del órgano, adjudicatario o ambos."""
    if df.empty or not nif or not str(nif).strip():
        return df
    from modules.ingestion import _normalizar_nif

    objetivo = _normalizar_nif(str(nif))
    if not objetivo:
        return df

    def coincide(serie: pd.Series) -> pd.Series:
        return serie.fillna("").astype(str).map(_normalizar_nif).str.contains(objetivo, na=False)

    mascara = pd.Series(False, index=df.index)
    if ambito in {"organo", "ambos"} and "nif_organo" in df.columns:
        mascara |= coincide(df["nif_organo"])
    if ambito in {"adjudicatario", "ambos"} and "nif_adjudicatario" in df.columns:
        mascara |= coincide(df["nif_adjudicatario"])
    return df[mascara].reset_index(drop=True)


def search_dataframe(
    df: pd.DataFrame,
    texto: str = "",
    presupuesto_min: float | None = None,
    presupuesto_max: float | None = None,
    ubicaciones: Sequence[str] | None = None,
    estados: Sequence[str] | None = None,
    incluir_sin_presupuesto: bool = True,
    fecha_campo: str = "fecha_actualizacion",
    fecha_desde: pd.Timestamp | None = None,
    fecha_hasta: pd.Timestamp | None = None,
    incluir_sin_fecha: bool = True,
    nif: str = "",
    nif_ambito: str = "ambos",
    expediente: str = "",
    niveles_admin: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Búsqueda libre y filtros del buscador general."""
    if df.empty:
        return df

    filtrado = df
    if expediente and str(expediente).strip():
        filtrado = filter_by_expediente(filtrado, expediente)
    if texto and texto.strip():
        filtrado = filter_by_texto_libre(filtrado, texto)
    if nif and str(nif).strip():
        filtrado = filter_by_nif(filtrado, nif, ambito=nif_ambito)
    # Con búsqueda directa por NIF/expediente no aplicar ámbito: muchos órganos
    # caen en «Otros» y el filtro los ocultaba aunque el NIF coincidiera.
    busqueda_directa = bool(
        (nif and str(nif).strip()) or (expediente and str(expediente).strip())
    )
    if niveles_admin and not busqueda_directa:
        filtrado = filter_by_nivel_administracion(filtrado, niveles_admin)

    if presupuesto_min is not None or presupuesto_max is not None:
        importes = filtrado["presupuesto_sin_iva"]
        mascara = pd.Series(True, index=filtrado.index)
        if presupuesto_min is not None:
            mascara &= importes >= presupuesto_min
        if presupuesto_max is not None:
            mascara &= importes <= presupuesto_max
        if incluir_sin_presupuesto:
            mascara |= importes.isna()
        filtrado = filtrado[mascara]

    if ubicaciones:
        filtrado = filtrado[filtrado["ubicacion"].isin(list(ubicaciones))]
    filtrado = filter_by_estado(filtrado, estados)
    filtrado = filter_by_fechas(
        filtrado,
        campo=fecha_campo,
        desde=fecha_desde,
        hasta=fecha_hasta,
        incluir_sin_fecha=incluir_sin_fecha,
    )

    if "organo_contratacion" in filtrado.columns:
        filtrado = with_nivel_administracion(filtrado)
    return filtrado.reset_index(drop=True)


def summarize(df: pd.DataFrame) -> dict[str, int | float]:
    """Métricas rápidas para la cabecera del panel."""
    if df.empty:
        return {"total": 0, "alta": 0, "media": 0, "baja": 0, "importe_oportunidades": 0.0}
    conteo = df["categoria"].value_counts()
    oportunidades = df[df["categoria"].isin(["Alta", "Media"])]
    return {
        "total": int(len(df)),
        "alta": int(conteo.get("Alta", 0)),
        "media": int(conteo.get("Media", 0)),
        "baja": int(conteo.get("Baja", 0)),
        "importe_oportunidades": float(oportunidades["presupuesto_sin_iva"].fillna(0).sum()),
    }
