"""Sincronización diaria: histórico en Sheets + alerta Google Chat."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from modules import google_chat, sheets_historico, sheets_store

LOGGER = logging.getLogger(__name__)


@dataclass
class SyncResult:
    ejecutado: bool = False
    omitido: bool = False
    motivo: str = ""
    filas_historico: int = 0
    nuevas_alta: int = 0
    chat_enviado: bool = False
    detalle_nuevas: list[dict[str, Any]] = field(default_factory=list)

    def resumen(self) -> str:
        if self.omitido:
            return f"Sync omitida: {self.motivo}"
        if not self.ejecutado:
            return self.motivo or "Sync no ejecutada."
        partes = [f"Histórico: +{self.filas_historico} filas"]
        partes.append(f"Nuevas Alta: {self.nuevas_alta}")
        if self.chat_enviado:
            partes.append("Aviso enviado a Google Chat")
        return " · ".join(partes)


def _app_url() -> str:
    return google_chat.app_url()


def run_daily_sync(
    puntuadas: pd.DataFrame,
    *,
    forzar: bool = False,
    hoja_id: str | None = None,
) -> SyncResult:
    """Guarda snapshot en Histórico y avisa por Chat de nuevas Alta."""
    resultado = SyncResult()

    if not sheets_store.is_configured():
        resultado.omitido = True
        resultado.motivo = "Google Sheets no configurado"
        return resultado

    if not forzar and sheets_historico.ya_ejecutado_hoy(hoja_id):
        resultado.omitido = True
        resultado.motivo = "ya ejecutada hoy"
        return resultado

    try:
        claves_vistas = sheets_historico.load_claves_alta_vistas(hoja_id)
        nuevas, claves_actuales = sheets_historico.detectar_nuevas_alta(
            puntuadas, claves_vistas, hoja_id
        )
        resultado.filas_historico = sheets_historico.append_historico_snapshot(
            puntuadas, hoja_id=hoja_id
        )
        sheets_historico.save_claves_alta_vistas(claves_actuales, hoja_id)
        sheets_historico.marcar_ejecutado_hoy(hoja_id)

        resultado.ejecutado = True
        resultado.nuevas_alta = len(nuevas)
        resultado.detalle_nuevas = nuevas

        if nuevas and google_chat.is_configured():
            total_alta = int((puntuadas["categoria"] == "Alta").sum()) if not puntuadas.empty else 0
            texto = google_chat.format_nuevas_alta(
                nuevas, app_url=_app_url(), total_alta=total_alta
            )
            resultado.chat_enviado = google_chat.send_message(texto)
        elif nuevas:
            resultado.motivo = "Hay nuevas Alta pero Google Chat no está configurado"
    except sheets_store.SheetsError as exc:
        resultado.motivo = str(exc)
        LOGGER.warning("Sync diaria fallida: %s", exc)
    except Exception as exc:
        resultado.motivo = f"Error inesperado: {exc}"
        LOGGER.exception("Sync diaria fallida")

    return resultado
