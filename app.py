"""GREFA · Monitor de licitaciones públicas (PLACSP).

Interfaz Streamlit para descargar el feed ATOM de la Plataforma de Contratación
del Sector Público, puntuar cada expediente con el Índice de Relevancia GREFA y
gestionar los criterios de búsqueda (CPV y palabras clave) en caliente.

Ejecución:  streamlit run app.py
"""

from __future__ import annotations

import importlib
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from config.cpv_catalog import active_cpvs, default_cpv_catalog  # noqa: E402
from config.default_criteria import (  # noqa: E402
    CUSTOM_KEYWORD_CATEGORY,
    ESTADOS_ABIERTOS_DEFAULT,
    HIGH_RELEVANCE_THRESHOLD,
    MEDIUM_RELEVANCE_THRESHOLD,
    RELEVANCE_LEVELS,
    flatten_keywords,
)
from config.keyword_catalog import (  # noqa: E402
    active_keywords_grouped,
    default_term_catalog,
)
from modules import (  # noqa: E402
    auth,
    daily_sync,
    drive_docs,
    email_alert,
    grefa_filter,
    google_chat,
    historico_placsp,
    pdf_summary,
    pliegos_placsp,
    sheets_catalog,
    sheets_historico,
    sheets_store,
)
from modules.admin_ambito import NIVEL_AUTONOMICO, NIVEL_LOCAL, NIVEL_NACIONAL, NIVELES_ADMIN  # noqa: E402
from modules.translator import complete_from_any, complete_term_translations  # noqa: E402
from modules.exporter import (  # noqa: E402
    timestamped_filename,
    to_csv_bytes,
    to_excel_bytes,
)
from modules.ingestion import (  # noqa: E402
    COLUMN_LABELS,
    PRIMARY_FEED_URL,
    IngestionError,
    empty_dataframe,
    fetch_placsp_licitaciones,
    parse_atom_bytes,
)

st.set_page_config(
    page_title="GREFA · Licitaciones PLACSP",
    page_icon="🦅",
    layout="wide",
    initial_sidebar_state="expanded",
)

CUSTOM_CSS = """
<style>
    .bloque-titulo { padding: 0; }
    .cabecera-compacta {
        display: flex; flex-wrap: wrap; align-items: baseline; gap: 0.35rem 0.75rem;
        margin-bottom: 0.25rem; line-height: 1.2;
    }
    .cabecera-titulo { font-size: 1.15rem; font-weight: 700; color: #10241a; }
    .cabecera-sub { font-size: 0.78rem; color: #5b6b62; }
    .cabecera-badge {
        font-size: 0.72rem; font-weight: 600; color: #1B873F;
        background: #eef7f0; border-radius: 999px; padding: 0.1rem 0.45rem;
    }
    .tarjeta {
        border: 1px solid #e2e6e3;
        border-left: 6px solid var(--color-acento, #6B7280);
        border-radius: 10px;
        padding: 0.9rem 1.1rem;
        margin-bottom: 0.85rem;
        background: #ffffff;
        box-shadow: 0 1px 2px rgba(16, 24, 40, 0.05);
    }
    .tarjeta h4 { margin: 0 0 0.45rem 0; font-size: 1.02rem; line-height: 1.35; color: #10241a; }
    .badge {
        display: inline-block;
        padding: 0.15rem 0.6rem;
        border-radius: 999px;
        font-size: 0.74rem;
        font-weight: 700;
        color: #ffffff;
        letter-spacing: 0.02em;
    }
    .meta { color: #4b5563; font-size: 0.86rem; margin: 0.15rem 0; }
    .meta strong { color: #1f2937; }
    .chip {
        display: inline-block; background: #eef3ef; color: #33513f;
        border-radius: 6px; padding: 0.08rem 0.45rem; margin: 0.1rem 0.25rem 0.1rem 0;
        font-size: 0.75rem; font-family: ui-monospace, monospace;
    }
    /* Panel de control superior: máx. 30 % del alto de pantalla */
    .zona-control-flag { display: none; }
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.zona-control-flag) {
        max-height: 30vh;
        overflow-y: auto;
        overflow-x: hidden;
        margin-bottom: 0.25rem;
        padding-top: 0.35rem;
        padding-bottom: 0.25rem;
    }
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.zona-control-flag) [data-testid="stVerticalBlock"] {
        gap: 0.25rem;
    }
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.zona-control-flag) div[data-testid="stMetricValue"] {
        font-size: 1.05rem;
    }
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.zona-control-flag) div[data-testid="stMetricLabel"] {
        font-size: 0.68rem;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.zona-control-flag) div[data-testid="stMetric"] {
        padding: 0.15rem 0;
    }
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.zona-control-flag) [data-testid="stTextInput"],
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.zona-control-flag) [data-testid="stDateInput"] {
        margin-bottom: 0;
    }
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.zona-control-flag) button[kind="secondary"] {
        min-height: 1.85rem !important;
        padding: 0.15rem 0.45rem !important;
        font-size: 0.78rem !important;
    }
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.zona-control-flag) [data-testid="stFormSubmitButton"] button {
        min-height: 1.85rem !important;
        font-size: 0.82rem !important;
    }
    .resumen-filtros { font-size: 0.72rem; color: #5b6b62; margin: 0.08rem 0; line-height: 1.2; }
    .grid-etiq {
        font-size: 0.68rem; font-weight: 700; color: #33513f;
        text-transform: uppercase; letter-spacing: 0.02em;
        line-height: 1.1rem; white-space: nowrap;
    }
    .grid-val {
        font-size: 0.78rem; font-weight: 600; color: #10241a;
        line-height: 1.1rem; text-align: right;
    }
    .grid-par {
        display: flex; align-items: center; gap: 0.12rem;
        line-height: 1.1rem; white-space: nowrap;
    }
    .grid-par .grid-etiq, .grid-par .grid-val {
        line-height: 1.1rem; text-align: left;
    }
    .grid-par .grid-val { font-size: 0.78rem; }
    .col-filtros-flag { display: none; }
    div[data-testid="stVerticalBlock"]:has(.col-filtros-flag) [data-testid="stHorizontalBlock"] {
        gap: 0.03rem !important;
        align-items: center;
    }
    div[data-testid="stVerticalBlock"]:has(.col-filtros-flag) [data-testid="column"]:first-child [data-testid="stMarkdown"] {
        padding-right: 0 !important;
        margin-right: 0 !important;
    }
    div[data-testid="stVerticalBlock"]:has(.col-filtros-flag) [data-testid="column"]:last-child [data-testid="element-container"] {
        padding-left: 0 !important;
        margin-left: 0 !important;
        max-width: 50% !important;
    }
    div[data-testid="stVerticalBlock"]:has(.col-filtros-flag) [data-testid="column"]:last-child button[kind="secondary"] {
        width: 100% !important;
        max-width: 100% !important;
    }
    div[data-testid="stVerticalBlock"]:has(.col-filtros-flag) .grid-etiq {
        padding-right: 0.08rem;
    }
    .panel-mockup-flag { display: none; }
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.panel-mockup-flag) {
        max-height: 32vh;
        overflow-y: auto;
        margin-bottom: 0.25rem;
        padding: 0.25rem 0.4rem 0.2rem 0.4rem;
    }
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.panel-mockup-flag) [data-testid="stVerticalBlock"] {
        gap: 0.06rem;
    }
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.panel-mockup-flag) [data-testid="stHorizontalBlock"] {
        gap: 0.05rem !important;
        align-items: center;
    }
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.panel-mockup-flag) [data-testid="column"] {
        padding-left: 0.08rem !important;
        padding-right: 0.08rem !important;
    }
    .col-stats-flag { display: none; }
    div[data-testid="stVerticalBlock"]:has(.col-stats-flag) [data-testid="stHorizontalBlock"] {
        gap: 0.04rem !important;
    }
    div[data-testid="stVerticalBlock"]:has(.col-stats-flag) .grid-par {
        gap: 0.08rem;
    }
    div[data-testid="stVerticalBlock"]:has(.col-stats-flag) .grid-etiq {
        font-size: 0.64rem;
    }
    div[data-testid="stVerticalBlock"]:has(.col-stats-flag) .grid-val {
        font-size: 0.74rem;
    }
    .fila-buscar-flag { display: none; }
    div[data-testid="stVerticalBlock"]:has(.fila-buscar-flag) [data-testid="stHorizontalBlock"] {
        gap: 0.25rem !important;
        align-items: center;
        justify-content: flex-end;
    }
    div[data-testid="stVerticalBlock"]:has(.fila-buscar-flag) [data-testid="column"]:last-child button {
        font-weight: 600;
    }
    .bloque-opp-flag { display: none; }
    .bloque-estandar-flag { display: none; }
    .bloque-libre-flag { display: none; }
    .bloque-seccion-titulo {
        font-size: 0.72rem; font-weight: 700; color: #33513f;
        text-transform: uppercase; letter-spacing: 0.04em;
        margin: 0.35rem 0 0.12rem 0; line-height: 1.2;
    }
    div[data-testid="stVerticalBlock"]:has(.bloque-opp-flag) .resumen-filtros,
    div[data-testid="stVerticalBlock"]:has(.bloque-estandar-flag) .resumen-filtros,
    div[data-testid="stVerticalBlock"]:has(.bloque-libre-flag) .resumen-filtros {
        margin: 0.1rem 0 0.06rem 0;
    }
    .opp-stats-spacer {
        display: block;
        height: 3.35rem;
    }
    @media (max-width: 900px) {
        .opp-stats-spacer { height: 0; }
    }
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.panel-mockup-flag) [data-testid="element-container"] {
        margin-top: 0.04rem !important;
        margin-bottom: 0.04rem !important;
        padding-top: 0.02rem !important;
        padding-bottom: 0.02rem !important;
    }
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.panel-mockup-flag) button[kind="secondary"] {
        min-height: 1.12rem !important;
        max-height: 1.35rem !important;
        padding: 0.02rem 0.28rem !important;
        font-size: 0.7rem !important;
        line-height: 1.1 !important;
        width: 100%;
    }
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.panel-mockup-flag) [data-testid="stTextInput"] input {
        min-height: 1.12rem !important;
        padding: 0.12rem 0.35rem !important;
        font-size: 0.78rem !important;
    }
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.panel-mockup-flag) [data-testid="stMultiSelect"] > div {
        min-height: 1.12rem !important;
    }
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.panel-mockup-flag) [data-testid="stSlider"] label,
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.panel-mockup-flag) .stRadio > label {
        display: none;
    }
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.panel-mockup-flag) [data-testid="stFormSubmitButton"] button {
        min-height: 1.12rem !important;
        font-size: 0.72rem !important;
        padding: 0.12rem 0.3rem !important;
    }
    .barra-criterios-flag { display: none; }
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.zona-control-flag) [data-testid="stHorizontalBlock"] {
        gap: 0.35rem;
        align-items: center;
    }
    div[data-testid="stPopoverBody"] {
        max-height: min(70vh, 520px);
        overflow-y: auto;
    }
    div[data-testid="stPopoverBody"] h3, div[data-testid="stPopoverBody"] h2 {
        font-size: 0.95rem;
        margin: 0 0 0.35rem 0;
    }
    .toolbar-oport-flag { display: none; }
    div[data-testid="stVerticalBlock"]:has(.toolbar-oport-flag) {
        margin-bottom: 0.35rem;
    }
    div[data-testid="stVerticalBlock"]:has(.toolbar-oport-flag) div[data-testid="stMetricValue"] {
        font-size: 0.95rem;
    }
    div[data-testid="stVerticalBlock"]:has(.toolbar-oport-flag) div[data-testid="stMetricLabel"] {
        font-size: 0.65rem;
    }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Estado de la sesión
# ---------------------------------------------------------------------------
def init_state() -> None:
    catalogo_cpv = default_cpv_catalog()
    catalogo_terminos = default_term_catalog()
    valores_iniciales = {
        "catalogo_cpv": catalogo_cpv,
        "catalogo_terminos": catalogo_terminos,
        "cpvs": active_cpvs(catalogo_cpv),
        "keywords": active_keywords_grouped(catalogo_terminos),
        "feed_url": PRIMARY_FEED_URL,
        "max_pages": 2,
        "max_entries": 500,
        "refresh_token": 0,
        "datos": None,
        "origen_datos": "",
        "ultima_actualizacion": None,
        "error_descarga": "",
        "sheets_sincronizado": False,
        "sheets_estado": "",
        "filtro_estados": list(ESTADOS_ABIERTOS_DEFAULT),
        "estados_aplicados": list(ESTADOS_ABIERTOS_DEFAULT),
        "busqueda_aplicada": "",
        "busqueda_borrador": "",
        "usar_fechas_aplicado": False,
        "fecha_campo_aplicado": "fecha_actualizacion",
        "fecha_desde_aplicada": None,
        "fecha_hasta_aplicada": None,
        "incluir_sin_fecha_aplicado": True,
        "cargando_datos": False,
        "filtro_usar_fechas": False,
        "filtro_fecha_campo": "fecha_actualizacion",
        "filtro_incluir_sin_fecha": True,
        "opp_min_relevancia": MEDIUM_RELEVANCE_THRESHOLD,
        "opp_min_relevancia_aplicado": MEDIUM_RELEVANCE_THRESHOLD,
        "opp_categorias_borrador": ["Alta", "Media"],
        "opp_categorias_aplicadas": ["Alta", "Media"],
        "opp_vista": "Tarjetas",
        "pdf_resumenes": {},
        "seguimiento_cache": {},
        "mis_licitaciones_cache": None,
        "pliego_expediente_sel": "",
        "buscador_filtros_aplicados": None,
        "hist_filtros_aplicados": None,
        "pliego_consulta_aplicada": "",
    }
    for clave, valor in valores_iniciales.items():
        st.session_state.setdefault(clave, valor)


def _sincronizar_activos_desde_catalogos() -> None:
    st.session_state["cpvs"] = active_cpvs(st.session_state["catalogo_cpv"])
    st.session_state["keywords"] = active_keywords_grouped(st.session_state["catalogo_terminos"])


init_state()


def _recargar_modulos_criticos() -> None:
    """Fuerza la recarga de módulos (Streamlit Cloud puede cachear código antiguo)."""
    for nombre in ("modules.grefa_filter", "modules.sheets_historico", "modules.admin_ambito"):
        try:
            modulo = importlib.import_module(nombre)
            modulo = importlib.reload(modulo)
            sys.modules[nombre] = modulo
            corto = nombre.rsplit(".", 1)[-1]
            globals()[corto] = modulo
        except Exception:
            continue


def aplicar_filtros_globales(
    df: pd.DataFrame,
    *,
    texto: str = "",
    fecha_campo: str = "fecha_actualizacion",
    fecha_desde=None,
    fecha_hasta=None,
    incluir_sin_fecha: bool = True,
) -> pd.DataFrame:
    """Búsqueda libre + fechas con fallbacks si falta alguna función en el módulo."""
    texto = str(texto or "").strip()
    usar_fechas = fecha_desde is not None or fecha_hasta is not None

    aplicar = getattr(grefa_filter, "apply_filtros_busqueda", None)
    if callable(aplicar):
        return aplicar(
            df,
            texto=texto,
            fecha_campo=fecha_campo,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            incluir_sin_fecha=incluir_sin_fecha,
        )

    resultado = df
    filtrar_texto = getattr(grefa_filter, "filter_by_texto_libre", None)
    if callable(filtrar_texto) and texto:
        resultado = filtrar_texto(resultado, texto)
    elif texto and hasattr(grefa_filter, "search_dataframe"):
        resultado = grefa_filter.search_dataframe(resultado, texto=texto)

    filtrar_fechas = getattr(grefa_filter, "filter_by_fechas", None)
    if callable(filtrar_fechas) and usar_fechas:
        resultado = filtrar_fechas(
            resultado,
            campo=fecha_campo,
            desde=fecha_desde,
            hasta=fecha_hasta,
            incluir_sin_fecha=incluir_sin_fecha,
        )
    elif usar_fechas and hasattr(grefa_filter, "search_dataframe"):
        try:
            resultado = grefa_filter.search_dataframe(
                resultado,
                fecha_campo=fecha_campo,
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
                incluir_sin_fecha=incluir_sin_fecha,
            )
        except TypeError:
            pass
    return resultado


# ---------------------------------------------------------------------------
# Carga de datos
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False, ttl=1800)
def cargar_feed(url: str, max_pages: int, max_entries: int, token: int) -> pd.DataFrame:
    """Descarga cacheada del feed. `token` permite forzar la recarga manual."""
    return fetch_placsp_licitaciones(
        feed_url=url or None, max_pages=max_pages, max_entries=max_entries
    )


def actualizar_datos() -> None:
    st.session_state["error_descarga"] = ""
    try:
        df = cargar_feed(
            st.session_state["feed_url"],
            int(st.session_state["max_pages"]),
            int(st.session_state["max_entries"]),
            int(st.session_state["refresh_token"]),
        )
        st.session_state["datos"] = df
        st.session_state["origen_datos"] = df.attrs.get("feed_url", st.session_state["feed_url"])
        st.session_state["ultima_actualizacion"] = datetime.now()
    except IngestionError as exc:
        st.session_state["error_descarga"] = str(exc)
    except Exception as exc:  # errores de red inesperados
        st.session_state["error_descarga"] = f"Error inesperado al descargar el feed: {exc}"


def cargar_datos_con_indicador() -> None:
    """Descarga con indicador breve (sin bloque de estado persistente)."""
    with st.spinner("⏳ Descargando licitaciones de la PLACSP…"):
        actualizar_datos()
    st.session_state["cargando_datos"] = False


# ---------------------------------------------------------------------------
# Criterios compartidos en Google Sheets
# ---------------------------------------------------------------------------
def cargar_criterios_de_sheets(inicial: bool = False) -> bool:
    """Trae los catálogos / criterios de la hoja compartida a la sesión."""
    if not sheets_store.is_configured():
        return False
    try:
        cpvs, keywords, catalogo_cpv, catalogo_terminos = sheets_catalog.load_selection()
    except sheets_store.SheetsError as exc:
        st.session_state["sheets_estado"] = f"⚠️ {exc}"
        return False
    except Exception as exc:
        st.session_state["sheets_estado"] = f"⚠️ {exc}"
        return False

    st.session_state["sheets_sincronizado"] = True
    if not catalogo_cpv and not catalogo_terminos and not cpvs and not keywords:
        if inicial:
            guardar_criterios_en_sheets(silencioso=True)
            st.session_state["sheets_estado"] = "Hoja inicializada con los catálogos por defecto."
        return False

    if catalogo_cpv:
        st.session_state["catalogo_cpv"] = catalogo_cpv
    if catalogo_terminos:
        st.session_state["catalogo_terminos"] = catalogo_terminos
    _sincronizar_activos_desde_catalogos()
    st.session_state["sheets_estado"] = (
        f"Catálogos cargados ({sum(1 for c in st.session_state['catalogo_cpv'] if c.get('activo'))} CPV activos, "
        f"{sum(1 for t in st.session_state['catalogo_terminos'] if t.get('activo'))} términos activos)."
    )
    return True


def guardar_criterios_en_sheets(silencioso: bool = False) -> bool:
    """Persiste la selección de catálogos en Google Sheets."""
    if not sheets_store.is_configured():
        return False
    try:
        sheets_catalog.save_cpv_catalog(st.session_state["catalogo_cpv"])
        sheets_catalog.save_term_catalog(st.session_state["catalogo_terminos"])
        sheets_catalog.sync_active_summary_sheets(
            st.session_state["catalogo_cpv"],
            st.session_state["catalogo_terminos"],
        )
    except sheets_store.SheetsError as exc:
        st.session_state["sheets_estado"] = f"⚠️ {exc}"
        if not silencioso:
            st.sidebar.error(str(exc))
        return False

    st.session_state["sheets_estado"] = (
        f"Selección guardada en Google Sheets a las {datetime.now():%H:%M}."
    )
    if not silencioso:
        st.toast("Selección guardada en Google Sheets", icon="✅")
    return True


# ---------------------------------------------------------------------------
# Utilidades de formato
# ---------------------------------------------------------------------------
def formato_importe(valor: float | None) -> str:
    if valor is None or pd.isna(valor):
        return "No publicado"
    return f"{valor:,.2f} €".replace(",", "@").replace(".", ",").replace("@", ".")


def formato_fecha(valor) -> str:
    if valor is None or pd.isna(valor):
        return "—"
    if isinstance(valor, str):
        return valor
    try:
        return pd.to_datetime(valor).strftime("%d/%m/%Y %H:%M")
    except (ValueError, TypeError):
        return str(valor)


def tabla_para_mostrar(df: pd.DataFrame, columnas: list[str]) -> pd.DataFrame:
    presentes = [c for c in columnas if c in df.columns]
    vista = df[presentes].copy()
    for columna in vista.columns:
        if vista[columna].map(lambda v: isinstance(v, (list, tuple))).any():
            vista[columna] = vista[columna].map(
                lambda v: ", ".join(str(x) for x in v) if isinstance(v, (list, tuple)) else v
            )
    return vista.rename(columns={c: COLUMN_LABELS.get(c, c) for c in vista.columns})


CONFIG_COLUMNAS = {
    COLUMN_LABELS["relevancia"]: st.column_config.ProgressColumn(
        "Relevancia GREFA", min_value=0, max_value=100, format="%d%%", width="medium"
    ),
    COLUMN_LABELS["url"]: st.column_config.LinkColumn(
        "Enlace", display_text="Abrir en PLACSP", width="small"
    ),
    COLUMN_LABELS["presupuesto_sin_iva"]: st.column_config.NumberColumn(
        "Presupuesto (sin IVA)", format="%.2f €"
    ),
    COLUMN_LABELS["titulo"]: st.column_config.TextColumn("Título / Objeto", width="large"),
    COLUMN_LABELS["fecha_actualizacion"]: st.column_config.DatetimeColumn(
        "Actualizada", format="DD/MM/YYYY HH:mm"
    ),
    COLUMN_LABELS["fecha_limite"]: st.column_config.DatetimeColumn(
        "Límite presentación", format="DD/MM/YYYY"
    ),
}


def botones_exportacion(df: pd.DataFrame, sufijo: str, permitir_sheets: bool = False) -> None:
    if df.empty:
        st.caption("No hay resultados que exportar con los filtros actuales.")
        return
    izquierda, derecha, sheets, _ = st.columns([1, 1, 1.4, 1.6])
    with izquierda:
        st.download_button(
            "⬇️ Descargar CSV",
            data=to_csv_bytes(df),
            file_name=timestamped_filename(f"licitaciones_{sufijo}", "csv"),
            mime="text/csv",
            width="stretch",
            key=f"csv_{sufijo}",
        )
    with derecha:
        st.download_button(
            "⬇️ Descargar Excel",
            data=to_excel_bytes(df),
            file_name=timestamped_filename(f"licitaciones_{sufijo}", "xlsx"),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
            key=f"xlsx_{sufijo}",
        )
    if permitir_sheets and sheets_store.is_configured():
        with sheets:
            if st.button(
                "📗 Enviar a Google Sheets",
                width="stretch",
                key=f"sheets_{sufijo}",
                help="Añade a la pestaña «Oportunidades» las que aún no estén registradas",
            ):
                try:
                    anadidas, omitidas = sheets_store.append_opportunities(df)
                    st.toast(
                        f"{anadidas} oportunidades nuevas en la hoja "
                        f"({omitidas} ya estaban registradas).",
                        icon="✅",
                    )
                except sheets_store.SheetsError as exc:
                    st.error(str(exc))


def _clave_expediente(expediente: str, url: str) -> str:
    return f"{str(expediente).strip().lower()}|{str(url).strip().lower()}"


def _cargar_mis_licitaciones_cache(*, forzar: bool = False) -> list[dict]:
    if not sheets_store.is_configured():
        return list(st.session_state.get("mis_licitaciones_local") or [])
    if forzar or st.session_state.get("mis_licitaciones_cache") is None:
        try:
            st.session_state["mis_licitaciones_cache"] = sheets_store.load_mis_licitaciones()
        except Exception as exc:
            st.session_state["mis_licitaciones_cache"] = list(
                st.session_state.get("mis_licitaciones_local") or []
            )
            st.caption(f"Mis Licitaciones (caché local): {exc}")
    return list(st.session_state.get("mis_licitaciones_cache") or [])


def _claves_interes() -> set[str]:
    return {
        _clave_expediente(f.get("expediente", ""), f.get("url", ""))
        for f in _cargar_mis_licitaciones_cache()
    }


def _marcar_interes(fila: pd.Series | dict, *, interesa: bool) -> None:
    get = fila.get if hasattr(fila, "get") else lambda k, d="": d
    expediente = str(get("expediente", "") or "")
    url = str(get("url", "") or "")
    presupuesto = get("presupuesto_sin_iva", "")
    if presupuesto is not None and str(presupuesto) not in {"", "nan", "None"}:
        try:
            presupuesto = f"{float(presupuesto):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        except Exception:
            presupuesto = str(presupuesto)
    else:
        presupuesto = ""
    payload = dict(
        expediente=expediente,
        enlace=url,
        titulo=str(get("titulo", "") or ""),
        organo=str(get("organo_contratacion", "") or get("organo", "") or ""),
        presupuesto=presupuesto,
        estado=str(get("estado", "") or ""),
        relevancia=str(get("relevancia", "") or ""),
        me_interesa=interesa,
    )
    if sheets_store.is_configured():
        sheets_store.upsert_mi_licitacion(**payload)
        st.session_state["mis_licitaciones_cache"] = None
    else:
        local = list(st.session_state.setdefault("mis_licitaciones_local", []))
        clave = _clave_expediente(expediente, url)
        local = [x for x in local if _clave_expediente(x.get("expediente", ""), x.get("url", "")) != clave]
        if interesa:
            local.append(
                {
                    "expediente": expediente,
                    "url": url,
                    "titulo": payload["titulo"],
                    "organo": payload["organo"],
                    "presupuesto": presupuesto,
                    "estado": payload["estado"],
                    "relevancia": payload["relevancia"],
                    "me_interesa": "sí",
                    "me_presento": "no",
                    "fecha_interes": datetime.now().strftime("%d/%m/%Y %H:%M"),
                    "notas": "",
                }
            )
        st.session_state["mis_licitaciones_local"] = local
        st.session_state["mis_licitaciones_cache"] = local


def _render_resultados_con_interes(
    resultados: pd.DataFrame,
    *,
    clave_prefix: str,
    max_filas: int = 40,
) -> None:
    """Lista resultados con checkbox «Me interesa» a la izquierda."""
    if resultados.empty:
        return
    interes = _claves_interes()
    st.caption(
        "Marca ⭐ **Me interesa** para enviarla a la pestaña **Mis Licitaciones**."
    )
    for i, (_, fila) in enumerate(resultados.head(max_filas).iterrows()):
        clave = _clave_expediente(str(fila.get("expediente") or ""), str(fila.get("url") or ""))
        marcado = clave in interes
        c0, c1 = st.columns([0.08, 0.92])
        with c0:
            nuevo = st.checkbox(
                "⭐",
                value=marcado,
                key=f"int_{clave_prefix}_{i}_{clave[:40]}",
                help="Me interesa esta licitación",
            )
        with c1:
            exp = fila.get("expediente") or "—"
            tit = str(fila.get("titulo") or "")[:120]
            organo = str(fila.get("organo_contratacion") or "")[:80]
            meta = " · ".join(
                x
                for x in (
                    str(fila.get("estado") or ""),
                    organo,
                    f"{fila.get('relevancia')} %" if pd.notna(fila.get("relevancia")) else "",
                )
                if x
            )
            st.markdown(f"**{exp}** — {tit}")
            if meta:
                st.caption(meta)
            if fila.get("url"):
                st.markdown(f"[PLACSP ↗]({fila.get('url')})")
        if nuevo != marcado:
            try:
                _marcar_interes(fila, interesa=nuevo)
                st.toast(
                    "Añadida a Mis Licitaciones." if nuevo else "Quitada de Mis Licitaciones.",
                    icon="⭐" if nuevo else "🗑️",
                )
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    if len(resultados) > max_filas:
        st.caption(f"Mostrando {max_filas} de {len(resultados):,} (exporta para ver todas).")


def _cargar_seguimiento_cache() -> dict:
    if not sheets_store.is_configured():
        return {}
    try:
        return sheets_store.load_opportunities_tracking()
    except sheets_store.SheetsError as exc:
        st.session_state["seguimiento_estado"] = str(exc)
        return {}


def _docs_desde_fila(fila: pd.Series | dict | None) -> list[dict]:
    if fila is None:
        return []
    try:
        docs = fila.get("documentos") if hasattr(fila, "get") else None
    except Exception:
        docs = None
    if isinstance(docs, list):
        return [d for d in docs if isinstance(d, dict) and d.get("url")]
    return []


def _sembrar_checklist_desde_resumen(
    expediente: str, url: str, titulo: str, resumen: str
) -> None:
    """Crea checklist en Sheets a partir del resumen IA (si aún no existe)."""
    if not sheets_store.is_configured() or not expediente:
        return
    try:
        existentes = sheets_store.load_checklist(expediente, url)
        if existentes:
            return
        extras = sheets_store.parse_documentacion_desde_resumen(resumen)
        sheets_store.ensure_checklist(expediente, url, titulo, items=extras)
    except Exception:
        pass


def _widget_checklist_docs(
    expediente: str,
    url: str,
    titulo: str,
    *,
    clave_prefix: str,
    organo: str = "",
) -> None:
    """Checklist de documentación a preparar, con estados y subida a Drive."""
    if not expediente and not url:
        st.caption("Selecciona o indica un expediente para el checklist.")
        return
    if not sheets_store.is_configured():
        st.info("Configura Google Sheets para guardar el checklist en Drive.")
        return

    carpeta_prevista = drive_docs.nombre_carpeta_expediente(expediente, organo)
    st.markdown("**Checklist de documentación**")
    st.caption(
        "Pendiente · En preparación · Preparado · No aplica. "
        f"Los ficheros se guardan en Drive → `{carpeta_prevista}`."
    )

    # No golpear Sheets hasta que el usuario lo pida (evita 429 al abrir la pestaña).
    cargar_key = f"chk_loaded_{clave_prefix}_{_clave_expediente(expediente, url)[:40]}"
    col_load, _ = st.columns([1, 2])
    with col_load:
        if st.button(
            "📂 Abrir checklist en Sheets",
            key=f"chk_open_{clave_prefix}",
            type="primary",
            width="stretch",
        ):
            st.session_state[cargar_key] = True

    if not st.session_state.get(cargar_key):
        st.info("Pulsa «Abrir checklist en Sheets» cuando quieras trabajar la documentación.")
        return

    try:
        items = sheets_store.load_checklist(expediente, url)
    except Exception as exc:
        st.warning(
            f"No se pudo leer el checklist ahora: {exc}. "
            "Si es cuota 429, espera un minuto y vuelve a pulsar Abrir."
        )
        if st.button("Reintentar", key=f"chk_retry_{clave_prefix}"):
            st.session_state[cargar_key] = True
            st.rerun()
        return

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button(
            "📋 Crear / cargar plantilla GREFA",
            key=f"chk_crear_{clave_prefix}",
            width="stretch",
        ):
            try:
                resumen = (st.session_state.get("pdf_resumenes") or {}).get(
                    _clave_expediente(expediente, url), ""
                )
                extras = sheets_store.parse_documentacion_desde_resumen(resumen)
                items = sheets_store.ensure_checklist(
                    expediente, url, titulo, items=extras
                )
                st.toast(f"Checklist listo ({len(items)} documentos).", icon="📋")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    with col_b:
        nuevo = st.text_input(
            "Añadir documento",
            key=f"chk_nuevo_{clave_prefix}",
            placeholder="Ej. Certificado de penalidades…",
        )
        if nuevo.strip() and st.button(
            "➕ Añadir", key=f"chk_add_{clave_prefix}", width="stretch"
        ):
            try:
                sheets_store.upsert_checklist_item(
                    expediente,
                    url,
                    nuevo.strip(),
                    titulo=titulo,
                    estado="Pendiente",
                )
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    if not items:
        st.info(
            "Aún no hay checklist. Pulsa «Crear / cargar plantilla GREFA» "
            "(o genera antes un resumen IA para incorporar requisitos del pliego)."
        )
        return

    pendientes = sum(1 for i in items if i.get("estado") == "Pendiente")
    en_prep = sum(1 for i in items if i.get("estado") == "En preparación")
    listos = sum(1 for i in items if i.get("estado") == "Preparado")
    st.caption(f"Resumen: {listos} preparados · {en_prep} en preparación · {pendientes} pendientes")

    for idx, item in enumerate(items):
        doc = item.get("documento") or f"Documento {idx + 1}"
        row_n = int(item.get("_row") or 0) or None
        with st.container(border=True):
            st.markdown(f"**{doc}**")
            c1, c2 = st.columns([1, 2])
            with c1:
                estado = st.selectbox(
                    "Estado",
                    sheets_store.CHECKLIST_ESTADOS,
                    index=(
                        list(sheets_store.CHECKLIST_ESTADOS).index(item["estado"])
                        if item.get("estado") in sheets_store.CHECKLIST_ESTADOS
                        else 0
                    ),
                    key=f"chk_est_{clave_prefix}_{idx}",
                )
            with c2:
                notas = st.text_input(
                    "Notas",
                    value=item.get("notas") or "",
                    key=f"chk_notas_{clave_prefix}_{idx}",
                )
            enlace_drive = item.get("enlace_drive") or ""
            if enlace_drive:
                st.markdown(f"[📄 Abrir en Drive]({enlace_drive})")

            up = st.file_uploader(
                "Subir fichero a Drive",
                type=None,
                key=f"chk_up_{clave_prefix}_{idx}",
                help="Se guarda en Drive (cuenta de servicio) y se enlaza aquí.",
            )
            pegado = st.text_input(
                "O pegar enlace Drive",
                value=enlace_drive,
                key=f"chk_link_{clave_prefix}_{idx}",
            )
            if st.button("💾 Guardar ítem", key=f"chk_save_{clave_prefix}_{idx}"):
                try:
                    link_final = (pegado or "").strip()
                    if up is not None:
                        subido = drive_docs.upload_bytes(
                            up.getvalue(),
                            up.name or f"{doc}.bin",
                            expediente=expediente,
                            organo=organo,
                        )
                        link_final = subido.get("webViewLink") or link_final
                        if subido.get("folderLink"):
                            st.caption(
                                f"Carpeta: [{carpeta_prevista}]({subido['folderLink']})"
                            )
                    sheets_store.upsert_checklist_item(
                        expediente,
                        url,
                        doc,
                        titulo=titulo,
                        estado=estado,
                        notas=notas,
                        enlace_drive=link_final,
                        row=row_n,
                    )
                    st.toast("Documento y checklist guardados en Drive.", icon="✅")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))


def _widget_resumen_pliego(
    expediente: str,
    url: str,
    titulo: str,
    *,
    clave_prefix: str,
    documentos: list[dict] | None = None,
) -> None:
    """Multi-PDF (PCAP/PPT) + descarga desde ficha PLACSP + resumen IA."""
    if not pdf_summary.is_configured():
        st.caption("Configura `[gemini] api_key` en Secrets para activar el resumen IA.")
        return

    clave = _clave_expediente(expediente, url)
    resumenes = st.session_state.setdefault("pdf_resumenes", {})
    cache_docs_key = f"placsp_docs_cache_{clave_prefix}"
    docs_placsp = list(
        st.session_state.get(cache_docs_key)
        or documentos
        or []
    )
    # Clave estable: no depende del texto del expediente (evita vaciar el uploader al teclear).
    stash_key = f"pdf_stash_{clave_prefix}"
    stash: dict[str, bytes] = st.session_state.setdefault(stash_key, {})

    if sheets_store.is_configured():
        guardado = sheets_store.load_pliego_resumen(expediente, url)
        if guardado and clave not in resumenes:
            resumenes[clave] = guardado

    if clave in resumenes:
        st.markdown(resumenes[clave])
        if st.button("🗑️ Borrar resumen de sesión", key=f"borrar_resumen_{clave_prefix}"):
            resumenes.pop(clave, None)
            st.rerun()
        return

    if url:
        st.caption(
            "Para **cualquier** licitación: ficha PLACSP → PDF/HTML «Pliego» → "
            "enlaces internos al PCAP y PPT (si el feed CODICE no los trae ya)."
        )
        if docs_placsp:
            st.caption(
                "Documentos detectados: "
                + ", ".join(
                    f"{d.get('tipo', '?')}: {d.get('nombre', 'doc')}"
                    for d in docs_placsp[:8]
                )
            )
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            leer_ficha = st.button(
                "🔗 Leer enlaces de la ficha PLACSP",
                key=f"placsp_scan_{clave_prefix}",
                width="stretch",
            )
        with col_f2:
            analizar = st.button(
                "⬇️ Descargar pliegos y analizar",
                key=f"placsp_docs_{clave_prefix}",
                type="primary",
                width="stretch",
            )

        if leer_ficha:
            with st.spinner("Leyendo documentos de la ficha PLACSP…"):
                try:
                    docs_placsp = pliegos_placsp.resolver_documentos(
                        documentos, url, forzar_ficha=True
                    )
                    st.session_state[cache_docs_key] = docs_placsp
                    if docs_placsp:
                        st.success(f"{len(docs_placsp)} documento(s) con enlace público.")
                    else:
                        st.warning(
                            "La ficha no expuso PDFs descargables (a veces requieren sesión)."
                        )
                    st.rerun()
                except Exception as exc:
                    st.error(f"No se pudo leer la ficha: {exc}")

        if analizar:
            with st.spinner("Obteniendo pliegos de PLACSP y analizando con Gemini…"):
                try:
                    docs_placsp = pliegos_placsp.resolver_documentos(
                        docs_placsp or documentos, url, forzar_ficha=True
                    )
                    st.session_state[cache_docs_key] = docs_placsp
                    descargados = pliegos_placsp.download_documentos(
                        docs_placsp,
                        solo_tipos=("PCAP", "PPT", "PLIEGO"),
                        max_docs=6,
                        url_detalle=url,
                    )
                    ok = [d for d in descargados if d.get("bytes")]
                    fallos = [d for d in descargados if d.get("error")]
                    for fallo in fallos:
                        st.warning(f"{fallo.get('nombre')}: {fallo.get('error')}")
                    if not ok:
                        st.error(
                            "No se pudo descargar ningún pliego público desde PLACSP. "
                            "Prueba a subir el PCAP y el PPT manualmente."
                        )
                    else:
                        texto = pdf_summary.summarize_documentos(
                            ok, expediente=expediente, titulo=titulo
                        )
                        resumenes[clave] = texto
                        if sheets_store.is_configured():
                            sheets_store.save_pliego_resumen(expediente, url, titulo, texto)
                            _sembrar_checklist_desde_resumen(
                                expediente, url, titulo, texto
                            )
                            st.toast("Resumen y checklist guardados en Drive.", icon="✅")
                        st.rerun()
                except pdf_summary.PdfSummaryError as exc:
                    st.error(str(exc))
                except Exception as exc:
                    st.error(f"Error al obtener pliegos: {exc}")
    else:
        st.caption(
            "Sin enlace PLACSP: sube manualmente el PCAP y el PPT (PDF)."
        )

    st.markdown("**Subir pliegos (varios PDF)**")
    st.caption(
        "Puedes subir el PCAP y el PPT en pasos sucesivos: cada archivo se acumula "
        "en la lista (no sustituye al anterior). También puedes seleccionar varios a la vez."
    )
    ficheros = st.file_uploader(
        "Añadir PDF a la cola de análisis",
        type=["pdf"],
        accept_multiple_files=True,
        key=f"pdf_up_{clave_prefix}",
    )
    # Streamlit sustituye la selección del uploader; acumulamos en sesión por nombre.
    sig_key = f"{stash_key}_sig"
    if ficheros:
        firma = tuple(
            sorted(
                (
                    Path(getattr(f, "name", "") or "documento.pdf").name,
                    len(f.getvalue()),
                )
                for f in ficheros
            )
        )
        if firma != st.session_state.get(sig_key):
            for f in ficheros:
                nombre = Path(getattr(f, "name", "") or "documento.pdf").name
                if not nombre.lower().endswith(".pdf"):
                    nombre = f"{nombre}.pdf"
                stash[nombre] = f.getvalue()
            st.session_state[stash_key] = stash
            st.session_state[sig_key] = firma

    if stash:
        st.success(
            f"**{len(stash)} PDF en cola:** "
            + ", ".join(
                f"{pliegos_placsp.etiquetar_upload(n)} · {n}" for n in stash.keys()
            )
        )
        col_gen, col_clr = st.columns([2, 1])
        with col_clr:
            if st.button("🗑️ Vaciar cola", key=f"vaciar_pdf_{clave_prefix}", width="stretch"):
                st.session_state[stash_key] = {}
                st.session_state.pop(f"{stash_key}_sig", None)
                st.rerun()
        with col_gen:
            if st.button(
                "✨ Generar resumen con IA",
                key=f"resumir_{clave_prefix}",
                type="primary",
                width="stretch",
            ):
                with st.spinner(f"Analizando {len(stash)} PDF con Gemini…"):
                    try:
                        docs_up = [
                            {
                                "nombre": nombre,
                                "tipo": pliegos_placsp.etiquetar_upload(nombre),
                                "bytes": contenido,
                            }
                            for nombre, contenido in stash.items()
                        ]
                        texto = pdf_summary.summarize_documentos(
                            docs_up, expediente=expediente, titulo=titulo
                        )
                        resumenes[clave] = texto
                        st.session_state[stash_key] = {}
                        if sheets_store.is_configured():
                            sheets_store.save_pliego_resumen(expediente, url, titulo, texto)
                            _sembrar_checklist_desde_resumen(
                                expediente, url, titulo, texto
                            )
                            st.toast("Resumen y checklist guardados en Drive.", icon="✅")
                        st.rerun()
                    except pdf_summary.PdfSummaryError as exc:
                        st.error(str(exc))
                    except sheets_store.SheetsError as exc:
                        st.warning(f"Resumen generado pero no guardado en Sheets: {exc}")
                        if clave in resumenes:
                            st.markdown(resumenes[clave])
    else:
        st.info("Aún no hay PDF en cola. Sube al menos el PCAP y el PPT.")


def tarjeta_licitacion(fila: pd.Series) -> None:
    nivel = RELEVANCE_LEVELS.get(fila["categoria"], RELEVANCE_LEVELS["Baja"])
    cpvs = " ".join(f"<span class='chip'>{codigo}</span>" for codigo in (fila.get("cpvs") or [])[:8])
    keywords = ", ".join(fila.get("keywords_match") or []) or "—"
    titulo = fila["titulo"] or "(Sin título en el expediente)"

    st.markdown(
        f"""
        <div class="tarjeta" style="--color-acento: {nivel['color']};">
            <div style="display:flex; justify-content:space-between; align-items:center; gap:1rem;">
                <span class="badge" style="background:{nivel['color']};">
                    {nivel['emoji']} {fila['badge']} · {fila['relevancia']}%
                </span>
                <span class="meta">{formato_fecha(fila.get('fecha_actualizacion'))}</span>
            </div>
            <h4>{titulo}</h4>
            <p class="meta"><strong>Órgano:</strong> {fila.get('organo_contratacion') or '—'}</p>
            <p class="meta">
                <strong>Presupuesto (sin IVA):</strong> {formato_importe(fila.get('presupuesto_sin_iva'))}
                &nbsp;·&nbsp; <strong>Ubicación:</strong> {fila.get('ubicacion') or '—'}
                &nbsp;·&nbsp; <strong>Estado:</strong> {fila.get('estado') or '—'}
            </p>
            <p class="meta"><strong>Expediente:</strong> {fila.get('expediente') or '—'}
                &nbsp;·&nbsp; <strong>Palabras clave:</strong> {keywords}</p>
            <p class="meta"><strong>NIF órgano:</strong> {fila.get('nif_organo') or '—'}
                &nbsp;·&nbsp; <strong>Adjudicatario:</strong> {fila.get('adjudicatario') or '—'}
                {f" ({fila.get('nif_adjudicatario')})" if fila.get('nif_adjudicatario') else ""}</p>
            <p class="meta">{cpvs}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    columna_enlace, columna_motivo = st.columns([1, 4])
    with columna_enlace:
        if fila.get("url"):
            st.link_button("Ver en PLACSP ↗", fila["url"], width="stretch")
    with columna_motivo:
        with st.expander("¿Por qué esta puntuación?"):
            st.write(fila.get("justificacion", ""))
            if fila.get("descripcion"):
                st.caption(fila["descripcion"][:800])

    expediente = str(fila.get("expediente") or "")
    url = str(fila.get("url") or "")
    clave = _clave_expediente(expediente, url)
    seguimiento = st.session_state.get("seguimiento_cache", {}).get(clave, {})
    if seguimiento:
        st.caption(f"📋 Seguimiento: **{seguimiento.get('seguimiento', '—')}**")

    with st.expander("📄 Resumir pliegos (IA)"):
        _widget_resumen_pliego(
            expediente,
            url,
            str(fila.get("titulo") or ""),
            clave_prefix=f"tarjeta_{clave[:40]}",
            documentos=_docs_desde_fila(fila),
        )


# ---------------------------------------------------------------------------
# Barra superior: criterios de búsqueda (CPV, términos, estado)
# ---------------------------------------------------------------------------
def _etiqueta_estados(estados: list[str] | None, max_chars: int = 28) -> str:
    if not estados:
        return "todos"
    texto = ", ".join(estados)
    return texto if len(texto) <= max_chars else texto[: max_chars - 1] + "…"


def _como_date(valor) -> date | None:
    """Convierte Timestamp/datetime/str a date para los selectores."""
    if valor is None:
        return None
    if isinstance(valor, date) and not isinstance(valor, datetime):
        return valor
    try:
        if pd.isna(valor):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return pd.Timestamp(valor).date()
    except (ValueError, TypeError):
        return None


def _rango_fechas_disponible(df: pd.DataFrame, campo: str | None = None) -> tuple[date, date]:
    """Rango permitido en los selectores (unión de columnas de fecha si no se indica campo)."""
    hoy = date.today()
    fallback_min = hoy - timedelta(days=730)
    fallback_max = hoy + timedelta(days=730)

    if df.empty:
        return fallback_min, fallback_max

    campos = [campo] if campo else ["fecha_actualizacion", "fecha_limite"]
    minimos: list[date] = []
    maximos: list[date] = []
    for nombre in campos:
        if nombre not in df.columns:
            continue
        fechas = pd.to_datetime(df[nombre], errors="coerce").dropna()
        if fechas.empty:
            continue
        minimos.append(fechas.min().date())
        maximos.append(fechas.max().date())

    if not minimos:
        return fallback_min, fallback_max

    min_d, max_d = min(minimos), max(maximos)
    if min_d >= max_d:
        max_d = min_d + timedelta(days=1)
    return min_d, max_d


def _clamp_date(valor: date, min_d: date, max_d: date) -> date:
    if valor < min_d:
        return min_d
    if valor > max_d:
        return max_d
    return valor


def _limpiar_busqueda_estandar() -> None:
    pass


def _limpiar_busqueda_libre() -> None:
    st.session_state["estados_aplicados"] = list(ESTADOS_ABIERTOS_DEFAULT)
    st.session_state["_reset_filtro_estados"] = True
    st.session_state["usar_fechas_aplicado"] = False
    st.session_state["fecha_campo_aplicado"] = "fecha_actualizacion"
    st.session_state["fecha_desde_aplicada"] = None
    st.session_state["fecha_hasta_aplicada"] = None
    st.session_state["incluir_sin_fecha_aplicado"] = True
    st.session_state["_reset_filtro_fechas"] = True
    st.session_state["opp_categorias_aplicadas"] = ["Alta", "Media"]
    st.session_state["opp_min_relevancia_aplicado"] = MEDIUM_RELEVANCE_THRESHOLD
    st.session_state["_reset_opp_categorias"] = True


def _limpiar_filtros_busqueda() -> None:
    _limpiar_busqueda_estandar()
    _limpiar_busqueda_libre()
    st.session_state["busqueda_aplicada"] = ""
    st.session_state["busqueda_borrador"] = ""


def _aplicar_filtros_oportunidades() -> None:
    borrador = list(st.session_state.get("opp_categorias_borrador") or [])
    st.session_state["opp_categorias_aplicadas"] = borrador
    st.session_state["opp_min_relevancia_aplicado"] = int(
        st.session_state.get("opp_min_relevancia", MEDIUM_RELEVANCE_THRESHOLD)
    )


def _aplicar_busqueda_estandar() -> None:
    """CPV y términos se aplican al activarlos en catálogo; rerun refresca scoring."""
    return


def _aplicar_busqueda_libre() -> str | None:
    """Copia borradores de búsqueda libre. Devuelve error o None."""
    if st.session_state.get("filtro_usar_fechas"):
        desde = _como_date(st.session_state.get("filtro_fecha_desde"))
        hasta = _como_date(st.session_state.get("filtro_fecha_hasta"))
        if desde and hasta and desde > hasta:
            return "La fecha «Desde» no puede ser posterior a «Hasta»."
    st.session_state["estados_aplicados"] = list(st.session_state.get("filtro_estados") or [])
    _aplicar_borrador_fechas()
    _aplicar_filtros_oportunidades()
    return None


def _etiqueta_fechas_borrador(max_chars: int = 22) -> str:
    if not st.session_state.get("filtro_usar_fechas"):
        return "off"
    desde = _como_date(st.session_state.get("filtro_fecha_desde"))
    hasta = _como_date(st.session_state.get("filtro_fecha_hasta"))
    if desde and hasta:
        texto = f"{desde:%d/%m/%y}–{hasta:%d/%m/%y}"
        return texto if len(texto) <= max_chars else texto[: max_chars - 1] + "…"
    return "on"


def _etiqueta_fechas(max_chars: int = 22) -> str:
    if not st.session_state.get("usar_fechas_aplicado"):
        return "off"
    desde = _como_date(st.session_state.get("fecha_desde_aplicada"))
    hasta = _como_date(st.session_state.get("fecha_hasta_aplicada"))
    if desde and hasta:
        texto = f"{desde:%d/%m/%y}–{hasta:%d/%m/%y}"
        return texto if len(texto) <= max_chars else texto[: max_chars - 1] + "…"
    return "on"


def _inicializar_borrador_fechas(df: pd.DataFrame) -> None:
    min_d, max_d = _rango_fechas_disponible(df)
    if "filtro_fecha_desde" not in st.session_state:
        st.session_state["filtro_fecha_desde"] = min_d
    if "filtro_fecha_hasta" not in st.session_state:
        st.session_state["filtro_fecha_hasta"] = max_d


def _estados_disponibles(df: pd.DataFrame) -> list[str]:
    if df.empty:
        return []
    return sorted({str(e).strip() for e in df["estado"].unique() if e})


def _render_fechas_inline(df: pd.DataFrame, *, en_formulario: bool = False) -> None:
    """Filtros en línea de búsqueda libre: estado, fechas.

    Con ``en_formulario=True`` los widgets no disparan rerun hasta «Buscar»;
    las fechas quedan editables y solo se aplican si el checkbox está activo.
    """
    if st.session_state.pop("_reset_filtro_fechas", False):
        st.session_state["filtro_usar_fechas"] = False
        st.session_state["filtro_fecha_campo"] = "fecha_actualizacion"
        st.session_state["filtro_incluir_sin_fecha"] = True
        st.session_state.pop("filtro_fecha_desde", None)
        st.session_state.pop("filtro_fecha_hasta", None)

    if st.session_state.pop("_reset_filtro_estados", False):
        st.session_state["filtro_estados"] = list(ESTADOS_ABIERTOS_DEFAULT)

    min_d, max_d = _rango_fechas_disponible(df)
    _inicializar_borrador_fechas(df)
    usar = bool(st.session_state.get("filtro_usar_fechas"))
    disponibles = _estados_disponibles(df)
    # En formulario no hay rerun al marcar el checkbox: fechas siempre editables.
    fechas_bloqueadas = False if en_formulario else (not usar)

    ce, cv = st.columns([0.34, 0.66], gap="small")
    with ce:
        _celda_etiqueta("Fechas")
    with cv:
        st.checkbox(
            "Activar filtro por fechas",
            key="filtro_usar_fechas",
            help="Solo se aplica al pulsar «Buscar».",
        )

    c1, c2, c3, c4 = st.columns([1.1, 0.7, 0.7, 0.55], gap="small")
    with c1:
        st.multiselect(
            "Estado",
            options=disponibles,
            key="filtro_estados",
            placeholder="Publicada, Adjudicada…",
            help="Vacío = todos los estados. No carga datos hasta pulsar «Buscar».",
            disabled=not disponibles,
        )
    with c2:
        st.date_input(
            "Desde",
            min_value=min_d,
            max_value=max_d,
            format="DD/MM/YYYY",
            key="filtro_fecha_desde",
            disabled=fechas_bloqueadas,
        )
    with c3:
        st.date_input(
            "Hasta",
            min_value=min_d,
            max_value=max_d,
            format="DD/MM/YYYY",
            key="filtro_fecha_hasta",
            disabled=fechas_bloqueadas,
        )
    with c4:
        st.checkbox(
            "Sin fecha",
            key="filtro_incluir_sin_fecha",
            disabled=fechas_bloqueadas,
            help="Incluir licitaciones sin fecha de actualización",
        )


def render_filtro_fechas(df: pd.DataFrame) -> None:
    """Filtro por fechas en popover (legacy; no usado en panel principal)."""
    _render_fechas_inline(df)


def _aplicar_borrador_fechas() -> None:
    usar = bool(st.session_state.get("filtro_usar_fechas"))
    st.session_state["usar_fechas_aplicado"] = usar
    if usar:
        st.session_state["fecha_campo_aplicado"] = st.session_state.get(
            "filtro_fecha_campo", "fecha_actualizacion"
        )
        st.session_state["fecha_desde_aplicada"] = st.session_state.get("filtro_fecha_desde")
        st.session_state["fecha_hasta_aplicada"] = st.session_state.get("filtro_fecha_hasta")
        st.session_state["incluir_sin_fecha_aplicado"] = bool(
            st.session_state.get("filtro_incluir_sin_fecha", True)
        )
    else:
        st.session_state["fecha_desde_aplicada"] = None
        st.session_state["fecha_hasta_aplicada"] = None


def _resumen_busqueda_estandar_borrador(n_cpv: int, n_terms: int) -> str:
    return f"Estandarizada: {n_cpv} CPV · {n_terms} términos"


def _resumen_busqueda_libre_borrador() -> str:
    partes: list[str] = []
    estados = st.session_state.get("filtro_estados") or []
    if estados:
        partes.append(f"estado: {', '.join(estados)}")
    else:
        partes.append("estado: todos")
    if st.session_state.get("filtro_usar_fechas"):
        desde = _como_date(st.session_state.get("filtro_fecha_desde"))
        hasta = _como_date(st.session_state.get("filtro_fecha_hasta"))
        if desde and hasta:
            partes.append(f"fechas: {desde:%d/%m/%Y}–{hasta:%d/%m/%Y}")
    else:
        partes.append("fechas: sin filtrar")
    min_rel = st.session_state.get("opp_min_relevancia")
    if min_rel is not None:
        partes.append(f"rel. mín. {int(min_rel)}%")
    vista = st.session_state.get("opp_vista") or "Tarjetas"
    partes.append(f"vista: {vista}")
    cats = st.session_state.get("opp_categorias_borrador") or []
    if cats:
        partes.append(f"categorías: {', '.join(cats)}")
    return "Libre: " + " · ".join(partes)


def _celda_etiqueta(texto: str) -> None:
    st.markdown(f'<div class="grid-etiq">{texto}</div>', unsafe_allow_html=True)


def _celda_valor(texto: str) -> None:
    st.markdown(f'<div class="grid-val">{texto}</div>', unsafe_allow_html=True)


def _celda_par(etiqueta: str, valor: str) -> None:
    st.markdown(
        f'<div class="grid-par">'
        f'<span class="grid-etiq">{etiqueta}</span>'
        f'<span class="grid-val">{valor}</span>'
        f"</div>",
        unsafe_allow_html=True,
    )


def _fila_etiq_valor(etiqueta: str, valor: str) -> None:
    _celda_par(etiqueta, valor)


def _fila_popover(etiqueta: str, popover_label: str, contenido) -> None:
    ce, cv = st.columns([0.28, 0.72], gap="small")
    with ce:
        _celda_etiqueta(etiqueta)
    with cv:
        with st.popover(popover_label, width="stretch"):
            contenido()


def panel_control_superior(
    df: pd.DataFrame,
    puntuadas: pd.DataFrame,
    resumen: dict,
    n_cpv: int,
    n_conceptos: int,
) -> tuple[pd.DataFrame, str]:
    """Panel según mockup: filtros|stats, búsqueda, controles, pie oportunidades."""
    catalogo_cpv: list[dict] = st.session_state["catalogo_cpv"]
    catalogo_terminos: list[dict] = st.session_state["catalogo_terminos"]
    n_cpv_activos = sum(1 for c in catalogo_cpv if c.get("activo"))
    n_terms = sum(1 for t in catalogo_terminos if t.get("activo"))

    with st.container(border=True):
        st.markdown('<span class="zona-control-flag"></span>', unsafe_allow_html=True)
        st.markdown('<span class="panel-mockup-flag"></span>', unsafe_allow_html=True)
        st.markdown(
            '<span class="cabecera-titulo">🦅 GREFA · Licitaciones PLACSP</span>',
            unsafe_allow_html=True,
        )

        # ── Estadísticas globales ──
        st.markdown('<span class="col-stats-flag"></span>', unsafe_allow_html=True)
        s1, s2, s3, s4, s5 = st.columns(5, gap="small")
        with s1:
            _celda_par("Descargados", str(resumen["total"]))
        with s2:
            _celda_par("Alta", str(resumen["alta"]))
        with s3:
            _celda_par("Media", str(resumen["media"]))
        with s4:
            _celda_par("Baja", str(resumen["baja"]))
        with s5:
            _celda_par("Criterios", f"{n_cpv} CPV · {n_conceptos}")

        # ── 1. Búsqueda estandarizada GREFA (CPV · Términos) ──
        st.markdown('<span class="bloque-estandar-flag"></span>', unsafe_allow_html=True)
        st.markdown(
            '<p class="bloque-seccion-titulo">Búsqueda estandarizada GREFA</p>',
            unsafe_allow_html=True,
        )
        c_cpv, c_term = st.columns(2, gap="small")
        with c_cpv:
            st.markdown('<span class="col-filtros-flag"></span>', unsafe_allow_html=True)
            _fila_popover("CPV", f"CPV · {n_cpv_activos}", render_cpv_catalog)
        with c_term:
            _fila_popover("Términos", f"Término · {n_terms}", render_term_catalog)
        st.markdown(
            f'<p class="resumen-filtros">{_resumen_busqueda_estandar_borrador(n_cpv_activos, n_terms)}</p>',
            unsafe_allow_html=True,
        )
        _, c_lim_e, c_bus_e = st.columns([6.2, 0.55, 0.6], gap="small")
        with c_lim_e:
            if st.button("Limpiar", key="btn_limpiar_estandar", width="stretch"):
                _limpiar_busqueda_estandar()
                st.rerun()
        with c_bus_e:
            if st.button("🔍 Buscar GREFA", key="btn_buscar_estandar", type="primary", width="stretch"):
                _aplicar_busqueda_estandar()
                st.rerun()

        # ── 2. Búsqueda libre (formulario: no rerun al tocar widgets) ──
        st.markdown('<span class="bloque-libre-flag"></span>', unsafe_allow_html=True)
        st.markdown(
            '<p class="bloque-seccion-titulo">Búsqueda libre</p>',
            unsafe_allow_html=True,
        )
        st.caption(
            "Ajusta Estado, fechas, relevancia y categorías; los resultados "
            "solo se actualizan al pulsar **Buscar**."
        )

        minimo = int(
            st.session_state.get("opp_min_relevancia_aplicado", MEDIUM_RELEVANCE_THRESHOLD)
        )
        categorias_aplicadas = list(st.session_state.get("opp_categorias_aplicadas") or [])
        oportunidades = grefa_filter.filter_opportunities(
            puntuadas, minimo, categorias_aplicadas
        )
        resumen_opp = grefa_filter.summarize(oportunidades) if not oportunidades.empty else None
        importe_opp = (
            formato_importe(resumen_opp["importe_oportunidades"]) if resumen_opp else "—"
        )

        if st.session_state.pop("_reset_opp_categorias", False):
            st.session_state["opp_categorias_borrador"] = list(
                st.session_state.get("opp_categorias_aplicadas") or ["Alta", "Media"]
            )

        with st.form("form_busqueda_libre", border=False, clear_on_submit=False):
            _render_fechas_inline(df, en_formulario=True)

            col_izq, col_der = st.columns([1.55, 1], gap="small")
            with col_izq:
                ce, cv = st.columns([0.34, 0.66], gap="small")
                with ce:
                    _celda_etiqueta("Rel. mín. %")
                with cv:
                    st.slider(
                        "Relevancia mínima",
                        min_value=0,
                        max_value=100,
                        step=5,
                        key="opp_min_relevancia",
                        label_visibility="collapsed",
                    )
                ce, cv = st.columns([0.34, 0.66], gap="small")
                with ce:
                    _celda_etiqueta("Vista")
                with cv:
                    st.radio(
                        "Vista",
                        ["Tarjetas", "Tabla"],
                        horizontal=True,
                        key="opp_vista",
                        label_visibility="collapsed",
                    )
                ce, cv = st.columns([0.34, 0.66], gap="small")
                with ce:
                    _celda_etiqueta("Categorías")
                with cv:
                    st.multiselect(
                        "Categorías",
                        options=["Alta", "Media", "Baja"],
                        key="opp_categorias_borrador",
                        label_visibility="collapsed",
                    )

            with col_der:
                st.markdown('<div class="opp-stats-spacer"></div>', unsafe_allow_html=True)
                o1, o2, o3 = st.columns(3, gap="small")
                with o1:
                    _celda_par(
                        "Oportunidades", str(resumen_opp["total"] if resumen_opp else 0)
                    )
                with o2:
                    _celda_par("Alta", str(resumen_opp["alta"] if resumen_opp else 0))
                with o3:
                    _celda_par("Importe", importe_opp)

            st.markdown(
                f'<p class="resumen-filtros">{_resumen_busqueda_libre_borrador()}</p>',
                unsafe_allow_html=True,
            )
            st.markdown('<span class="fila-buscar-flag"></span>', unsafe_allow_html=True)
            _, c_lim_l, c_bus_l = st.columns([6.2, 0.55, 0.6], gap="small")
            with c_lim_l:
                limpiar_libre = st.form_submit_button("Limpiar", width="stretch")
            with c_bus_l:
                buscar_libre = st.form_submit_button(
                    "🔍 Buscar", type="primary", width="stretch"
                )

        if limpiar_libre:
            _limpiar_busqueda_libre()
            st.rerun()
        if buscar_libre:
            error = _aplicar_busqueda_libre()
            if error:
                st.error(error)
            else:
                st.rerun()

    vista = str(st.session_state.get("opp_vista") or "Tarjetas")
    return oportunidades, vista


# ---------------------------------------------------------------------------
# Sidebar: fuente de datos y Google Sheets
# ---------------------------------------------------------------------------
def sidebar_fuente_datos() -> None:
    st.sidebar.header("🔄 Fuente de datos")

    if st.session_state["ultima_actualizacion"]:
        st.sidebar.success(
            f"Última extracción: {st.session_state['ultima_actualizacion']:%d/%m/%Y %H:%M}"
        )
        st.sidebar.caption(f"Origen: {st.session_state['origen_datos']}")
    else:
        st.sidebar.info("Sin datos cargados todavía.")

    with st.sidebar.expander("Parámetros de extracción"):
        st.text_input("URL del feed ATOM", key="feed_url")
        st.slider("Páginas del feed a recorrer", 1, 15, key="max_pages")
        st.slider(
            "Máximo de expedientes",
            100,
            5000,
            step=100,
            key="max_entries",
            help="Por defecto 500, los más recientes según fecha de actualización.",
        )
        st.caption(
            "Si la URL principal no responde, se prueban automáticamente las "
            "sindicaciones oficiales alternativas de contrataciondelestado.es."
        )

    if st.session_state.get("cargando_datos"):
        st.sidebar.info("⏳ Descargando licitaciones…")

    if st.sidebar.button("🔁 Actualizar datos ahora", type="primary", width="stretch"):
        st.session_state["refresh_token"] += 1
        st.session_state["cargando_datos"] = True
        st.rerun()

    with st.sidebar.expander("Cargar fichero ATOM local"):
        fichero = st.file_uploader("Archivo .atom / .xml", type=["atom", "xml"], key="uploader")
        if fichero is not None and st.button("Procesar fichero", width="stretch"):
            try:
                with st.spinner("Procesando fichero ATOM…"):
                    df = parse_atom_bytes(fichero.getvalue())
                st.session_state["datos"] = df
                st.session_state["origen_datos"] = f"Fichero local: {fichero.name}"
                st.session_state["ultima_actualizacion"] = datetime.now()
                st.session_state["error_descarga"] = ""
                st.rerun()
            except Exception as exc:
                st.error(f"No se pudo procesar el fichero: {exc}")


def sidebar_google_sheets() -> None:
    st.sidebar.header("📗 Google Sheets")

    if not sheets_store.is_configured():
        st.sidebar.caption(
            "Sin hoja compartida: los criterios solo viven en tu sesión y se pierden al recargar."
        )
        with st.sidebar.expander("Cómo conectarla"):
            st.markdown(
                "1. Crea una hoja de cálculo en Drive.\n"
                "2. Compártela como **Editor** con el correo de la cuenta de servicio.\n"
                "3. Define `GREFA_SPREADSHEET_ID` con el ID de la hoja "
                "(el tramo entre `/d/` y `/edit` de la URL).\n\n"
                "La app crea sola las pestañas de criterios, Oportunidades, Histórico y Config."
            )
        return

    st.sidebar.markdown(f"[Abrir hoja compartida ↗]({sheets_store.spreadsheet_url()})")
    if st.session_state["sheets_estado"]:
        st.sidebar.caption(st.session_state["sheets_estado"])

    columna_cargar, columna_guardar = st.sidebar.columns(2)
    with columna_cargar:
        if st.button("⬇️ Cargar", width="stretch", help="Traer los criterios de la hoja"):
            cargar_criterios_de_sheets()
            st.rerun()
    with columna_guardar:
        if st.button("⬆️ Guardar", width="stretch", help="Volcar los criterios actuales a la hoja"):
            guardar_criterios_en_sheets()
            st.rerun()

    st.sidebar.caption("**Sync diaria** (Histórico + alertas Chat)")
    # No leer Sheets en cada rerun: caché de sesión (la de Config dura ~10 min).
    if "_ultima_sync_hora_ui" not in st.session_state:
        st.session_state["_ultima_sync_hora_ui"] = sheets_historico.get_config(
            "ultima_ejecucion_hora", "—"
        )
    st.sidebar.caption(f"Última sync: {st.session_state['_ultima_sync_hora_ui']}")
    if email_alert.is_configured():
        st.sidebar.caption("Alertas: email al espacio Chat ✓")
    elif google_chat.is_configured():
        st.sidebar.caption("Alertas: webhook Chat ✓")
    else:
        st.sidebar.caption("Alertas: configura email del espacio en Secrets")

    if st.sidebar.button(
        "🔄 Sync histórico ahora",
        width="stretch",
        help="Guarda snapshot Alta/Media y avisa nuevas Alta (1×/día automático)",
    ):
        st.session_state["_forzar_sync_diaria"] = True
        st.session_state.pop("_sync_omitida_hoy", None)
        st.session_state.pop("_ultima_sync_hora_ui", None)
        sheets_historico.clear_config_cache()
        st.rerun()


def render_filtro_estado(df: pd.DataFrame) -> None:
    """Filtro global por estado PLACSP (persiste en la sesión)."""
    if st.session_state.pop("_reset_filtro_estados", False):
        st.session_state["filtro_estados"] = list(ESTADOS_ABIERTOS_DEFAULT)

    st.markdown("**Estado de la licitación**")
    disponibles = sorted({str(e).strip() for e in df["estado"].unique() if e}) if not df.empty else []

    if not disponibles:
        st.caption("Carga licitaciones para filtrar por estado.")
        return

    seleccion = st.multiselect(
        "Mostrar solo licitaciones en",
        options=disponibles,
        key="filtro_estados",
        help="Vacío = todos los estados. El filtro se aplica en ambas pestañas.",
    )
    if not seleccion:
        st.caption("Sin filtro de estado (todos). Se aplica al pulsar «Buscar».")
    else:
        st.caption(f"{len(seleccion)} estado(s). Se aplicará al pulsar «Buscar».")


def render_cpv_catalog() -> None:
    st.markdown("**Catálogo CPV**")
    catalogo: list[dict] = st.session_state["catalogo_cpv"]
    activos = [c for c in catalogo if c.get("activo")]
    st.caption(f"{len(activos)} activos de {len(catalogo)} códigos oficiales")

    with st.expander("CPV activos", expanded=False):
        if not activos:
            st.warning("Ninguno activo: el bloque del 50 % por CPV no puntuará.")
        else:
            for fila in activos[:80]:
                st.markdown(
                    f"<span class='chip'>{fila['codigo']}</span> "
                    f"<span class='meta'>{fila.get('descripcion','')}</span>",
                    unsafe_allow_html=True,
                )
            if len(activos) > 80:
                st.caption(f"… y {len(activos) - 80} más. Gestiona la selección abajo o en Sheets.")

    busqueda = st.text_input("Buscar en catálogo CPV", placeholder="forestal, 9072, veterinario…")
    if busqueda.strip():
        q = grefa_filter.normalize_text(busqueda).strip()
        coincidencias = [
            c for c in catalogo
            if q in grefa_filter.normalize_text(f"{c['codigo']} {c.get('descripcion','')}")
        ][:40]
        opciones = {
            f"{c['codigo']} · {c.get('descripcion','')[:60]}": c["codigo"] for c in coincidencias
        }
        elegidos = st.multiselect(
            "Seleccionar / activar CPV encontrados",
            options=list(opciones.keys()),
            default=[k for k, codigo in opciones.items() if any(
                c["codigo"] == codigo and c.get("activo") for c in catalogo
            )],
            key="cpv_picker",
        )
        if st.button("✅ Aplicar selección CPV", width="stretch"):
            elegidos_codigos = {opciones[k] for k in elegidos}
            mostrados = {c["codigo"] for c in coincidencias}
            for fila in catalogo:
                if fila["codigo"] in mostrados:
                    fila["activo"] = fila["codigo"] in elegidos_codigos
            _sincronizar_activos_desde_catalogos()
            guardar_criterios_en_sheets(silencioso=True)
            st.rerun()

    desactivar = st.multiselect(
        "Desactivar CPV activos",
        options=[f"{c['codigo']} · {c.get('descripcion','')[:40]}" for c in activos[:200]],
        key="cpv_off",
    )
    if desactivar and st.button("🗑️ Desactivar seleccionados", width="stretch", key="btn_cpv_off"):
        codigos = {item.split(" · ", 1)[0] for item in desactivar}
        for fila in catalogo:
            if fila["codigo"] in codigos:
                fila["activo"] = False
        _sincronizar_activos_desde_catalogos()
        guardar_criterios_en_sheets(silencioso=True)
        st.rerun()


def render_term_catalog() -> None:
    st.markdown("**Catálogo de términos**")
    catalogo: list[dict] = st.session_state["catalogo_terminos"]
    activos = [t for t in catalogo if t.get("activo")]
    st.caption(f"{len(activos)} conceptos activos · búsqueda en ES / EU / CA / GL")

    with st.expander("Términos activos", expanded=False):
        for termino in activos:
            st.markdown(
                f"<span class='chip'>{termino['castellano']}</span> "
                f"<span class='meta'>{termino.get('categoria','')}</span>",
                unsafe_allow_html=True,
            )

    busqueda = st.text_input(
        "Buscar término",
        placeholder="biodiversidad, ingurumena, ADIF…",
        key="term_search",
    )
    if busqueda.strip():
        q = grefa_filter.normalize_text(busqueda).strip()
        coincidencias = []
        for t in catalogo:
            blob = " ".join(
                [
                    t.get("castellano", ""),
                    t.get("euskera", ""),
                    t.get("catalan", ""),
                    t.get("gallego", ""),
                    t.get("categoria", ""),
                ]
            )
            if q in grefa_filter.normalize_text(blob):
                coincidencias.append(t)
        opciones = {t["castellano"]: t["castellano"] for t in coincidencias[:60]}
        elegidos = st.multiselect(
            "Activar términos encontrados",
            options=list(opciones.keys()),
            default=[t["castellano"] for t in coincidencias[:60] if t.get("activo")],
            key="term_picker",
        )
        if st.button("✅ Aplicar selección de términos", width="stretch"):
            elegidos_set = set(elegidos)
            mostrados = set(opciones.keys())
            for fila in catalogo:
                if fila["castellano"] in mostrados:
                    fila["activo"] = fila["castellano"] in elegidos_set
            _sincronizar_activos_desde_catalogos()
            guardar_criterios_en_sheets(silencioso=True)
            st.rerun()

    categorias = sorted({t.get("categoria", CUSTOM_KEYWORD_CATEGORY) for t in catalogo})
    if CUSTOM_KEYWORD_CATEGORY not in categorias:
        categorias.append(CUSTOM_KEYWORD_CATEGORY)

    with st.form("form_add_keyword", clear_on_submit=True):
        st.markdown("**Añadir concepto**")
        st.caption("Escribe en castellano, euskera, catalán o gallego; el resto se traduce solo.")
        termino_unico = st.text_input(
            "Término",
            placeholder="biodiversidad / biodibertsitatea / biodiversitat…",
        )
        castellano = st.text_input("Castellano (opcional si usas el campo de arriba)")
        euskera = st.text_input("Euskera (opcional)")
        catalan = st.text_input("Catalán (opcional)")
        gallego = st.text_input("Gallego (opcional)")
        categoria = st.selectbox("Categoría", categorias, index=len(categorias) - 1)
        if st.form_submit_button("➕ Añadir y activar", width="stretch"):
            if termino_unico.strip() and not any([castellano, euskera, catalan, gallego]):
                traducido = complete_from_any(termino_unico.strip())
            else:
                traducido = complete_term_translations(
                    castellano=castellano,
                    euskera=euskera,
                    catalan=catalan,
                    gallego=gallego,
                )
            canonico = traducido.get("castellano", "").strip()
            existentes = {t["castellano"].lower() for t in catalogo}
            if not canonico:
                st.warning("Escribe al menos un término.")
            elif canonico.lower() in existentes:
                st.info("Ese concepto ya está en el catálogo; actívalo desde la búsqueda.")
            else:
                catalogo.append(
                    {
                        **traducido,
                        "categoria": categoria,
                        "activo": True,
                    }
                )
                _sincronizar_activos_desde_catalogos()
                guardar_criterios_en_sheets(silencioso=True)
                st.success(
                    f"«{canonico}» añadido · EU: {traducido.get('euskera') or '—'} · "
                    f"CA: {traducido.get('catalan') or '—'} · GL: {traducido.get('gallego') or '—'}"
                )

    desactivar = st.multiselect(
        "Desactivar términos",
        options=[t["castellano"] for t in activos],
        key="term_off",
    )
    if desactivar and st.button("🗑️ Desactivar términos", width="stretch", key="btn_term_off"):
        objetivo = {t.lower() for t in desactivar}
        for fila in catalogo:
            if fila["castellano"].lower() in objetivo:
                fila["activo"] = False
        _sincronizar_activos_desde_catalogos()
        guardar_criterios_en_sheets(silencioso=True)
        st.rerun()

    if st.button("♻️ Restaurar catálogos por defecto", width="stretch"):
        st.session_state["catalogo_cpv"] = default_cpv_catalog()
        st.session_state["catalogo_terminos"] = default_term_catalog()
        _sincronizar_activos_desde_catalogos()
        guardar_criterios_en_sheets(silencioso=True)
        st.rerun()


# ---------------------------------------------------------------------------
# Pestañas
# ---------------------------------------------------------------------------
def pestana_oportunidades(oportunidades: pd.DataFrame, vista: str) -> None:
    if oportunidades.empty:
        st.info(
            "Ninguna licitación supera el umbral. Baja la relevancia mínima o ajusta CPV/términos."
        )
        return

    botones_exportacion(oportunidades, "oportunidades", permitir_sheets=True)

    if vista == "Tarjetas":
        total = len(oportunidades)
        if total > 5:
            tope = min(total, 60)
            a_mostrar = st.slider("Nº de tarjetas a mostrar", 5, tope, min(15, tope), step=5)
        else:
            a_mostrar = total
        for _, fila in oportunidades.head(a_mostrar).iterrows():
            tarjeta_licitacion(fila)
        if total > a_mostrar:
            st.caption(
                f"Mostrando {a_mostrar} de {total} oportunidades. "
                "Usa la vista de tabla o exporta el listado completo."
            )
    else:
        vista_tabla = tabla_para_mostrar(
            oportunidades,
            [
                "relevancia", "badge", "titulo", "organo_contratacion", "presupuesto_sin_iva",
                "ubicacion", "cpvs_texto", "keywords_match", "fecha_actualizacion", "estado", "url",
            ],
        )
        st.dataframe(
            vista_tabla,
            width="stretch",
            hide_index=True,
            column_config=CONFIG_COLUMNAS,
            height=560,
        )


def _anos_candidatos_desde_expediente(texto: str) -> list[int]:
    """Años a consultar en Drive: primero el actual, luego hacia atrás.

    El sufijo ``.25/`` de un ID (p. ej. ``3.25/20830.0288``) es solo una pista:
    muchos expedientes de 2025/2026 viven en la pestaña del año de publicación
    (a menudo el año en curso), no en Historico_2025.
    """
    import re

    ahora = datetime.now().year
    t = str(texto or "").strip()
    inferidos: list[int] = []
    for m in re.finditer(r"(20\d{2})", t):
        inferidos.append(int(m.group(1)))
    for m in re.finditer(r"\.(\d{2})/", t):
        yy = 2000 + int(m.group(1))
        if 2015 <= yy <= ahora + 1:
            inferidos.append(yy)

    # Orden: año actual → inferidos → resto hacia atrás hasta 2019
    out: list[int] = []
    for y in [ahora, *inferidos, *range(ahora - 1, 2018, -1)]:
        if 2019 <= y <= ahora + 1 and y not in out:
            out.append(y)
    return out or [ahora]


def _buscar_expediente_drive_por_años(
    consulta: str, años: list[int]
) -> tuple[pd.DataFrame, int | None, list[str]]:
    """Busca el expediente año a año (2026 → 2025 → …) hasta encontrarlo."""
    probados: list[str] = []
    try:
        sheets_historico.clear_worksheet_list_cache()
    except Exception:
        pass

    for year in años:
        probados.append(str(year))
        try:
            drive_df = sheets_historico.load_historico_dataframe(
                years=[year], include_legacy=False
            )
        except Exception as exc:
            msg = str(exc)
            if "429" in msg or "quota" in msg.lower():
                raise
            continue
        hit = _filtrar_por_expediente_seguro(drive_df, consulta)
        if not hit.empty:
            return hit, year, probados

    return empty_dataframe(), None, probados


def _filtrar_por_expediente_seguro(df: pd.DataFrame, consulta: str) -> pd.DataFrame:
    """Usa filter_by_expediente si existe; si no, coincidencia simple (Cloud cacheado)."""
    if df is None or df.empty or not str(consulta).strip():
        return empty_dataframe()
    if "expediente" not in df.columns:
        return empty_dataframe()
    filtrar = getattr(grefa_filter, "filter_by_expediente", None)
    if callable(filtrar):
        try:
            return filtrar(df, consulta)
        except Exception:
            pass
    q = str(consulta).strip().lower()
    serie = df["expediente"].fillna("").astype(str).str.lower()
    return df[serie.str.contains(q, regex=False, na=False)].reset_index(drop=True)


def _corpus_busqueda_pliegos(
    catalogo: pd.DataFrame | None,
    oportunidades: pd.DataFrame | None,
) -> tuple[pd.DataFrame, str]:
    """Une feed en sesión, catálogo puntuado, oportunidades e histórico Drive en caché."""
    partes: list[pd.DataFrame] = []
    notas: list[str] = []

    datos = st.session_state.get("datos")
    if isinstance(datos, pd.DataFrame) and not datos.empty:
        partes.append(datos)
        notas.append(f"feed vivo ({len(datos):,})")

    if catalogo is not None and isinstance(catalogo, pd.DataFrame) and not catalogo.empty:
        partes.append(catalogo)
        notas.append(f"catálogo ({len(catalogo):,})")

    if (
        oportunidades is not None
        and isinstance(oportunidades, pd.DataFrame)
        and not oportunidades.empty
    ):
        partes.append(oportunidades)

    if st.session_state.get("hist_drive_loaded") and sheets_store.is_configured():
        try:
            hoja_id = sheets_store.spreadsheet_id() or "default"
            years_key = str(st.session_state.get("hist_drive_years_key") or "")
            drive_df = _cargar_historico_drive_cached(hoja_id, years_key)
            if isinstance(drive_df, pd.DataFrame) and not drive_df.empty:
                partes.append(drive_df)
                notas.append(f"Drive caché ({len(drive_df):,})")
        except Exception:
            pass

    if not partes:
        return empty_dataframe(), "sin datos cargados"

    combinado = pd.concat(partes, ignore_index=True, sort=False)
    if "url" in combinado.columns:
        combinado = combinado.drop_duplicates(subset=["expediente", "url"], keep="first")
    else:
        combinado = combinado.drop_duplicates(subset=["expediente"], keep="first")
    return combinado.reset_index(drop=True), " + ".join(notas) if notas else f"{len(combinado):,} filas"


def pestana_analisis_pliegos(
    oportunidades: pd.DataFrame,
    catalogo: pd.DataFrame | None = None,
) -> None:
    st.subheader("Análisis de pliegos con IA")
    st.caption(
        "Localiza el expediente (feed + histórico Drive) y analiza PCAP + PPT "
        "con Gemini, o súbelos manualmente."
    )

    gemini_ok = pdf_summary.is_configured()
    if not gemini_ok:
        st.warning(
            "Gemini no está configurado. Puedes localizar el expediente, pero para "
            "analizar hace falta `[gemini] api_key` en Secrets "
            "([Google AI Studio](https://aistudio.google.com/apikey))."
        )

    expediente, url, titulo = "", "", ""
    documentos: list[dict] = []

    st.markdown("**1. Localizar expediente**")
    base_busqueda, origen_corpus = _corpus_busqueda_pliegos(catalogo, oportunidades)
    st.caption(f"Ámbito disponible: {origen_corpus}. La búsqueda solo se ejecuta al pulsar el botón.")

    col_q, col_btn = st.columns([3, 1])
    with col_q:
        st.text_input(
            "Buscar por ID de expediente",
            placeholder="Ej. 3.25/20830.0288",
            key="pliego_buscar_exp",
        )
    with col_btn:
        st.markdown("<br>", unsafe_allow_html=True)
        lanzar = st.button(
            "🔍 Buscar",
            key="pliego_btn_buscar",
            help="Feed + Drive (2026 → 2025 → …) hasta encontrarlo.",
            type="primary",
            width="stretch",
        )

    if lanzar:
        st.session_state["pliego_consulta_aplicada"] = str(
            st.session_state.get("pliego_buscar_exp") or ""
        ).strip()
        st.session_state.pop("pliego_hallados_drive", None)

    consulta = str(st.session_state.get("pliego_consulta_aplicada") or "").strip()
    hallados = empty_dataframe()

    if consulta:
        hallados = _filtrar_por_expediente_seguro(base_busqueda, consulta)
        cache_drive = st.session_state.get("pliego_hallados_drive") or {}
        if hallados.empty and cache_drive.get("q") == consulta and cache_drive.get("rows"):
            hallados = pd.DataFrame(cache_drive["rows"])
            if cache_drive.get("year"):
                st.caption(f"Encontrado en Drive · Historico_{cache_drive['year']} (caché).")
        elif hallados.empty and sheets_store.is_configured() and lanzar:
            años = _anos_candidatos_desde_expediente(consulta)
            with st.spinner(
                f"Buscando «{consulta}» en Drive: {años[0]} → …"
            ):
                try:
                    hallados, año_ok, probados = _buscar_expediente_drive_por_años(
                        consulta, años
                    )
                    if not hallados.empty:
                        st.session_state["pliego_hallados_drive"] = {
                            "q": consulta,
                            "year": año_ok,
                            "rows": hallados.to_dict(orient="records"),
                        }
                        st.success(
                            f"Encontrado en **Historico_{año_ok}** "
                            f"(probado: {' → '.join(probados)})."
                        )
                    else:
                        st.caption("Drive revisado: " + " → ".join(probados))
                except Exception as exc:
                    msg = str(exc)
                    if "429" in msg or "quota" in msg.lower():
                        st.warning("Cuota Sheets agotada. Espera 1 minuto y vuelve a buscar.")
                    else:
                        st.warning(f"Drive: {exc}")

        if hallados.empty:
            st.warning(
                f"Sin coincidencias para «{consulta}». "
                "Prueba de nuevo o sube los PDF a mano."
            )
        else:
            st.success(f"**{len(hallados)}** coincidencia(s) para «{consulta}».")
            _render_resultados_con_interes(hallados, clave_prefix="pliego", max_filas=15)

    opciones: list[tuple[str, str, str, str, str, list]] = []
    fuente_opciones = hallados if not hallados.empty else (
        oportunidades if isinstance(oportunidades, pd.DataFrame) and not oportunidades.empty
        else empty_dataframe()
    )
    if not fuente_opciones.empty:
        for _, fila in fuente_opciones.head(80).iterrows():
            exp = str(fila.get("expediente") or "—")
            tit = str(fila.get("titulo") or "")[:70]
            enlace = str(fila.get("url") or "")
            organo_fila = str(fila.get("organo_contratacion") or "")
            etiqueta = f"{exp} — {tit}" if tit else exp
            opciones.append(
                (
                    etiqueta,
                    exp,
                    enlace,
                    str(fila.get("titulo") or ""),
                    organo_fila,
                    _docs_desde_fila(fila),
                )
            )

    etiquetas = ["— Sin vincular / solo subir PDF —"] + [o[0] for o in opciones]
    idx_default = 1 if (consulta and opciones and not hallados.empty) else 0
    # Evitar ValueError de Streamlit si la opción guardada ya no existe.
    actual = st.session_state.get("pliego_select_exp")
    if st.session_state.get("_pliego_q_prev") != consulta or actual not in etiquetas:
        st.session_state["_pliego_q_prev"] = consulta
        st.session_state["pliego_select_exp"] = etiquetas[min(idx_default, len(etiquetas) - 1)]

    seleccion = st.selectbox(
        "Expediente a analizar",
        etiquetas,
        key="pliego_select_exp",
    )

    organo = ""
    if seleccion != etiquetas[0]:
        for etiqueta, exp, enlace, tit, organo_fila, docs in opciones:
            if etiqueta == seleccion:
                expediente, url, titulo, organo, documentos = (
                    exp,
                    enlace,
                    tit,
                    organo_fila,
                    docs,
                )
                break
    else:
        if consulta:
            expediente = consulta
        titulo = st.text_input(
            "Título / referencia (opcional)",
            key="pliego_titulo_libre",
        )
        organo = st.text_input(
            "Órgano / contratista (para carpeta Drive)",
            key="pliego_organo_libre",
            placeholder="Ej. Ayuntamiento de…",
        )

    if expediente or url:
        st.caption(
            f"Seleccionado: **{expediente or '—'}**"
            + (f" · {len(documentos)} documento(s) PLACSP" if documentos else " · sin enlaces de pliego en origen")
        )
        if sheets_store.is_configured():
            try:
                previo = sheets_store.load_pliego_resumen(expediente, url)
            except Exception:
                previo = None
            if previo:
                st.info("Ya hay un resumen guardado en Sheets para este expediente.")
                with st.expander("Ver resumen guardado"):
                    st.markdown(previo)

    st.markdown("**2. Documentos y análisis**")
    if gemini_ok:
        _widget_resumen_pliego(
            expediente,
            url,
            titulo,
            clave_prefix="tab_pliego",
            documentos=documentos,
        )
    else:
        st.info("Configura Gemini para generar el resumen IA.")

    st.markdown("**3. Checklist de documentación a presentar**")
    _widget_checklist_docs(
        expediente,
        url,
        titulo,
        clave_prefix="tab_pliego",
        organo=organo,
    )


def pestana_mis_licitaciones() -> None:
    st.subheader("Mis Licitaciones")
    st.caption(
        "Licitaciones que marcaste con ⭐ **Me interesa** en las búsquedas. "
        "Marca **Me presento** para preparar el checklist de documentación."
    )

    col_r, _ = st.columns([1, 3])
    with col_r:
        if st.button("🔄 Recargar", key="mis_lic_reload"):
            st.session_state["mis_licitaciones_cache"] = None
            st.rerun()

    filas = _cargar_mis_licitaciones_cache(forzar=False)
    if not filas:
        st.info(
            "Aún no hay licitaciones de interés. Busca en **Buscador** o **Histórico** "
            "y marca la estrella ⭐ de las que te interesen."
        )
        return

    presentarse = [f for f in filas if f.get("me_presento") == "sí"]
    st.markdown(
        f"**{len(filas)}** de interés · **{len(presentarse)}** con presentación prevista"
    )

    for idx, fila in enumerate(filas):
        clave = _clave_expediente(fila.get("expediente", ""), fila.get("url", ""))
        with st.container(border=True):
            c_chk, c_body = st.columns([0.12, 0.88])
            with c_chk:
                presento = st.checkbox(
                    "Me presento",
                    value=fila.get("me_presento") == "sí",
                    key=f"mis_presento_{idx}_{clave[:36]}",
                    help="Voy a presentar oferta: activa el checklist de documentación",
                )
            with c_body:
                st.markdown(
                    f"**{fila.get('expediente') or '—'}** — "
                    f"{str(fila.get('titulo') or '')[:120]}"
                )
                st.caption(
                    " · ".join(
                        x
                        for x in (
                            fila.get("organo") or "",
                            fila.get("estado") or "",
                            f"Relevancia {fila.get('relevancia')} %"
                            if fila.get("relevancia")
                            else "",
                        )
                        if x
                    )
                )
                if fila.get("url"):
                    st.markdown(f"[PLACSP ↗]({fila['url']})")

            if presento != (fila.get("me_presento") == "sí"):
                try:
                    if sheets_store.is_configured():
                        sheets_store.upsert_mi_licitacion(
                            fila.get("expediente", ""),
                            fila.get("url", ""),
                            titulo=fila.get("titulo", ""),
                            organo=fila.get("organo", ""),
                            presupuesto=fila.get("presupuesto", ""),
                            estado=fila.get("estado", ""),
                            relevancia=fila.get("relevancia", ""),
                            me_interesa=True,
                            me_presento=presento,
                        )
                    else:
                        fila["me_presento"] = "sí" if presento else "no"
                        st.session_state["mis_licitaciones_local"] = filas
                    st.session_state["mis_licitaciones_cache"] = None
                    if presento:
                        try:
                            sheets_store.ensure_checklist(
                                fila.get("expediente", ""),
                                fila.get("url", ""),
                                fila.get("titulo", ""),
                            )
                        except Exception:
                            pass
                    st.toast(
                        "Marcada para presentar." if presento else "Presentación desmarcada.",
                        icon="📝",
                    )
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

            if presento or fila.get("me_presento") == "sí":
                with st.expander("Checklist de documentación", expanded=True):
                    _widget_checklist_docs(
                        fila.get("expediente", ""),
                        fila.get("url", ""),
                        fila.get("titulo", ""),
                        clave_prefix=f"mismis_{idx}_{clave[:20]}",
                        organo=str(fila.get("organo") or ""),
                    )
                if pdf_summary.is_configured():
                    with st.expander("Análisis de pliegos (IA)"):
                        _widget_resumen_pliego(
                            fila.get("expediente", ""),
                            fila.get("url", ""),
                            fila.get("titulo", ""),
                            clave_prefix=f"mispliego_{idx}_{clave[:20]}",
                            documentos=[],
                        )

            if st.button("🗑️ Quitar de Mis Licitaciones", key=f"mis_del_{idx}_{clave[:36]}"):
                try:
                    _marcar_interes(
                        {
                            "expediente": fila.get("expediente", ""),
                            "url": fila.get("url", ""),
                            "titulo": fila.get("titulo", ""),
                            "organo_contratacion": fila.get("organo", ""),
                            "presupuesto_sin_iva": fila.get("presupuesto", ""),
                            "estado": fila.get("estado", ""),
                            "relevancia": fila.get("relevancia", ""),
                        },
                        interesa=False,
                    )
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))


def pestana_seguimiento() -> None:
    st.subheader("Seguimiento de expedientes")
    st.caption(
        "Pipeline del equipo sobre las oportunidades volcadas en Google Sheets. "
        "Los cambios se guardan en las columnas Seguimiento y Notas."
    )

    if not sheets_store.is_configured():
        st.info(
            "Configura Google Sheets en Secrets para usar el seguimiento compartido. "
            "Mientras tanto, exporta oportunidades con «Enviar a Google Sheets»."
        )
        return

    if st.button("🔄 Recargar desde Sheets", width="content"):
        st.session_state["seguimiento_cache"] = _cargar_seguimiento_cache()
        st.rerun()

    if not st.session_state.get("seguimiento_cache"):
        st.session_state["seguimiento_cache"] = _cargar_seguimiento_cache()

    filas = list(st.session_state["seguimiento_cache"].values())
    if not filas:
        st.info(
            "No hay oportunidades en la pestaña Oportunidades. "
            "Usa «Enviar a Google Sheets» desde la pestaña de oportunidades."
        )
        return

    conteo: dict[str, int] = {opt: 0 for opt in sheets_store.SEGUIMIENTO_OPTIONS}
    for fila in filas:
        estado = fila.get("seguimiento") or sheets_store.DEFAULT_TRACKING
        conteo[estado] = conteo.get(estado, 0) + 1

    cols = st.columns(len(sheets_store.SEGUIMIENTO_OPTIONS))
    for col, estado in zip(cols, sheets_store.SEGUIMIENTO_OPTIONS):
        col.metric(estado, conteo.get(estado, 0))

    filtro = st.multiselect(
        "Filtrar por estado",
        list(sheets_store.SEGUIMIENTO_OPTIONS),
        default=list(sheets_store.SEGUIMIENTO_OPTIONS),
    )

    filas_filtradas = [f for f in filas if f.get("seguimiento") in filtro]
    st.markdown(f"**{len(filas_filtradas)}** expedientes")

    for fila in filas_filtradas:
        clave = _clave_expediente(fila.get("expediente", ""), fila.get("url", ""))
        titulo = fila.get("titulo") or "(Sin título)"
        with st.container(border=True):
            st.markdown(f"**{fila.get('expediente') or '—'}** · {titulo[:100]}")
            meta = (
                f"Relevancia: {fila.get('relevancia') or '—'} % · "
                f"Categoría: {fila.get('categoria') or '—'} · "
                f"Detectado: {fila.get('fecha_deteccion') or '—'}"
            )
            st.caption(meta)
            if fila.get("url"):
                st.link_button("PLACSP ↗", fila["url"])

            c1, c2 = st.columns([1, 2])
            with c1:
                nuevo_estado = st.selectbox(
                    "Seguimiento",
                    sheets_store.SEGUIMIENTO_OPTIONS,
                    index=list(sheets_store.SEGUIMIENTO_OPTIONS).index(
                        fila.get("seguimiento") or sheets_store.DEFAULT_TRACKING
                    )
                    if (fila.get("seguimiento") or sheets_store.DEFAULT_TRACKING)
                    in sheets_store.SEGUIMIENTO_OPTIONS
                    else 0,
                    key=f"seg_{clave[:48]}",
                )
            with c2:
                nuevas_notas = st.text_area(
                    "Notas",
                    value=fila.get("notas") or "",
                    height=68,
                    key=f"notas_{clave[:48]}",
                )

            if st.button("💾 Guardar", key=f"guardar_{clave[:48]}"):
                try:
                    sheets_store.update_opportunity_tracking(
                        fila.get("expediente", ""),
                        fila.get("url", ""),
                        seguimiento=nuevo_estado,
                        notas=nuevas_notas,
                    )
                    st.session_state["seguimiento_cache"][clave]["seguimiento"] = nuevo_estado
                    st.session_state["seguimiento_cache"][clave]["notas"] = nuevas_notas
                    st.toast("Seguimiento actualizado.", icon="✅")
                except sheets_store.SheetsError as exc:
                    st.error(str(exc))

            if sheets_store.is_configured() and pdf_summary.is_configured():
                with st.expander("Resumen de pliego (ficha PLACSP)"):
                    _widget_resumen_pliego(
                        fila.get("expediente", ""),
                        fila.get("url", ""),
                        titulo,
                        clave_prefix=f"seg_{clave[:30]}",
                        documentos=_docs_desde_fila(fila) if hasattr(fila, "get") else [],
                    )
            if sheets_store.is_configured():
                with st.expander("Checklist documentación (Drive)"):
                    _widget_checklist_docs(
                        fila.get("expediente", ""),
                        fila.get("url", ""),
                        titulo,
                        clave_prefix=f"chkseg_{clave[:30]}",
                        organo=str(
                            fila.get("organo")
                            or fila.get("organo_contratacion")
                            or ""
                        ),
                    )


# Años posibles sin llamar a la API (evita 429). Al cargar se usan las pestañas que existan.
_ANOS_HISTORICO_UI = list(range(2019, 2027))


@st.cache_data(ttl=21600, show_spinner="Cargando histórico desde Google Drive…")
def _cargar_historico_drive_cached(
    spreadsheet_id: str, years_key: str = ""
) -> pd.DataFrame:
    """Cache larga (6 h) por hoja + años. Solo se invalida con el botón Cargar."""
    _ = spreadsheet_id
    years = [int(y) for y in years_key.split(",") if y.strip().isdigit()] or None
    try:
        return sheets_historico.load_historico_dataframe(
            years=years,
            include_legacy=not bool(years),
        )
    except TypeError:
        return sheets_historico.load_historico_dataframe()


def _combinar_fuentes_historico(
    puntuadas: pd.DataFrame,
    *,
    incluir_parquet: bool,
    drive_df: pd.DataFrame | None,
) -> pd.DataFrame:
    """Une feed vivo, Parquet local y pestañas Historico_YYYY de Drive."""
    partes: list[pd.DataFrame] = []
    if incluir_parquet and historico_placsp.is_available():
        partes.append(historico_placsp.load())
    if drive_df is not None and isinstance(drive_df, pd.DataFrame) and not drive_df.empty:
        partes.append(drive_df)
    if not puntuadas.empty:
        partes.append(puntuadas)

    if not partes:
        return empty_dataframe()
    if len(partes) == 1:
        combinado = partes[0].copy()
    else:
        combinado = pd.concat(partes, ignore_index=True, sort=False)
        if "url" in combinado.columns:
            combinado = combinado.drop_duplicates(subset=["expediente", "url"], keep="first")
        else:
            combinado = combinado.drop_duplicates(subset=["expediente"], keep="first")

    try:
        return grefa_filter.with_nivel_administracion(combinado.reset_index(drop=True))
    except Exception:
        return combinado.reset_index(drop=True)


def pestana_historico_nif(puntuadas: pd.DataFrame) -> None:
    """Pestaña de histórico; nunca debe tumbar el resto de la app."""
    try:
        _pestana_historico_nif_body(puntuadas if puntuadas is not None else empty_dataframe())
    except Exception as exc:
        st.error(
            "Error en la pestaña Histórico (la app sigue usable en el resto de pestañas). "
            f"{type(exc).__name__}: {exc or '(sin mensaje)'}."
        )


def _pestana_historico_nif_body(puntuadas: pd.DataFrame) -> None:
    from modules import historico_local

    st.subheader("Histórico y búsqueda avanzada")
    st.caption(
        "La búsqueda usa un **fichero local** (Parquet): sin cuota de Google Sheets. "
        "Filtra por ID expediente, NIF de órgano/adjudicatario o ámbito."
    )

    # ── Fuente principal: Parquet local (0 lecturas Sheets) ──
    local_df: pd.DataFrame | None = None
    if historico_local.is_available():
        años_local = st.multiselect(
            "Años (fichero local)",
            options=_ANOS_HISTORICO_UI,
            default=list(historico_local.metadata().get("años") or [2025, 2026]),
            key="hist_anos_local",
            help="Filtro sobre data/historico_grefa.parquet (sin llamar a Google).",
        )
        try:
            local_df = historico_local.load(years=años_local or None)
            con_adj = (
                int((local_df["nif_adjudicatario"].astype(str).str.strip() != "").sum())
                if not local_df.empty and "nif_adjudicatario" in local_df.columns
                else 0
            )
            st.success(
                f"{historico_local.resumen()} · cargadas **{len(local_df):,}** "
                f"({con_adj:,} con NIF adjudicatario)."
            )
        except Exception as exc:
            st.warning(f"No se pudo leer el fichero local: {exc}")
            local_df = None
    else:
        st.warning(
            "No hay fichero local (`data/historico_grefa.parquet`). "
            "Genéralo en el servidor con:\n\n"
            "`python -u scripts/build_historico_local.py --from-sheets --from-year 2021 --to-year 2026`\n\n"
            "o desde ZIPs PLACSP (sin Sheets):\n\n"
            "`python -u scripts/build_historico_local.py --from-year 2021 --to-year 2026 --skip-download`"
        )

    drive_df: pd.DataFrame | None = None
    incluir_drive = False
    incluir_vivo = False
    incluir_parquet_legado = False

    with st.expander("Fuentes opcionales (consumen cuota si usas Drive)", expanded=False):
        drive_disponible = sheets_store.is_configured()
        col_drive, col_vivo = st.columns(2)
        with col_drive:
            if drive_disponible:
                años_sel = st.multiselect(
                    "Años (pestañas Drive)",
                    options=_ANOS_HISTORICO_UI,
                    default=[2026],
                    key="hist_anos",
                    help="Solo si falta el Parquet. Cada año = lecturas API.",
                )
                cargar = st.button("📥 Cargar Drive", key="hist_cargar_drive")
                if cargar:
                    years_key = ",".join(str(y) for y in sorted(años_sel)) if años_sel else ""
                    st.session_state["hist_drive_years_key"] = years_key
                    try:
                        sheets_historico.clear_worksheet_list_cache()
                        _cargar_historico_drive_cached.clear()
                    except Exception:
                        pass
                    st.session_state["hist_drive_loaded"] = True
                incluir_drive = bool(st.session_state.get("hist_drive_loaded"))
                if incluir_drive:
                    hoja_id = sheets_store.spreadsheet_id() or "default"
                    years_key = st.session_state.get("hist_drive_years_key") or ",".join(
                        str(y) for y in sorted(años_sel)
                    )
                    try:
                        drive_df = _cargar_historico_drive_cached(hoja_id, years_key)
                        st.caption(f"Drive: {len(drive_df):,} filas ({years_key}).")
                    except Exception as exc:
                        st.warning(f"Drive: {exc}")
                        drive_df = None
                        incluir_drive = False
            else:
                st.caption("Sheets no configurado.")
        with col_vivo:
            incluir_vivo = st.checkbox(
                "Incluir feed en vivo", value=False, key="hist_incluir_vivo"
            )
            if historico_placsp.is_available():
                incluir_parquet_legado = st.checkbox(
                    "Parquet PLACSP legado", value=False, key="hist_incluir_parquet"
                )
            else:
                incluir_parquet_legado = False

    col_exp, col_nif = st.columns([2, 2])
    with col_exp:
        expediente = st.text_input(
            "ID Expediente",
            placeholder="Ej. 2024/001234… (también busca en la URL PLACSP)",
            key="hist_exp",
        )
    with col_nif:
        nif = st.text_input("NIF", placeholder="Ej. B12345678…", key="hist_nif")

    col_ambito_nif, col_ambito_admin = st.columns([1, 2])
    with col_ambito_nif:
        ambito_etiqueta = st.selectbox(
            "Buscar NIF en",
            ["Ambos", "Órgano de contratación", "Adjudicatario"],
            key="hist_nif_ambito",
        )
    with col_ambito_admin:
        niveles_admin = st.multiselect(
            "Ámbito del órgano",
            [NIVEL_NACIONAL, NIVEL_AUTONOMICO, NIVEL_LOCAL, NIVELES_ADMIN[-1]],
            default=list(NIVELES_ADMIN),
            key="hist_niveles",
            help="Si buscas por NIF o ID expediente, este filtro no se aplica.",
        )

    texto = st.text_input("Texto libre (opcional)", placeholder="Título, CPV…", key="hist_texto")

    if st.button("🔍 Buscar", key="hist_btn_buscar", type="primary"):
        st.session_state["hist_filtros_aplicados"] = {
            "expediente": (expediente or "").strip(),
            "nif": (nif or "").strip(),
            "nif_ambito": {
                "Ambos": "ambos",
                "Órgano de contratación": "organo",
                "Adjudicatario": "adjudicatario",
            }.get(ambito_etiqueta, "ambos"),
            "niveles_admin": list(niveles_admin),
            "texto": (texto or "").strip(),
            "incluir_vivo": incluir_vivo,
            "incluir_parquet": incluir_parquet_legado,
            "incluir_drive": incluir_drive,
            "incluir_local": True,
            "years_key": st.session_state.get("hist_drive_years_key") or "",
            "_probe_drive": False,
        }

    aplicados = st.session_state.get("hist_filtros_aplicados")
    if not aplicados:
        st.info("Elige filtros y pulsa **Buscar**. Se consulta el fichero local (sin Sheets).")
        return

    partes: list[pd.DataFrame] = []
    if aplicados.get("incluir_local", True) and local_df is not None and not local_df.empty:
        partes.append(local_df)
    base_extra = _combinar_fuentes_historico(
        puntuadas if aplicados.get("incluir_vivo") else empty_dataframe(),
        incluir_parquet=bool(aplicados.get("incluir_parquet")),
        drive_df=drive_df if aplicados.get("incluir_drive") else None,
    )
    if base_extra is not None and not base_extra.empty:
        partes.append(base_extra)
    if not partes:
        st.warning("No hay datos locales ni fuentes opcionales cargadas.")
        return
    base = partes[0] if len(partes) == 1 else pd.concat(partes, ignore_index=True, sort=False)
    if "url" in base.columns:
        base = base.drop_duplicates(subset=["expediente", "url"], keep="first")
    else:
        base = base.drop_duplicates(subset=["expediente"], keep="first")
    base = base.reset_index(drop=True)

    resultados = grefa_filter.search_dataframe(
        base,
        texto=str(aplicados.get("texto") or ""),
        nif=str(aplicados.get("nif") or ""),
        nif_ambito=str(aplicados.get("nif_ambito") or "ambos"),
        expediente=str(aplicados.get("expediente") or ""),
        niveles_admin=aplicados.get("niveles_admin"),
    )

    # Si buscan por expediente y no está en la base cargada → Drive año a año (solo al pulsar Buscar).
    q_exp = str(aplicados.get("expediente") or "").strip()
    if (
        q_exp
        and resultados.empty
        and sheets_store.is_configured()
        and aplicados.pop("_probe_drive", False)
    ):
        st.session_state["hist_filtros_aplicados"] = aplicados
        años = _anos_candidatos_desde_expediente(q_exp)
        with st.spinner(f"Buscando expediente en Drive ({años[0]} → …)…"):
            try:
                hallados, año_ok, probados = _buscar_expediente_drive_por_años(q_exp, años)
                if not hallados.empty:
                    resultados = hallados
                    st.session_state["hist_resultados_drive"] = {
                        "q": q_exp,
                        "rows": hallados.to_dict(orient="records"),
                    }
                    st.success(
                        f"Encontrado en Historico_{año_ok} (probado: {' → '.join(probados)})."
                    )
                else:
                    st.caption("Drive revisado: " + " → ".join(probados))
            except Exception as exc:
                st.warning(f"Drive: {exc}")
    elif q_exp and resultados.empty:
        cache = st.session_state.get("hist_resultados_drive") or {}
        if cache.get("q") == q_exp and cache.get("rows"):
            resultados = pd.DataFrame(cache["rows"])

    st.markdown(f"**{len(resultados):,}** expedientes encontrados.")
    if resultados.empty:
        st.warning(
            "Sin coincidencias en el fichero local. Revisa NIF/expediente o regenera el Parquet. "
            "El histórico GREFA solo incluye Alta/Media."
        )
        return

    botones_exportacion(resultados, "historico_nif")
    _render_resultados_con_interes(resultados, clave_prefix="hist")

    columnas = [
        "expediente", "titulo", "organo_contratacion", "nivel_administracion", "nif_organo",
        "adjudicatario", "nif_adjudicatario", "estado", "presupuesto_sin_iva",
        "ubicacion", "fecha_actualizacion", "fecha_snapshot", "url",
    ]
    if "relevancia" in resultados.columns and resultados["relevancia"].notna().any():
        columnas = ["relevancia", "categoria"] + columnas

    vista_tabla = tabla_para_mostrar(resultados, [c for c in columnas if c in resultados.columns])
    with st.expander("Tabla completa", expanded=False):
        st.dataframe(
            vista_tabla,
            width="stretch",
            hide_index=True,
            column_config=CONFIG_COLUMNAS,
            height=420,
        )


def pestana_buscador(df: pd.DataFrame) -> None:
    st.subheader("Buscador general PLACSP")
    st.caption(
        "Configura los filtros y pulsa **Buscar**. "
        "Si indicas un ID de expediente, también se consulta el histórico Drive (2026→2025…)."
    )

    importes = df["presupuesto_sin_iva"].dropna()
    tope = float(importes.max()) if not importes.empty else 0.0

    ubicaciones_disponibles = sorted({u for u in df["ubicacion"].unique() if u})
    col_exp, col_admin = st.columns([2, 2])
    with col_exp:
        st.text_input(
            "ID Expediente",
            placeholder="Búsqueda directa por código de licitación",
            key="buscador_exp",
            help="Si rellenas el ID, se ignoran ámbito, ubicación e importe.",
        )
    with col_admin:
        st.multiselect(
            "Ámbito del órgano",
            [NIVEL_NACIONAL, NIVEL_AUTONOMICO, NIVEL_LOCAL, NIVELES_ADMIN[-1]],
            default=[NIVEL_NACIONAL, NIVEL_AUTONOMICO, NIVEL_LOCAL],
            key="buscador_niveles",
        )

    st.multiselect("Ubicación / Provincia", ubicaciones_disponibles, key="buscador_ubicaciones")

    estados_globales = st.session_state.get("estados_aplicados") or None
    if estados_globales:
        st.caption(f"Estados aplicados (barra superior): {', '.join(estados_globales)}")

    busqueda = (st.session_state.get("busqueda_aplicada") or "").strip()
    if busqueda:
        st.caption(f"Búsqueda libre activa: «{busqueda}»")

    if tope > 0:
        st.slider(
            "Rango de presupuesto sin IVA (€)",
            min_value=0.0,
            max_value=tope,
            value=(0.0, tope),
            step=max(tope / 200, 1.0),
            format="%.0f",
            key="buscador_rango",
        )
        st.checkbox(
            "Incluir licitaciones sin presupuesto publicado",
            value=True,
            key="buscador_sin_importe",
        )
    else:
        st.caption("El feed descargado no incluye importes; el filtro de presupuesto está desactivado.")

    if st.button("🔍 Buscar", key="buscador_btn_buscar", type="primary"):
        rango = st.session_state.get("buscador_rango") or (None, None)
        st.session_state["buscador_filtros_aplicados"] = {
            "expediente": str(st.session_state.get("buscador_exp") or "").strip(),
            "niveles_admin": list(st.session_state.get("buscador_niveles") or []),
            "ubicaciones": list(st.session_state.get("buscador_ubicaciones") or []),
            "presupuesto_min": rango[0] if isinstance(rango, (list, tuple)) else None,
            "presupuesto_max": rango[1] if isinstance(rango, (list, tuple)) else None,
            "incluir_sin_presupuesto": bool(
                st.session_state.get("buscador_sin_importe", True)
            ),
            "_probe_drive": True,
        }

    aplicados = st.session_state.get("buscador_filtros_aplicados")
    if not aplicados:
        st.info("Configura filtros y pulsa **Buscar**.")
        return

    resultados = grefa_filter.search_dataframe(
        df,
        presupuesto_min=aplicados.get("presupuesto_min"),
        presupuesto_max=aplicados.get("presupuesto_max"),
        ubicaciones=aplicados.get("ubicaciones") or None,
        incluir_sin_presupuesto=bool(aplicados.get("incluir_sin_presupuesto", True)),
        expediente=str(aplicados.get("expediente") or ""),
        niveles_admin=aplicados.get("niveles_admin"),
    )

    q_exp = str(aplicados.get("expediente") or "").strip()
    if (
        q_exp
        and resultados.empty
        and sheets_store.is_configured()
        and aplicados.pop("_probe_drive", False)
    ):
        st.session_state["buscador_filtros_aplicados"] = aplicados
        años = _anos_candidatos_desde_expediente(q_exp)
        with st.spinner(f"No está en el feed vivo; buscando en Drive ({años[0]} → …)…"):
            try:
                hallados, año_ok, probados = _buscar_expediente_drive_por_años(q_exp, años)
                if not hallados.empty:
                    resultados = hallados
                    st.session_state["busc_resultados_drive"] = {
                        "q": q_exp,
                        "rows": hallados.to_dict(orient="records"),
                    }
                    st.success(
                        f"Encontrado en Historico_{año_ok} (probado: {' → '.join(probados)})."
                    )
            except Exception as exc:
                st.warning(f"Drive: {exc}")
    elif q_exp and resultados.empty:
        cache = st.session_state.get("busc_resultados_drive") or {}
        if cache.get("q") == q_exp and cache.get("rows"):
            resultados = pd.DataFrame(cache["rows"])

    st.markdown(f"**{len(resultados)}** licitaciones coinciden con los filtros.")
    botones_exportacion(resultados, "busqueda")

    if resultados.empty:
        st.info("Sin coincidencias. Prueba otro ID, carga más páginas del feed o Drive.")
        return

    _render_resultados_con_interes(resultados, clave_prefix="busc")

    vista_tabla = tabla_para_mostrar(
        resultados,
        [
            "relevancia", "categoria", "expediente", "titulo", "organo_contratacion",
            "nivel_administracion", "presupuesto_sin_iva", "ubicacion", "tipo_contrato", "cpvs_texto",
            "fecha_actualizacion", "fecha_limite", "estado", "url",
        ],
    )
    with st.expander("Tabla completa", expanded=False):
        st.dataframe(
            vista_tabla,
            width="stretch",
            hide_index=True,
            column_config=CONFIG_COLUMNAS,
            height=420,
        )


# ---------------------------------------------------------------------------
# Aplicación
# ---------------------------------------------------------------------------
def main() -> None:
    if not st.session_state.get("_modulos_criticos_reloaded"):
        _recargar_modulos_criticos()
        st.session_state["_modulos_criticos_reloaded"] = True

    usuario = auth.requiere_acceso()

    # Los criterios compartidos mandan sobre los valores por defecto.
    if not st.session_state["sheets_sincronizado"]:
        cargar_criterios_de_sheets(inicial=True)

    necesita_carga = st.session_state.get("cargando_datos") or (
        st.session_state["datos"] is None and not st.session_state["error_descarga"]
    )
    if necesita_carga:
        cargar_datos_con_indicador()

    sidebar_fuente_datos()
    sidebar_google_sheets()
    auth.barra_usuario(usuario)

    datos = st.session_state["datos"]
    if datos is None:
        datos = empty_dataframe()

    if st.session_state["error_descarga"]:
        st.error(st.session_state["error_descarga"])
        st.info(
            "Si la red corporativa bloquea contrataciondelestado.es, descarga el fichero "
            ".atom manualmente y súbelo desde «Cargar fichero ATOM local» en la barra lateral."
        )

    _sincronizar_activos_desde_catalogos()
    cpvs_activos = list(st.session_state["cpvs"].keys())
    keywords_activas = flatten_keywords(st.session_state["keywords"])
    conceptos_activos = [t for t in st.session_state["catalogo_terminos"] if t.get("activo")]
    puntuadas_todas = grefa_filter.score_licitaciones(
        datos,
        cpvs_activos,
        keywords_activas,
        conceptos=conceptos_activos,
    )
    # Filtros de estado/fecha solo para oportunidades/buscador; el histórico
    # necesita también Adjudicada/Resuelta (p. ej. licitaciones ya ganadas).
    puntuadas = grefa_filter.filter_by_estado(
        puntuadas_todas, st.session_state.get("estados_aplicados") or None
    )

    usar_fechas = bool(st.session_state.get("usar_fechas_aplicado", False))
    puntuadas = aplicar_filtros_globales(
        puntuadas,
        texto=str(st.session_state.get("busqueda_aplicada") or ""),
        fecha_campo=str(st.session_state.get("fecha_campo_aplicado") or "fecha_actualizacion"),
        fecha_desde=st.session_state.get("fecha_desde_aplicada") if usar_fechas else None,
        fecha_hasta=st.session_state.get("fecha_hasta_aplicada") if usar_fechas else None,
        incluir_sin_fecha=bool(st.session_state.get("incluir_sin_fecha_aplicado", True)),
    )

    resumen = grefa_filter.summarize(puntuadas)

    if sheets_store.is_configured() and not puntuadas.empty:
        forzar_sync = bool(st.session_state.pop("_forzar_sync_diaria", False))
        # Evita leer Config/Sheets en cada rerun si ya sabemos que la sync de hoy pasó.
        if forzar_sync or not st.session_state.get("_sync_omitida_hoy"):
            sync = daily_sync.run_daily_sync(puntuadas, forzar=forzar_sync)
            st.session_state["ultimo_sync"] = sync.resumen()
            if sync.ejecutado or (sync.omitido and "ya ejecutada" in (sync.motivo or "")):
                st.session_state["_sync_omitida_hoy"] = True
            if sync.ejecutado:
                st.session_state.pop("_ultima_sync_hora_ui", None)
            if sync.ejecutado or (forzar_sync and not sync.omitido):
                st.toast(st.session_state["ultimo_sync"], icon="📗")
            elif forzar_sync and sync.omitido:
                st.toast(st.session_state["ultimo_sync"], icon="ℹ️")

    oportunidades, vista = panel_control_superior(
        datos, puntuadas, resumen, len(cpvs_activos), len(conceptos_activos)
    )

    if sheets_store.is_configured() and not st.session_state.get("seguimiento_cache"):
        st.session_state["seguimiento_cache"] = _cargar_seguimiento_cache()

    if puntuadas.empty:
        st.warning("No hay datos cargados. Pulsa «Actualizar datos ahora» en la barra lateral.")

    pestana_1, pestana_2, pestana_3, pestana_4, pestana_5, pestana_6 = st.tabs(
        [
            "🎯 Oportunidades GREFA",
            "🔎 Buscador General PLACSP",
            "🗂️ Histórico y NIF",
            "⭐ Mis Licitaciones",
            "📄 Análisis de pliegos",
            "📋 Seguimiento",
        ]
    )
    with pestana_1:
        if puntuadas.empty:
            st.info("Carga licitaciones para ver oportunidades GREFA.")
        else:
            pestana_oportunidades(oportunidades, vista)
    with pestana_2:
        if puntuadas_todas.empty:
            st.info("Carga licitaciones para usar el buscador.")
        else:
            pestana_buscador(puntuadas_todas)
    with pestana_3:
        try:
            pestana_historico_nif(puntuadas_todas)
        except Exception as exc:
            st.error(f"Histórico no disponible ahora: {type(exc).__name__}")
    with pestana_4:
        pestana_mis_licitaciones()
    with pestana_5:
        pestana_analisis_pliegos(oportunidades, catalogo=puntuadas_todas)
    with pestana_6:
        pestana_seguimiento()

    st.divider()
    st.caption(
        "Datos públicos de la Plataforma de Contratación del Sector Público (contrataciondelestado.es). "
        "El Índice de Relevancia GREFA es una estimación automática: revisa siempre el pliego original."
    )


if __name__ == "__main__":
    main()
