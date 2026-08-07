#!/usr/bin/env python3
"""Crea pestañas Historico, Config y Pliegos si no existen (sin tocar datos)."""

from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from modules import sheets_historico, sheets_store  # noqa: E402


def main() -> int:
    if not sheets_store.is_configured():
        print("ERROR: configure GREFA_SPREADSHEET_ID y credenciales.")
        return 1

    hoja_id = sheets_store.spreadsheet_id()
    print(f"Hoja: {sheets_store.spreadsheet_url(hoja_id)}")

    try:
        sheets_historico._worksheet_historico(hoja_id)
        print("  OK Historico (legado/sync)")
        for year in range(2021, 2027):
            sheets_historico._worksheet_year(year, hoja_id)
            print(f"  OK Historico_{year}")
        sheets_historico._worksheet_config(hoja_id)
        print("  OK Config")
        hoja = sheets_store.get_spreadsheet(hoja_id)
        sheets_store._worksheet(hoja, sheets_store.PLIEGOS_SHEET, sheets_store.PLIEGO_HEADERS)
        print("  OK Pliegos")
    except sheets_store.SheetsError as exc:
        print(f"ERROR: {exc}")
        return 1

    print("Listo. Recarga el libro en Drive.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
