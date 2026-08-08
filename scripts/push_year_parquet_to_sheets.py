#!/usr/bin/env python3
"""Escribe snapshots data/historico_grefa_YYYY.parquet en Historico_YYYY de Sheets."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from modules import historico_local, sheets_historico, sheets_store  # noqa: E402


def _bootstrap() -> None:
    secrets = BASE / ".streamlit" / "secrets.toml"
    if not secrets.is_file():
        return
    try:
        import tomllib
    except ImportError:
        return
    with secrets.open("rb") as f:
        datos = tomllib.load(f)
    if not os.environ.get("GREFA_SPREADSHEET_ID"):
        sid = datos.get("sheets", {}).get("spreadsheet_id")
        if sid:
            os.environ["GREFA_SPREADSHEET_ID"] = str(sid)
    if not os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON"):
        gcp = datos.get("gcp_service_account")
        if gcp:
            os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"] = json.dumps(gcp)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, action="append", required=True)
    args = parser.parse_args()
    _bootstrap()
    if not sheets_store.is_configured():
        print("ERROR: Sheets no configurado")
        return 1

    for year in sorted(set(args.year)):
        snap = historico_local.DATA_DIR / f"historico_grefa_{year}.parquet"
        if not snap.is_file():
            print(f"Sin snapshot {snap.name}", flush=True)
            continue
        df = pd.read_parquet(snap)
        print(f"Historico_{year}: {len(df):,} filas desde {snap.name}", flush=True)
        if "categoria" not in df.columns:
            df["categoria"] = "Media"
        for intento in range(8):
            try:
                sheets_store.reset_cache()
                sheets_historico.clear_worksheet_list_cache()
                n = sheets_historico.replace_year_historico(
                    df,
                    year,
                    etiqueta_snapshot=f"Importación PLACSP {year}",
                )
                print(f"  Escrito: {n} filas", flush=True)
                break
            except Exception as exc:
                texto = str(exc).lower()
                if "429" in texto or "quota" in texto:
                    espera = min(30 * (intento + 1), 120)
                    print(f"  429 · espera {espera}s…", flush=True)
                    time.sleep(espera)
                    continue
                print(f"  ERROR: {exc}", flush=True)
                break
        time.sleep(5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
