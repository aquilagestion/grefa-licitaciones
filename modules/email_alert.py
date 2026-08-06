"""Alertas por email al espacio de Google Chat (sin webhook)."""

from __future__ import annotations

import logging
import os
import smtplib
from email.mime.text import MIMEText

from modules.sheets_store import _secret

LOGGER = logging.getLogger(__name__)

TIMEOUT = 30


def space_email() -> str | None:
    destino = _secret("alerts", "space_email") or os.environ.get("GREFA_ALERTS_SPACE_EMAIL")
    if destino:
        return str(destino).strip()
    return None


def _smtp_config() -> dict[str, str | int] | None:
    usuario = _secret("alerts", "smtp_user") or os.environ.get("GREFA_SMTP_USER")
    clave = _secret("alerts", "smtp_password") or os.environ.get("GREFA_SMTP_PASSWORD")
    if not usuario or not clave:
        return None
    host = str(_secret("alerts", "smtp_host") or os.environ.get("GREFA_SMTP_HOST") or "smtp.gmail.com")
    port = int(_secret("alerts", "smtp_port") or os.environ.get("GREFA_SMTP_PORT") or 587)
    remitente = str(
        _secret("alerts", "smtp_from") or os.environ.get("GREFA_SMTP_FROM") or usuario
    ).strip()
    return {
        "host": host,
        "port": port,
        "user": str(usuario).strip(),
        "password": str(clave).strip(),
        "from_addr": remitente,
    }


def is_configured() -> bool:
    return bool(space_email() and _smtp_config())


def send_message(asunto: str, cuerpo: str) -> bool:
    """Envía email al espacio Chat. Devuelve True si SMTP aceptó el mensaje."""
    destino = space_email()
    cfg = _smtp_config()
    if not destino or not cfg:
        LOGGER.info("Alertas por email no configuradas; se omite el aviso.")
        return False
    if not asunto.strip() or not cuerpo.strip():
        return False

    mensaje = MIMEText(cuerpo, "plain", "utf-8")
    mensaje["Subject"] = asunto.strip()[:200]
    mensaje["From"] = str(cfg["from_addr"])
    mensaje["To"] = destino

    try:
        with smtplib.SMTP(str(cfg["host"]), int(cfg["port"]), timeout=TIMEOUT) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(str(cfg["user"]), str(cfg["password"]))
            smtp.send_message(mensaje)
        return True
    except smtplib.SMTPException as exc:
        LOGGER.warning("No se pudo enviar el email al espacio Chat: %s", exc)
        return False
    except OSError as exc:
        LOGGER.warning("Error de red SMTP: %s", exc)
        return False
