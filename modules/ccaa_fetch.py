"""Orquestador de conectores nativos CCAA (solo bajo demanda del Buscador)."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Any

import pandas as pd

from config.ccaa_sources import debe_consultar_nativa, etiqueta_fuente
from modules.ingestion import empty_dataframe

LOGGER = logging.getLogger(__name__)

#: (nombre CCAA canónico, fetcher, etiqueta corta)
Fetcher = Callable[..., pd.DataFrame]


def _fetchers() -> list[tuple[str, Fetcher, dict[str, Any]]]:
    from modules import (
        ingestion_catalunya,
        ingestion_euskadi,
        ingestion_madrid,
        ingestion_navarra,
    )

    return [
        (
            "País Vasco",
            ingestion_euskadi.fetch_euskadi_notices,
            {"max_pages": 4, "page_size": 50},
        ),
        (
            "Cataluña",
            ingestion_catalunya.fetch_catalunya_notices,
            {"limit": 200},
        ),
        (
            "Comunidad de Madrid",
            ingestion_madrid.fetch_madrid_notices,
            {},
        ),
        (
            "Comunidad Foral de Navarra",
            ingestion_navarra.fetch_navarra_notices,
            {"limit": 250},
        ),
    ]


def fetch_nativas(
    comunidades: Sequence[str] | None = None,
) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Descarga conectores nativos según filtro CCAA.

    Returns:
        (dataframe_combinado, mensajes_ok, mensajes_aviso)
    """
    partes: list[pd.DataFrame] = []
    oks: list[str] = []
    avisos: list[str] = []
    seleccion = list(comunidades or [])

    for nombre, fetcher, kwargs in _fetchers():
        if not debe_consultar_nativa(seleccion, nombre):
            continue
        try:
            df = fetcher(**kwargs)
            if df is None or df.empty:
                avisos.append(f"{nombre}: sin resultados nativos.")
                continue
            partes.append(df)
            fuente = str(df["fuente"].iloc[0]) if "fuente" in df.columns else nombre
            oks.append(
                f"{nombre}: **{len(df):,}** ({etiqueta_fuente(fuente)})"
            )
        except Exception as exc:
            LOGGER.warning("Conector %s falló: %s", nombre, exc)
            avisos.append(f"{nombre}: {exc}")

    if not partes:
        return empty_dataframe(), oks, avisos

    combinado = pd.concat(partes, ignore_index=True, sort=False)
    if "expediente" in combinado.columns:
        subset = (
            ["expediente", "url"] if "url" in combinado.columns else ["expediente"]
        )
        combinado = combinado.drop_duplicates(subset=subset, keep="first")
    return combinado.reset_index(drop=True), oks, avisos
