#!/usr/bin/env python3
"""Importa histórico PLACSP desde ZIPs oficiales a Parquet local.

Ejemplos:
  python scripts/import_historico_placsp.py --year 2025
  python scripts/import_historico_placsp.py --zip C:\\descargas\\licitaciones_2024.zip
  python scripts/import_historico_placsp.py --year 2024 --year 2025 --max-files 50
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from modules import historico_placsp  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Importar histórico PLACSP a Parquet")
    parser.add_argument("--year", type=int, action="append", help="Año del ZIP oficial (repetible)")
    parser.add_argument("--zip", type=str, help="Ruta a un ZIP ya descargado")
    parser.add_argument("--max-files", type=int, default=None, help="Máx. ficheros .atom a procesar")
    parser.add_argument("--no-append", action="store_true", help="Sustituir histórico en lugar de fusionar")
    args = parser.parse_args()

    if not args.year and not args.zip:
        parser.error("Indica --year o --zip")

    total = 0
    try:
        if args.zip:
            nuevas, meta = historico_placsp.import_from_zip(
                Path(args.zip), max_files=args.max_files, append=not args.no_append
            )
            total += nuevas
            print(f"Importadas {nuevas} filas desde {args.zip}. Total histórico: {meta.get('filas')}")
        for year in args.year or []:
            destino = historico_placsp.CACHE_DIR / f"licitaciones_{year}.zip"
            print(f"Descargando {year}…")
            historico_placsp.download_year_zip(year, destino)
            nuevas, meta = historico_placsp.import_from_zip(
                destino, max_files=args.max_files, append=not args.no_append
            )
            total += nuevas
            print(f"Año {year}: +{nuevas} filas. Total histórico: {meta.get('filas')}")
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1

    print(f"Listo. Filas importadas en esta ejecución: {total}")
    print(f"Parquet: {historico_placsp._cache_path()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
