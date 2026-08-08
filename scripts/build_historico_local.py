#!/usr/bin/env python3
"""Construye data/historico_grefa.parquet (consultas locales sin cuota Sheets).

Desde ZIPs PLACSP (recomendado, 0 lecturas Sheets):
  python -u scripts/build_historico_local.py --from-year 2021 --to-year 2026 --skip-download

Desde pestañas Historico_YYYY (1 lectura por año, una sola vez):
  python -u scripts/build_historico_local.py --from-sheets --from-year 2021 --to-year 2026
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

from config.cpv_catalog import active_cpvs, default_cpv_catalog  # noqa: E402
from config.default_criteria import flatten_keywords  # noqa: E402
from config.keyword_catalog import active_keywords_grouped, default_term_catalog  # noqa: E402
from modules import (  # noqa: E402
    grefa_filter,
    historico_local,
    historico_placsp,
    sheets_catalog,
    sheets_historico,
    sheets_store,
)


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


def _cargar_criterios() -> tuple[list[str], list[str], list[dict]]:
    if sheets_store.is_configured():
        try:
            cpvs, keywords, _c, catalogo_terminos = sheets_catalog.load_selection()
            return list(cpvs.keys()), flatten_keywords(keywords), catalogo_terminos
        except sheets_store.SheetsError as exc:
            print(f"Aviso: criterios por defecto ({exc})", flush=True)
    catalogo_cpv = default_cpv_catalog()
    catalogo_terminos = default_term_catalog()
    return (
        list(active_cpvs(catalogo_cpv).keys()),
        flatten_keywords(active_keywords_grouped(catalogo_terminos)),
        catalogo_terminos,
    )


def _desde_zip(
    year: int,
    *,
    cpvs: list[str],
    keywords: list[str],
    conceptos: list[dict],
    skip_download: bool,
    max_files: int | None,
) -> pd.DataFrame:
    import pandas as pd

    destino = historico_placsp.CACHE_DIR / f"licitaciones_{year}.zip"
    if not (destino.is_file() and skip_download):
        print(f"  Descargando ZIP {year}…", flush=True)
        historico_placsp.download_year_zip(year, destino)
    else:
        print(f"  ZIP en caché: {destino.name}", flush=True)

    df = historico_placsp.import_from_zip_bytes(destino, max_files=max_files)

    if df.empty:
        return df

    conceptos_activos = [t for t in conceptos if t.get("activo")]
    puntuadas = grefa_filter.score_licitaciones(
        df, cpvs, keywords, conceptos=conceptos_activos
    )
    relevantes = puntuadas[puntuadas["categoria"].isin(["Alta", "Media"])].copy()
    return historico_local.normalize_for_store(
        relevantes, fuente=f"zip_{year}", default_year=year
    )


def _desde_sheets(years: list[int]) -> "pd.DataFrame":
    import pandas as pd

    partes = []
    for year in years:
        print(f"  Leyendo Historico_{year}…", flush=True)
        try:
            df = sheets_historico.load_historico_dataframe(
                years=[year], include_legacy=False
            )
        except Exception as exc:
            print(f"  ERROR {year}: {exc}", flush=True)
            continue
        if df.empty:
            print(f"  Historico_{year}: vacío", flush=True)
            continue
        partes.append(
            historico_local.normalize_for_store(df, fuente=f"sheets_{year}", default_year=year)
        )
        print(f"  Historico_{year}: {len(df)} filas", flush=True)
    if not partes:
        return pd.DataFrame()
    return pd.concat(partes, ignore_index=True, sort=False)


def main() -> int:
    import pandas as pd

    parser = argparse.ArgumentParser(description="Construir histórico local Parquet")
    parser.add_argument("--from-year", type=int, default=2021)
    parser.add_argument("--to-year", type=int, default=2026)
    parser.add_argument("--year", type=int, action="append")
    parser.add_argument("--from-sheets", action="store_true")
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--max-files", type=int, default=None)
    parser.add_argument(
        "--append",
        action="store_true",
        help="Fusionar con el Parquet existente en lugar de sustituirlo",
    )
    args = parser.parse_args()

    _bootstrap_env()
    años = sorted(set(args.year or range(args.from_year, args.to_year + 1)))
    print(f"Destino: {historico_local.parquet_path()}", flush=True)
    print(f"Años: {años}", flush=True)

    if args.from_sheets:
        if not sheets_store.is_configured():
            print("ERROR: Sheets no configurado", flush=True)
            return 1
        combinado = _desde_sheets(años)
    else:
        cpvs, keywords, conceptos = _cargar_criterios()
        print(f"Criterios: {len(cpvs)} CPV, {len(keywords)} términos", flush=True)
        partes = []
        for year in años:
            print(f"Año {year}: procesando…", flush=True)
            try:
                df = _desde_zip(
                    year,
                    cpvs=cpvs,
                    keywords=keywords,
                    conceptos=conceptos,
                    skip_download=args.skip_download,
                    max_files=args.max_files,
                )
            except Exception as exc:
                print(f"  ERROR: {exc}", flush=True)
                continue
            print(
                f"  Alta/Media: {len(df)} · NIF adj: "
                f"{int((df['nif_adjudicatario'].astype(str).str.strip()!='').sum()) if not df.empty and 'nif_adjudicatario' in df.columns else 0}",
                flush=True,
            )
            if not df.empty:
                partes.append(df)
        combinado = pd.concat(partes, ignore_index=True, sort=False) if partes else pd.DataFrame()

    if combinado.empty:
        print("ERROR: no se generaron filas", flush=True)
        return 1

    if args.append and historico_local.is_available():
        previo = historico_local.load()
        combinado = pd.concat([previo, combinado], ignore_index=True, sort=False)

    if "expediente" in combinado.columns:
        subset = ["expediente", "url"] if "url" in combinado.columns else ["expediente"]
        combinado = combinado.drop_duplicates(subset=subset, keep="last")

    ruta = historico_local.save(
        combinado,
        meta={
            "origen": "sheets" if args.from_sheets else "zip_placsp",
            "años_solicitados": años,
        },
    )
    print(historico_local.resumen(), flush=True)
    print(f"Guardado: {ruta}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
