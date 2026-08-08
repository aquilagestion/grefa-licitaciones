#!/usr/bin/env python3
"""Rellena Adjudicatario / NIF adjudicatario en Historico_YYYY desde los ZIP PLACSP.

No reimporta el histórico: solo actualiza esas columnas (y NIF órgano vacío).

Ejemplos:
  python -u scripts/enrich_adjudicatarios_sheets.py --year 2026
  python -u scripts/enrich_adjudicatarios_sheets.py --from-year 2021 --to-year 2026
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from modules import historico_placsp, sheets_historico, sheets_store  # noqa: E402


def _bootstrap_env() -> None:
    secrets_path = BASE / ".streamlit" / "secrets.toml"
    if not secrets_path.is_file():
        return
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            return
    with secrets_path.open("rb") as fichero:
        datos = tomllib.load(fichero)
    if not os.environ.get("GREFA_SPREADSHEET_ID"):
        sid = datos.get("sheets", {}).get("spreadsheet_id")
        if sid:
            os.environ["GREFA_SPREADSHEET_ID"] = str(sid)
    if not os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON") and not os.environ.get(
        "GOOGLE_APPLICATION_CREDENTIALS"
    ):
        gcp = datos.get("gcp_service_account")
        if gcp:
            os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"] = json.dumps(gcp)


def main() -> int:
    parser = argparse.ArgumentParser(description="Enriquecer adjudicatarios en Sheets")
    parser.add_argument("--from-year", type=int, default=2021)
    parser.add_argument("--to-year", type=int, default=2026)
    parser.add_argument("--year", type=int, action="append")
    parser.add_argument("--max-files", type=int, default=None)
    args = parser.parse_args()

    _bootstrap_env()
    if not sheets_store.is_configured():
        print("ERROR: configure GREFA_SPREADSHEET_ID y credenciales.")
        return 1

    hoja_id = sheets_store.spreadsheet_id() or ""
    print(f"Hoja: {sheets_store.spreadsheet_url(hoja_id)}", flush=True)

    años = sorted(set(args.year or range(args.from_year, args.to_year + 1)))
    for year in años:
        zip_path = historico_placsp.CACHE_DIR / f"licitaciones_{year}.zip"
        if not zip_path.is_file():
            print(f"Año {year}: sin ZIP en caché ({zip_path.name})", flush=True)
            continue
        print(f"Año {year}: escaneando {zip_path.name}…", flush=True)
        lookup = historico_placsp.scan_adjudicatarios_from_zip(
            zip_path, max_files=args.max_files
        )
        con_nif = sum(1 for v in lookup.values() if v.get("nif_adjudicatario"))
        print(
            f"  Índice: {len(lookup):,} adjudicadas ({con_nif:,} con NIF)",
            flush=True,
        )
        stats = sheets_historico.enrich_adjudicatarios_year(
            year, lookup, hoja_id=hoja_id
        )
        print(
            f"  Historico_{year}: {stats['filas']} filas · "
            f"actualizadas {stats['actualizadas']} · "
            f"con nombre {stats['con_nombre']} · con NIF {stats['con_nif']}",
            flush=True,
        )
    print("Hecho.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
