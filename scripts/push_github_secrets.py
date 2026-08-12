#!/usr/bin/env python3
"""Sube a GitHub Actions los secrets mínimos para Sync diaria GREFA.

Lee `.streamlit/secrets.toml` local y ejecuta `gh secret set`.

Uso:
  python scripts/push_github_secrets.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib  # type: ignore


BASE = Path(__file__).resolve().parent.parent
SECRETS_PATH = BASE / ".streamlit" / "secrets.toml"


def _set_secret(nombre: str, valor: str) -> None:
    proc = subprocess.run(
        ["gh", "secret", "set", nombre],
        input=valor,
        text=True,
        capture_output=True,
        cwd=BASE,
    )
    if proc.returncode != 0:
        raise SystemExit(
            f"Error al definir {nombre}: {proc.stderr.strip() or proc.stdout.strip()}"
        )
    print(f"OK  {nombre} ({len(valor)} caracteres)")


def main() -> int:
    if not SECRETS_PATH.exists():
        print(f"No existe {SECRETS_PATH}")
        return 1

    data = tomllib.loads(SECRETS_PATH.read_text(encoding="utf-8"))
    sheets = data.get("sheets") or {}
    spreadsheet_id = (sheets.get("spreadsheet_id") or "").strip()
    if not spreadsheet_id:
        print("Falta [sheets].spreadsheet_id en secrets.toml")
        return 1

    sa = data.get("gcp_service_account")
    if not isinstance(sa, dict) or not sa.get("private_key"):
        print("Falta el bloque [gcp_service_account] en secrets.toml")
        return 1

    print("Comprobando autenticación de gh…")
    auth = subprocess.run(
        ["gh", "auth", "status"],
        capture_output=True,
        text=True,
        cwd=BASE,
    )
    if auth.returncode != 0:
        print(auth.stderr or auth.stdout)
        print("Ejecuta primero: gh auth login")
        return 1

    _set_secret("GREFA_SPREADSHEET_ID", spreadsheet_id)
    _set_secret("GOOGLE_SERVICE_ACCOUNT_JSON", json.dumps(sa, ensure_ascii=False))

    alerts = data.get("alerts") or {}
    opcionales = {
        "GREFA_ALERTS_SPACE_EMAIL": alerts.get("space_email"),
        "GREFA_SMTP_USER": alerts.get("smtp_user"),
        "GREFA_SMTP_PASSWORD": alerts.get("smtp_password"),
        "GREFA_SMTP_FROM": alerts.get("smtp_from"),
        "GOOGLE_CHAT_WEBHOOK_URL": alerts.get("google_chat_webhook"),
    }
    for nombre, valor in opcionales.items():
        if valor:
            _set_secret(nombre, str(valor).strip())

    app_url = (alerts.get("app_url") or "").strip()
    if app_url:
        proc = subprocess.run(
            ["gh", "variable", "set", "GREFA_APP_URL", "--body", app_url],
            capture_output=True,
            text=True,
            cwd=BASE,
        )
        if proc.returncode != 0:
            print(f"Aviso: no se pudo definir GREFA_APP_URL: {proc.stderr.strip()}")
        else:
            print(f"OK  variable GREFA_APP_URL")

    print("\nSecrets listos. Relanza el workflow con:")
    print("  gh workflow run daily-sync.yml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
