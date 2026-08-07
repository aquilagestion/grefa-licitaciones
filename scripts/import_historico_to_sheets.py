#!/usr/bin/env python3
"""Importa histórico PLACSP (ZIPs oficiales) a la pestaña Historico de Google Sheets.

Solo vuelca licitaciones Alta/Media según el scoring GREFA (mismo criterio que la app).
El histórico completo de PLACSP no cabe en Sheets; esta importación es la versión útil.

Ejemplos:
  python scripts/import_historico_to_sheets.py --from-year 2021
  python scripts/import_historico_to_sheets.py --year 2024 --year 2025
  python scripts/import_historico_to_sheets.py --zip C:\\descargas\\licitaciones_2023.zip
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
    """Carga spreadsheet_id y credenciales desde .streamlit/secrets.toml si faltan."""
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
            cpvs, keywords, _catalogo_cpv, catalogo_terminos = sheets_catalog.load_selection()
            return list(cpvs.keys()), flatten_keywords(keywords), catalogo_terminos
        except sheets_store.SheetsError as exc:
            print(f"Aviso: no se leyeron criterios de Sheets ({exc}); valores por defecto.")

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
    cpvs: list[str],
    keywords: list[str],
    conceptos: list[dict],
    claves: set[str],
    hoja_id: str,
    etiqueta: str,
    max_files: int | None,
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
    )
    return añadidas, claves, total_parseadas, relevantes


def main() -> int:
    parser = argparse.ArgumentParser(description="Importar histórico PLACSP a Google Sheets")
    parser.add_argument("--from-year", type=int, default=2021, help="Primer año (con --to-year)")
    parser.add_argument("--to-year", type=int, default=2025, help="Último año inclusive")
    parser.add_argument("--year", type=int, action="append", help="Año concreto (repetible)")
    parser.add_argument("--zip", type=str, help="Ruta a un ZIP ya descargado")
    parser.add_argument("--max-files", type=int, default=None, help="Máx. ficheros .atom por ZIP")
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Usar ZIP en data/cache si ya existe",
    )
    args = parser.parse_args()

    _bootstrap_env()

    if not sheets_store.is_configured():
        print("ERROR: configure GREFA_SPREADSHEET_ID y credenciales de servicio.")
        return 1

    hoja_id = sheets_store.spreadsheet_id()
    print(f"Hoja: {sheets_store.spreadsheet_url(hoja_id)}")

    try:
        sheets_historico._worksheet_historico(hoja_id)
    except sheets_store.SheetsError as exc:
        print(f"ERROR: {exc}")
        return 1

    cpvs, keywords, conceptos = _cargar_criterios()
    print(f"Criterios: {len(cpvs)} CPV, {len(keywords)} palabras clave")

    claves = sheets_historico.load_claves_historico(hoja_id)
    print(f"Claves ya en Histórico: {len(claves)}")

    años: list[int] = sorted(set(args.year or range(args.from_year, args.to_year + 1)))
    total_añadidas = 0

    if args.zip:
        zip_path = Path(args.zip).expanduser().resolve()
        if not zip_path.is_file():
            print(f"ERROR: no existe {zip_path}")
            return 1
        etiqueta = f"Importación PLACSP ({zip_path.stem})"
        print(f"Procesando {zip_path.name}…")
        añadidas, claves, parseadas, relevantes = _procesar_zip(
            zip_path,
            cpvs=cpvs,
            keywords=keywords,
            conceptos=conceptos,
            claves=claves,
            hoja_id=hoja_id or "",
            etiqueta=etiqueta,
            max_files=args.max_files,
        )
        print(
            f"  Parseadas: {parseadas} · Alta/Media: {relevantes} · "
            f"Nuevas en Sheet: {añadidas}"
        )
        total_añadidas += añadidas
    else:
        for year in años:
            destino = historico_placsp.CACHE_DIR / f"licitaciones_{year}.zip"
            if destino.is_file() and args.skip_download:
                print(f"Año {year}: usando ZIP en caché ({destino.name})")
            else:
                print(f"Año {year}: descargando ZIP oficial…")
                try:
                    historico_placsp.download_year_zip(year, destino)
                except Exception as exc:
                    print(f"  ERROR descarga {year}: {exc}")
                    continue

            etiqueta = f"Importación PLACSP {year}"
            print(f"Año {year}: procesando…")
            try:
                añadidas, claves, parseadas, relevantes = _procesar_zip(
                    destino,
                    cpvs=cpvs,
                    keywords=keywords,
                    conceptos=conceptos,
                    claves=claves,
                    hoja_id=hoja_id or "",
                    etiqueta=etiqueta,
                    max_files=args.max_files,
                )
            except Exception as exc:
                print(f"  ERROR procesando {year}: {exc}")
                continue

            print(
                f"  Parseadas: {parseadas} · Alta/Media: {relevantes} · "
                f"Nuevas en Sheet: {añadidas}"
            )
            total_añadidas += añadidas

    print(f"\nListo. Filas nuevas en Histórico: {total_añadidas}")
    print(f"Total claves en Histórico: {len(claves)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
