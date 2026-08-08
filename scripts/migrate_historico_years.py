#!/usr/bin/env python3
"""Migra la pestaña legado Historico → Historico_YYYY e importa NIF adjudicatario.

Ejemplos:
  python scripts/migrate_historico_years.py
  python scripts/migrate_historico_years.py --reimport --from-year 2021 --to-year 2026
  python scripts/migrate_historico_years.py --reimport --year 2024 --skip-download
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd

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
    hoja_id: str | None,
    skip_download: bool,
    max_files: int | None,
) -> int:
    destino = historico_placsp.CACHE_DIR / f"licitaciones_{year}.zip"
    if not (destino.is_file() and skip_download):
        print(f"  Descargando ZIP {year}…", flush=True)
        historico_placsp.download_year_zip(year, destino)
    else:
        print(f"  Usando ZIP en caché ({destino.name})", flush=True)

    print(f"  Parseando+scoring por lotes (solo Alta/Media en memoria)…", flush=True)
    puntuadas = historico_placsp.import_score_zip_alta_media(
        destino,
        cpvs=cpvs,
        keywords=keywords,
        conceptos=conceptos,
        max_files=max_files,
    )

    if puntuadas.empty:
        print("  Sin datos Alta/Media parseables", flush=True)
        return 0

    if "nif_adjudicatario" in puntuadas.columns:
        con_adj = int((puntuadas["nif_adjudicatario"].astype(str).str.strip() != "").sum())
    else:
        con_adj = 0
    relevantes = len(puntuadas)
    print(f"  Alta/Media: {relevantes:,} (con NIF adjudicatario: {con_adj:,})", flush=True)

    # Parquet local (consultas sin cuota) + hoja Sheets
    try:
        local = historico_local.normalize_for_store(
            puntuadas,
            fuente=f"zip_{year}",
            default_year=year,
        )
        # Snapshot por año (por si falla el merge global)
        snap = historico_local.DATA_DIR / f"historico_grefa_{year}.parquet"
        historico_local.DATA_DIR.mkdir(parents=True, exist_ok=True)
        local_snap = local.copy()
        local_snap["relevancia"] = pd.to_numeric(local_snap.get("relevancia"), errors="coerce")
        for col in local_snap.select_dtypes(include=["object"]).columns:
            local_snap[col] = local_snap[col].map(
                lambda v: ""
                if v is None or (isinstance(v, float) and pd.isna(v))
                else (
                    ", ".join(str(x) for x in v)
                    if isinstance(v, (list, tuple))
                    else str(v)
                )
            )
        local_snap.to_parquet(snap, index=False)
        print(f"  Snapshot: {snap.name} ({len(local_snap):,} filas)", flush=True)

        if historico_local.is_available():
            previo = historico_local.load()
            if not previo.empty and "año" in previo.columns:
                previo = previo[previo["año"].fillna(0).astype(int) != int(year)]
            combinado = (
                local
                if previo.empty
                else pd.concat([previo, local], ignore_index=True, sort=False)
            )
        else:
            combinado = local
        if "expediente" in combinado.columns:
            subset = (
                ["expediente", "url"] if "url" in combinado.columns else ["expediente"]
            )
            combinado = combinado.drop_duplicates(subset=subset, keep="last")
        historico_local.save(
            combinado,
            meta={"origen": "reimport_zip", "año_actualizado": year},
        )
        print(f"  Parquet local actualizado ({historico_local.resumen()})", flush=True)
    except Exception as exc:
        print(f"  Aviso Parquet local: {exc}", flush=True)

    if hoja_id is None:
        print("  Omitido Sheets (--parquet-only).", flush=True)
        return relevantes

    print(f"  Escribiendo Historico_{year} en Sheets…", flush=True)
    import time

    ultimo: Exception | None = None
    for intento in range(6):
        try:
            sheets_store.reset_cache()
            sheets_historico.clear_worksheet_list_cache()
            escritas = sheets_historico.replace_year_historico(
                puntuadas,
                year,
                hoja_id=hoja_id,
                etiqueta_snapshot=f"Importación PLACSP {year}",
            )
            print(f"  Historico_{year}: {escritas} filas escritas", flush=True)
            return escritas
        except Exception as exc:
            ultimo = exc
            texto = str(exc).lower()
            if "429" in texto or "quota" in texto:
                espera = min(30 * (intento + 1), 120)
                print(f"  Cuota Sheets 429 · reintento en {espera}s…", flush=True)
                time.sleep(espera)
                continue
            break
    print(f"  ERROR escribiendo Sheets: {ultimo}", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrar histórico a pestañas por año")
    parser.add_argument("--reimport", action="store_true", help="Reimportar ZIPs a Historico_YYYY")
    parser.add_argument("--from-year", type=int, default=2021)
    parser.add_argument("--to-year", type=int, default=2026)
    parser.add_argument("--year", type=int, action="append")
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--max-files", type=int, default=None)
    parser.add_argument("--skip-migrate", action="store_true", help="No copiar pestaña legado")
    parser.add_argument(
        "--parquet-only",
        action="store_true",
        help="Solo actualizar Parquet local (0 lecturas/escrituras Sheets)",
    )
    args = parser.parse_args()

    _bootstrap_env()
    parquet_only = bool(args.parquet_only)
    if not parquet_only and not sheets_store.is_configured():
        print("ERROR: Sheets no configurado (o usa --parquet-only)")
        return 1

    hoja_id = None if parquet_only else (sheets_store.spreadsheet_id() or "")
    if parquet_only:
        print("Modo Parquet local (sin Sheets)", flush=True)
    else:
        print(f"Hoja: {sheets_store.spreadsheet_url(hoja_id)}", flush=True)

    if not parquet_only and not args.skip_migrate:
        print("Migrando pestana legado Historico -> Historico_YYYY...", flush=True)
        migrado = sheets_historico.migrate_legacy_to_year_sheets(hoja_id)
        if migrado:
            for year, n in sorted(migrado.items()):
                print(f"  Historico_{year}: +{n} filas migradas", flush=True)
        else:
            print("  Nada que migrar (vacío o ya migrado).", flush=True)

    if args.reimport:
        if parquet_only:
            catalogo_cpv = default_cpv_catalog()
            catalogo_terminos = default_term_catalog()
            cpvs = list(active_cpvs(catalogo_cpv).keys())
            keywords = flatten_keywords(active_keywords_grouped(catalogo_terminos))
            conceptos = catalogo_terminos
            print(f"Criterios locales: {len(cpvs)} CPV", flush=True)
        else:
            try:
                cpvs, keywords, conceptos = _cargar_criterios()
            except Exception as exc:
                print(f"Aviso criterios Sheets ({exc}); uso catálogo local", flush=True)
                catalogo_cpv = default_cpv_catalog()
                catalogo_terminos = default_term_catalog()
                cpvs = list(active_cpvs(catalogo_cpv).keys())
                keywords = flatten_keywords(active_keywords_grouped(catalogo_terminos))
                conceptos = catalogo_terminos
        years = sorted(set(args.year or range(args.from_year, args.to_year + 1)))
        print(f"Reimportando años {years}…", flush=True)
        total = 0
        for year in years:
            print(f"Año {year}:", flush=True)
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
                print(f"  ERROR: {exc}", flush=True)
        print(f"Total filas escritas en reimport: {total}", flush=True)

    print("Listo.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
