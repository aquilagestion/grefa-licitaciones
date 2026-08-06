#!/usr/bin/env python3
"""Envía un email de prueba al espacio de Google Chat."""

from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from modules import email_alert  # noqa: E402


def main() -> int:
    if not email_alert.is_configured():
        print("Falta configurar [alerts] space_email + smtp_user + smtp_password")
        return 1
    ok = email_alert.send_message(
        "GREFA: prueba de alertas",
        "Si ves este mensaje en el espacio de Chat, las alertas por email funcionan.",
    )
    print("OK" if ok else "ERROR al enviar")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
