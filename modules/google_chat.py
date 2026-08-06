"""Alertas al espacio de Google Chat mediante webhook entrante (gratuito)."""

from __future__ import annotations

import logging
from typing import Any

import requests

from modules import alert_messages
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
    return alert_messages.format_nuevas_alta_chat_webhook(
        nuevas, app_url=app_url, total_alta=total_alta
    )
