#!/usr/bin/env python3
"""Job diario: descarga PLACSP, puntúa, guarda histórico y avisa al espacio Chat.

Uso local:
  python scripts/daily_sync.py

Variables de entorno:
  GREFA_SPREADSHEET_ID, GOOGLE_SERVICE_ACCOUNT_JSON (o GOOGLE_APPLICATION_CREDENTIALS)
  Alertas por email (opción recomendada si no hay webhooks):
    GREFA_ALERTS_SPACE_EMAIL, GREFA_SMTP_USER, GREFA_SMTP_PASSWORD
    GREFA_SMTP_FROM (opcional), GREFA_APP_URL
  Fallback webhook: GOOGLE_CHAT_WEBHOOK_URL
  GREFA_FEED_MAX_PAGES (default 2), GREFA_FEED_MAX_ENTRIES (default 500)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from config.default_criteria import flatten_keywords  # noqa: E402
from config.keyword_catalog import active_keywords_grouped  # noqa: E402
from config.cpv_catalog import active_cpvs, default_cpv_catalog  # noqa: E402
from config.keyword_catalog import default_term_catalog  # noqa: E402
from modules import daily_sync, grefa_filter, sheets_catalog, sheets_store  # noqa: E402
from modules.ingestion import fetch_placsp_licitaciones, PRIMARY_FEED_URL  # noqa: E402


def _cargar_criterios() -> tuple[list[str], list[str], list[dict]]:
    if sheets_store.is_configured():
        try:
            cpvs, keywords, catalogo_cpv, catalogo_terminos = sheets_catalog.load_selection()
            return list(cpvs.keys()), flatten_keywords(keywords), catalogo_terminos
        except sheets_store.SheetsError as exc:
            print(f"Aviso: no se leyeron criterios de Sheets ({exc}); se usan valores por defecto.")

    catalogo_cpv = default_cpv_catalog()
    catalogo_terminos = default_term_catalog()
    return (
        list(active_cpvs(catalogo_cpv).keys()),
        flatten_keywords(active_keywords_grouped(catalogo_terminos)),
        catalogo_terminos,
    )


def _diagnostico_config() -> list[str]:
    """Lista qué falta para ejecutar en CI (sin revelar valores)."""
    faltan: list[str] = []
    if not sheets_store.is_configured():
        faltan.append("GREFA_SPREADSHEET_ID (o [sheets].spreadsheet_id en secrets.toml)")
    tiene_creds = bool(
        os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        or (
            os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
            and Path(os.environ["GOOGLE_APPLICATION_CREDENTIALS"]).exists()
        )
    )
    if not tiene_creds:
        # En local puede bastar secrets.toml / ADC; en Actions hace falta el JSON.
        if os.environ.get("GITHUB_ACTIONS") == "true":
            faltan.append("GOOGLE_SERVICE_ACCOUNT_JSON")
    return faltan


def main() -> int:
    faltan = _diagnostico_config()
    if faltan:
        print("ERROR: configuración incompleta para la sync diaria.")
        print("Falta configurar:")
        for item in faltan:
            print(f"  - {item}")
        if os.environ.get("GITHUB_ACTIONS") == "true":
            print(
                "En GitHub: Settings → Secrets and variables → Actions "
                "y define los secrets del workflow daily-sync.yml."
            )
        return 1

    max_pages = int(os.environ.get("GREFA_FEED_MAX_PAGES", "2"))
    max_entries = int(os.environ.get("GREFA_FEED_MAX_ENTRIES", "500"))
    feed_url = os.environ.get("GREFA_FEED_URL", PRIMARY_FEED_URL)

    print(f"Descargando feed (máx. {max_entries} expedientes, {max_pages} páginas)…")
    df = fetch_placsp_licitaciones(
        feed_url=feed_url, max_pages=max_pages, max_entries=max_entries
    )
    print(f"Descargados {len(df)} expedientes.")

    cpvs, keywords, conceptos = _cargar_criterios()
    conceptos_activos = [t for t in conceptos if t.get("activo")]
    puntuadas = grefa_filter.score_licitaciones(
        df, cpvs, keywords, conceptos=conceptos_activos
    )

    resultado = daily_sync.run_daily_sync(puntuadas, forzar=False)
    print(resultado.resumen())
    if resultado.detalle_nuevas:
        for fila in resultado.detalle_nuevas[:5]:
            print(f"  - {fila.get('expediente')}: {str(fila.get('titulo', ''))[:70]}")
    return 0 if resultado.ejecutado or resultado.omitido else 2


if __name__ == "__main__":
    raise SystemExit(main())
