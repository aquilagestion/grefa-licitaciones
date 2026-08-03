"""Inicializa la hoja de Google Sheets de GREFA.

Uso:
    set GREFA_SPREADSHEET_ID=1vR3VeFKuCU1NwnwXcN7fHXJgilpQaI3Jaj0HTSXhNXE
    set GOOGLE_APPLICATION_CREDENTIALS=C:\\ruta\\cuenta-servicio.json
    python scripts/init_sheets.py

También admite:
    python scripts/init_sheets.py --credentials cuenta-servicio.json --id ID_HOJA
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
DEFAULT_SHEET_ID = "1vR3VeFKuCU1NwnwXcN7fHXJgilpQaI3Jaj0HTSXhNXE"

if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))


def main() -> int:
    parser = argparse.ArgumentParser(description="Inicializa la hoja compartida de GREFA")
    parser.add_argument("--id", default=os.environ.get("GREFA_SPREADSHEET_ID", DEFAULT_SHEET_ID))
    parser.add_argument(
        "--credentials",
        default=os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", ""),
        help="Ruta al JSON de la cuenta de servicio",
    )
    parser.add_argument(
        "--sin-semilla",
        action="store_true",
        help="Crea pestañas y cabeceras sin cargar los CPV/palabras clave por defecto",
    )
    args = parser.parse_args()

    if args.credentials:
        ruta = Path(args.credentials).expanduser().resolve()
        if not ruta.exists():
            print(f"ERROR: no encuentro el fichero de credenciales: {ruta}")
            return 1
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(ruta)

    os.environ["GREFA_SPREADSHEET_ID"] = args.id

    from modules import sheets_store

    if not sheets_store.is_configured():
        print("ERROR: falta el ID de la hoja.")
        return 1

    print(f"Inicializando: {sheets_store.spreadsheet_url(args.id)}")
    try:
        resumen = sheets_store.initialize_spreadsheet(
            hoja_id=args.id,
            sembrar_criterios=not args.sin_semilla,
        )
    except sheets_store.SheetsError as exc:
        print(f"ERROR: {exc}")
        print(
            "\nComprueba que la hoja esté compartida como Editor con el "
            "client_email de la cuenta de servicio, y que las APIs "
            "Sheets y Drive estén habilitadas."
        )
        return 1

    print("Listo.")
    print(f"  CPV sembrados:           {resumen['cpvs']}")
    print(f"  Palabras clave sembradas: {resumen['keywords']}")
    print(f"  Oportunidades conservadas: {resumen['oportunidades']}")
    print(f"  Abrir: {sheets_store.spreadsheet_url(args.id)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
