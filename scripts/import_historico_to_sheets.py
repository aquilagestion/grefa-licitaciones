#!/usr/bin/env python3
"""Importa histórico PLACSP (ZIPs) a pestañas Historico_YYYY de Google Sheets.

Solo vuelca licitaciones Alta/Media según scoring GREFA (incluye NIF órgano/adjudicatario).

Ejemplos:
  python scripts/import_historico_to_sheets.py --from-year 2021 --to-year 2026
  python scripts/import_historico_to_sheets.py --year 2024 --replace
  python scripts/import_historico_to_sheets.py --year 2025 --skip-download
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from config.cpv_catalog import active_cpvs, default_cpv_catalog  # noqa: E402
from config.default_criteria import flatten_keywords  # noqa: E402
from config.keyword_catalog import active_keywords_grouped, default_term_catalog  # noqa: E402
from modules import grefa_filter, historico_placsp, sheets_catalog, sheets_historico, sheets_store  # noqa: E402


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
            print(f"Aviso: criterios por defecto ({exc})")
    catalogo_cpv = default_cpv_catalog()
    catalogo_terminos = default_term_catalog()
    return (
        list(active_cpvs(catalogo_cpv).keys()),
        flatten_keywords(active_keywords_grouped(catalogo_terminos)),
        catalogo_terminos,
    )


def _procesar_zip(
    zip_path: Path,
    *,
    year: int | None,
    cpvs: list[str],
    keywords: list[str],
    conceptos: list[dict],
    claves: set[str],
    hoja_id: str,
    etiqueta: str,
    max_files: int | None,
    replace: bool,
) -> tuple[int, set[str], int, int]:
    with tempfile.TemporaryDirectory(prefix="grefa_placsp_sheet_") as tmp:
        with zipfile.ZipFile(zip_path) as archivo:
            archivo.extractall(tmp)
        df = historico_placsp.import_from_directory(Path(tmp), max_files=max_files)

    if df.empty:
        return 0, claves, 0, 0

    total_parseadas = len(df)
    conceptos_activos = [t for t in conceptos if t.get("activo")]
    puntuadas = grefa_filter.score_licitaciones(df, cpvs, keywords, conceptos=conceptos_activos)
    relevantes = int((puntuadas["categoria"].isin(["Alta", "Media"])).sum())

    añadidas, claves = sheets_historico.append_historico_bulk(
        puntuadas,
        hoja_id=hoja_id,
        claves_existentes=claves,
        etiqueta_snapshot=etiqueta,
        default_year=year,
        replace_year=bool(replace and year is not None),
    )
    return añadidas, claves, total_parseadas, relevantes


def main() -> int:
    parser = argparse.ArgumentParser(description="Importar histórico PLACSP a Historico_YYYY")
    parser.add_argument("--from-year", type=int, default=2021)
    parser.add_argument("--to-year", type=int, default=2026)
    parser.add_argument("--year", type=int, action="append")
    parser.add_argument("--zip", type=str)
    parser.add_argument("--max-files", type=int, default=None)
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Sustituir Historico_YYYY completo (incluye NIF adjudicatario)",
    )
    args = parser.parse_args()

    _bootstrap_env()
    if not sheets_store.is_configured():
        print("ERROR: configure GREFA_SPREADSHEET_ID y credenciales.")
        return 1

    hoja_id = sheets_store.spreadsheet_id() or ""
    print(f"Hoja: {sheets_store.spreadsheet_url(hoja_id)}")

    cpvs, keywords, conceptos = _cargar_criterios()
    print(f"Criterios: {len(cpvs)} CPV, {len(keywords)} palabras clave")

    claves: set[str] = set() if args.replace else sheets_historico.load_claves_historico(hoja_id)
    print(f"Claves ya en histórico: {len(claves)}")

    total_añadidas = 0
    if args.zip:
        zip_path = Path(args.zip).expanduser().resolve()
        if not zip_path.is_file():
            print(f"ERROR: no existe {zip_path}")
            return 1
        year = None
        for token in zip_path.stem.split("_"):
            if token.isdigit() and len(token) == 4:
                year = int(token)
        añadidas, claves, parseadas, relevantes = _procesar_zip(
            zip_path,
            year=year,
            cpvs=cpvs,
            keywords=keywords,
            conceptos=conceptos,
            claves=claves,
            hoja_id=hoja_id,
            etiqueta=f"Importación PLACSP ({zip_path.stem})",
            max_files=args.max_files,
            replace=args.replace,
        )
        print(f"Parseadas {parseadas} · Alta/Media {relevantes} · Escritas {añadidas}")
        total_añadidas += añadidas
    else:
        años = sorted(set(args.year or range(args.from_year, args.to_year + 1)))
        for year in años:
            destino = historico_placsp.CACHE_DIR / f"licitaciones_{year}.zip"
            if destino.is_file() and args.skip_download:
                print(f"Año {year}: ZIP en caché")
            else:
                print(f"Año {year}: descargando…")
                try:
                    historico_placsp.download_year_zip(year, destino)
                except Exception as exc:
                    print(f"  ERROR descarga: {exc}")
                    continue
            print(f"Año {year}: procesando → Historico_{year}…")
            try:
                añadidas, claves, parseadas, relevantes = _procesar_zip(
                    destino,
                    year=year,
                    cpvs=cpvs,
                    keywords=keywords,
                    conceptos=conceptos,
                    claves=claves,
                    hoja_id=hoja_id,
                    etiqueta=f"Importación PLACSP {year}",
                    max_files=args.max_files,
                    replace=args.replace,
                )
            except Exception as exc:
                print(f"  ERROR: {exc}")
                continue
            print(f"  Parseadas {parseadas} · Alta/Media {relevantes} · Escritas {añadidas}")
            total_añadidas += añadidas

    print(f"\nListo. Filas escritas: {total_añadidas}")
    print(f"Años en hoja: {sheets_historico.list_historico_years(hoja_id)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
