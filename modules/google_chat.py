"""Alertas al espacio de Google Chat mediante webhook entrante (gratuito)."""

from __future__ import annotations

import logging
from typing import Any

import requests

from modules.sheets_store import _secret

LOGGER = logging.getLogger(__name__)

TIMEOUT = 15


def webhook_url() -> str | None:
    url = _secret("alerts", "google_chat_webhook") or _secret("google_chat_webhook")
    if url:
        return str(url).strip()
    import os

    return (os.environ.get("GOOGLE_CHAT_WEBHOOK_URL") or "").strip() or None


def app_url() -> str:
    import os

    return (
        os.environ.get("GREFA_APP_URL")
        or os.environ.get("STREAMLIT_APP_URL")
        or str(_secret("alerts", "app_url") or "")
        or "https://grefa-licitaciones.streamlit.app"
    ).strip()


def is_configured() -> bool:
    return bool(webhook_url())


def send_message(texto: str) -> bool:
    """Envía un mensaje de texto plano. Devuelve True si la API respondió OK."""
    url = webhook_url()
    if not url:
        LOGGER.info("Google Chat no configurado; se omite el aviso.")
        return False
    if not texto.strip():
        return False
    try:
        respuesta = requests.post(url, json={"text": texto[:4096]}, timeout=TIMEOUT)
        respuesta.raise_for_status()
        return True
    except requests.RequestException as exc:
        LOGGER.warning("No se pudo enviar el aviso a Google Chat: %s", exc)
        return False


def format_nuevas_alta(
    nuevas: list[dict[str, Any]],
    *,
    app_url: str = "",
    total_alta: int = 0,
) -> str:
    lineas = [
        f"🦅 *GREFA · Licitaciones* — {len(nuevas)} nueva(s) oportunidad(es) *Alta*",
    ]
    if total_alta:
        lineas.append(f"Total Alta en el monitor: {total_alta}")
    lineas.append("")
    for fila in nuevas[:8]:
        titulo = str(fila.get("titulo") or "")[:90]
        exp = str(fila.get("expediente") or "—")
        rel = fila.get("relevancia", "")
        lineas.append(f"• *{exp}* ({rel} %) — {titulo}")
    if len(nuevas) > 8:
        lineas.append(f"… y {len(nuevas) - 8} más.")
    if app_url:
        lineas.extend(["", f"<{app_url}|Abrir monitor GREFA>"])
    return "\n".join(lineas)
