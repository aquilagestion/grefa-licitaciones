#!/usr/bin/env python3
"""Migra la pestaña legado Historico → Historico_YYYY e importa NIF adjudicatario.

Ejemplos:
  python scripts/migrate_historico_years.py
  python scripts/migrate_historico_years.py --reimport --from-year 2021 --to-year 2025
  python scripts/migrate_historico_years.py --reimport --year 2024 --skip-download
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


def _reimport_year(
    year: int,
    *,
    cpvs: list[str],
    keywords: list[str],
    conceptos: list[dict],
    hoja_id: str,
    skip_download: bool,
    max_files: int | None,
) -> int:
    destino = historico_placsp.CACHE_DIR / f"licitaciones_{year}.zip"
    if not (destino.is_file() and skip_download):
        print(f"  Descargando ZIP {year}…")
        historico_placsp.download_year_zip(year, destino)
    else:
        print(f"  Usando ZIP en caché ({destino.name})")

    with tempfile.TemporaryDirectory(prefix="grefa_mig_") as tmp:
        with zipfile.ZipFile(destino) as archivo:
            archivo.extractall(tmp)
        df = historico_placsp.import_from_directory(Path(tmp), max_files=max_files)

    if df.empty:
        print("  Sin datos parseables")
        return 0

    conceptos_activos = [t for t in conceptos if t.get("activo")]
    puntuadas = grefa_filter.score_licitaciones(df, cpvs, keywords, conceptos=conceptos_activos)
    if "nif_adjudicatario" in puntuadas.columns:
        mask = puntuadas["categoria"].isin(["Alta", "Media"]) & (
            puntuadas["nif_adjudicatario"].astype(str).str.strip() != ""
        )
        con_adj = int(mask.sum())
    else:
        con_adj = 0

    escritas = sheets_historico.replace_year_historico(
        puntuadas,
        year,
        hoja_id=hoja_id,
        etiqueta_snapshot=f"Importación PLACSP {year}",
    )
    print(f"  Historico_{year}: {escritas} filas (con NIF adjudicatario: {con_adj})")
    return escritas


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrar histórico a pestañas por año")
    parser.add_argument("--reimport", action="store_true", help="Reimportar ZIPs a Historico_YYYY")
    parser.add_argument("--from-year", type=int, default=2021)
    parser.add_argument("--to-year", type=int, default=2025)
    parser.add_argument("--year", type=int, action="append")
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--max-files", type=int, default=None)
    parser.add_argument("--skip-migrate", action="store_true", help="No copiar pestaña legado")
    args = parser.parse_args()

    _bootstrap_env()
    if not sheets_store.is_configured():
        print("ERROR: Sheets no configurado")
        return 1

    hoja_id = sheets_store.spreadsheet_id() or ""
    print(f"Hoja: {sheets_store.spreadsheet_url(hoja_id)}")

    if not args.skip_migrate:
        print("Migrando pestana legado Historico -> Historico_YYYY...")
        migrado = sheets_historico.migrate_legacy_to_year_sheets(hoja_id)
        if migrado:
            for year, n in sorted(migrado.items()):
                print(f"  Historico_{year}: +{n} filas migradas")
        else:
            print("  Nada que migrar (vacío o ya migrado).")

    años = sheets_historico.list_historico_years(hoja_id)
    print(f"Pestañas año disponibles: {años or 'ninguna'}")

    if args.reimport:
        cpvs, keywords, conceptos = _cargar_criterios()
        years = sorted(set(args.year or range(args.from_year, args.to_year + 1)))
        print(f"Reimportando años {years} (sustituye cada Historico_YYYY)…")
        total = 0
        for year in years:
            print(f"Año {year}:")
            try:
                total += _reimport_year(
                    year,
                    cpvs=cpvs,
                    keywords=keywords,
                    conceptos=conceptos,
                    hoja_id=hoja_id,
                    skip_download=args.skip_download,
                    max_files=args.max_files,
                )
            except Exception as exc:
                print(f"  ERROR: {exc}")
        print(f"Total filas escritas en reimport: {total}")

    print("Listo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
