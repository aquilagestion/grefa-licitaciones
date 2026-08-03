"""GREFA · Monitor de licitaciones públicas (PLACSP).

Interfaz Streamlit para descargar el feed ATOM de la Plataforma de Contratación
del Sector Público, puntuar cada expediente con el Índice de Relevancia GREFA y
gestionar los criterios de búsqueda (CPV y palabras clave) en caliente.

Ejecución:  streamlit run app.py
"""

from __future__ import annotations

import importlib
import sys
from datetime import datetime
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
from modules import auth, grefa_filter, sheets_catalog, sheets_store  # noqa: E402
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
    .bloque-titulo { padding: 0.2rem 0 1rem 0; }
    .bloque-titulo h1 { margin-bottom: 0.1rem; font-size: 2rem; }
    .bloque-titulo p { color: #5b6b62; margin: 0; }
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
    div[data-testid="stMetricValue"] { font-size: 1.55rem; }
    /* Barra superior de criterios (~10 % de pantalla) */
    .barra-criterios-flag { display: none; }
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.barra-criterios-flag) {
        max-height: min(10vh, 76px);
        overflow: hidden;
        margin-bottom: 0.35rem;
        padding-top: 0.15rem;
        padding-bottom: 0.15rem;
    }
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.barra-criterios-flag) [data-testid="stHorizontalBlock"] {
        gap: 0.4rem;
        align-items: center;
    }
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.barra-criterios-flag) button[kind="secondary"] {
        min-height: 2.1rem !important;
        padding: 0.25rem 0.55rem !important;
        font-size: 0.82rem !important;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    div[data-testid="stPopoverBody"] {
        max-height: min(70vh, 520px);
        overflow-y: auto;
    }
    div[data-testid="stPopoverBody"] h3, div[data-testid="stPopoverBody"] h2 {
        font-size: 0.95rem;
        margin: 0 0 0.35rem 0;
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
        "max_pages": 3,
        "max_entries": 1500,
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
        "usar_fechas_aplicado": False,
        "fecha_campo_aplicado": "fecha_actualizacion",
        "fecha_desde_aplicada": None,
        "fecha_hasta_aplicada": None,
        "incluir_sin_fecha_aplicado": True,
    }
    for clave, valor in valores_iniciales.items():
        st.session_state.setdefault(clave, valor)


def _sincronizar_activos_desde_catalogos() -> None:
    st.session_state["cpvs"] = active_cpvs(st.session_state["catalogo_cpv"])
    st.session_state["keywords"] = active_keywords_grouped(st.session_state["catalogo_terminos"])


init_state()


def _recargar_grefa_filter() -> None:
    """Fuerza la recarga del módulo (Streamlit Cloud puede cachear código antiguo)."""
    import modules.grefa_filter as modulo

    importlib.reload(modulo)
    sys.modules["modules.grefa_filter"] = modulo
    globals()["grefa_filter"] = modulo


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
        with st.spinner("Descargando licitaciones de la PLACSP…"):
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


# ---------------------------------------------------------------------------
# Barra superior: criterios de búsqueda (CPV, términos, estado)
# ---------------------------------------------------------------------------
def _etiqueta_estados(estados: list[str] | None, max_chars: int = 28) -> str:
    if not estados:
        return "todos"
    texto = ", ".join(estados)
    return texto if len(texto) <= max_chars else texto[: max_chars - 1] + "…"


def barra_criterios_superior(df: pd.DataFrame) -> None:
    """CPV, términos y filtro de estado en una franja compacta bajo el título."""
    catalogo_cpv: list[dict] = st.session_state["catalogo_cpv"]
    catalogo_terminos: list[dict] = st.session_state["catalogo_terminos"]
    n_cpv = sum(1 for c in catalogo_cpv if c.get("activo"))
    n_terms = sum(1 for t in catalogo_terminos if t.get("activo"))
    estados_sel = st.session_state.get("estados_aplicados") or []

    with st.container(border=True):
        st.markdown('<span class="barra-criterios-flag"></span>', unsafe_allow_html=True)
        col_cpv, col_terms, col_estado = st.columns(3)

        with col_cpv:
            with st.popover(f"🏷️ CPV · {n_cpv} activos", width="stretch"):
                render_cpv_catalog()

        with col_terms:
            with st.popover(f"🔍 Términos · {n_terms} activos", width="stretch"):
                render_term_catalog()

        with col_estado:
            etiqueta = _etiqueta_estados(estados_sel)
            with st.popover(f"📋 Estado · {etiqueta}", width="stretch"):
                render_filtro_estado(df)


def _rango_fechas_disponible(df: pd.DataFrame, campo: str) -> tuple:
    """Devuelve (min, max) como date para el date_input de Streamlit."""
    from datetime import date

    if df.empty or campo not in df.columns:
        hoy = date.today()
        return hoy, hoy
    fechas = pd.to_datetime(df[campo], errors="coerce").dropna()
    if fechas.empty:
        hoy = date.today()
        return hoy, hoy
    return fechas.min().date(), fechas.max().date()


def _limpiar_filtros_busqueda() -> None:
    st.session_state["busqueda_aplicada"] = ""
    st.session_state["usar_fechas_aplicado"] = False
    st.session_state["fecha_campo_aplicado"] = "fecha_actualizacion"
    st.session_state["fecha_desde_aplicada"] = None
    st.session_state["fecha_hasta_aplicada"] = None
    st.session_state["incluir_sin_fecha_aplicado"] = True
    st.session_state["filtro_estados"] = list(ESTADOS_ABIERTOS_DEFAULT)
    st.session_state["estados_aplicados"] = list(ESTADOS_ABIERTOS_DEFAULT)


def _resumen_filtros_aplicados() -> None:
    partes: list[str] = []
    texto = (st.session_state.get("busqueda_aplicada") or "").strip()
    if texto:
        partes.append(f"texto «{texto}»")
    estados = st.session_state.get("estados_aplicados") or []
    if estados:
        partes.append(f"estado: {', '.join(estados)}")
    if st.session_state.get("usar_fechas_aplicado"):
        campo = st.session_state.get("fecha_campo_aplicado", "fecha_actualizacion")
        etiqueta = "actualización" if campo == "fecha_actualizacion" else "límite presentación"
        desde = st.session_state.get("fecha_desde_aplicada")
        hasta = st.session_state.get("fecha_hasta_aplicada")
        if desde and hasta:
            partes.append(f"fechas ({etiqueta}): {desde:%d/%m/%Y} – {hasta:%d/%m/%Y}")
    if partes:
        st.caption("Filtros activos: " + " · ".join(partes))
    else:
        st.caption("Sin filtros de búsqueda activos. Pulsa «Buscar» para aplicar.")


def barra_busqueda_filtros(df: pd.DataFrame) -> None:
    """Búsqueda libre y filtro por fechas; se aplican al pulsar «Buscar»."""
    campo_def = st.session_state.get("fecha_campo_aplicado", "fecha_actualizacion")
    min_d, max_d = _rango_fechas_disponible(df, campo_def)
    desde_def = st.session_state.get("fecha_desde_aplicada") or min_d
    hasta_def = st.session_state.get("fecha_hasta_aplicada") or max_d

    with st.container(border=True):
        with st.form("form_busqueda_global", clear_on_submit=False):
            col_texto, col_fechas_toggle = st.columns([4, 1])
            with col_texto:
                texto = st.text_input(
                    "Búsqueda libre",
                    value=st.session_state.get("busqueda_aplicada", ""),
                    placeholder=(
                        "Cualquier término en título, descripción, expediente, CPV, ubicación… "
                        "(sin añadirlo al catálogo)"
                    ),
                )
            with col_fechas_toggle:
                usar_fechas = st.checkbox(
                    "Filtrar por fechas",
                    value=bool(st.session_state.get("usar_fechas_aplicado", False)),
                )

            fc1, fc2, fc3, fc4 = st.columns([1.4, 1, 1, 1.2])
            with fc1:
                fecha_campo = st.selectbox(
                    "Campo de fecha",
                    ["fecha_actualizacion", "fecha_limite"],
                    index=0 if campo_def == "fecha_actualizacion" else 1,
                    format_func=lambda x: (
                        "Fecha de actualización" if x == "fecha_actualizacion" else "Límite de presentación"
                    ),
                )
            with fc2:
                fecha_desde = st.date_input("Desde", value=desde_def, min_value=min_d, max_value=max_d)
            with fc3:
                fecha_hasta = st.date_input("Hasta", value=hasta_def, min_value=min_d, max_value=max_d)
            with fc4:
                incluir_sin_fecha = st.checkbox(
                    "Incluir sin fecha",
                    value=bool(st.session_state.get("incluir_sin_fecha_aplicado", True)),
                )

            st.caption(
                "El estado (popover superior) y el texto/fechas se aplican juntos al pulsar «Buscar»."
            )
            col_buscar, col_limpiar, _ = st.columns([1, 1, 3])
            with col_buscar:
                buscar = st.form_submit_button("🔍 Buscar", type="primary", width="stretch")
            with col_limpiar:
                limpiar = st.form_submit_button("Limpiar filtros", width="stretch")

        if buscar:
            st.session_state["busqueda_aplicada"] = texto.strip()
            st.session_state["usar_fechas_aplicado"] = usar_fechas
            st.session_state["fecha_campo_aplicado"] = fecha_campo
            st.session_state["fecha_desde_aplicada"] = fecha_desde
            st.session_state["fecha_hasta_aplicada"] = fecha_hasta
            st.session_state["incluir_sin_fecha_aplicado"] = incluir_sin_fecha
            st.session_state["estados_aplicados"] = list(st.session_state.get("filtro_estados") or [])
            st.rerun()

        if limpiar:
            _limpiar_filtros_busqueda()
            st.rerun()

        _resumen_filtros_aplicados()


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
        st.slider("Máximo de expedientes", 100, 5000, step=100, key="max_entries")
        st.caption(
            "Si la URL principal no responde, se prueban automáticamente las "
            "sindicaciones oficiales alternativas de contrataciondelestado.es."
        )

    if st.sidebar.button("🔁 Actualizar datos ahora", type="primary", width="stretch"):
        st.session_state["refresh_token"] += 1
        actualizar_datos()
        st.rerun()

    with st.sidebar.expander("Cargar fichero ATOM local"):
        fichero = st.file_uploader("Archivo .atom / .xml", type=["atom", "xml"], key="uploader")
        if fichero is not None and st.button("Procesar fichero", width="stretch"):
            try:
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
                "La app crea sola las pestañas `CPV`, `PalabrasClave` y `Oportunidades`."
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


def render_filtro_estado(df: pd.DataFrame) -> None:
    """Filtro global por estado PLACSP (persiste en la sesión)."""
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
        st.caption("Sin filtro de estado (se muestran todos). Se aplica al pulsar «Buscar».")
    else:
        st.caption(f"{len(seleccion)} estado(s) seleccionado(s). Se aplicará al pulsar «Buscar».")


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
def pestana_oportunidades(df: pd.DataFrame) -> None:
    st.subheader("Oportunidades detectadas para GREFA")
    st.caption(
        f"Se muestran las licitaciones con relevancia media (≥ {MEDIUM_RELEVANCE_THRESHOLD} %) "
        f"y alta (≥ {HIGH_RELEVANCE_THRESHOLD} %). Usa la búsqueda libre superior para acotar por cualquier término."
    )

    columna_slider, columna_categorias, columna_vista = st.columns([2, 2, 1.4])
    with columna_slider:
        minimo = st.slider(
            "Relevancia mínima (%)",
            min_value=0,
            max_value=100,
            value=MEDIUM_RELEVANCE_THRESHOLD,
            step=5,
        )
    with columna_categorias:
        categorias = st.multiselect(
            "Categorías", options=["Alta", "Media", "Baja"], default=["Alta", "Media"]
        )
    with columna_vista:
        vista = st.radio("Vista", ["Tarjetas", "Tabla"], horizontal=True)

    oportunidades = grefa_filter.filter_opportunities(df, minimo, categorias)

    if oportunidades.empty:
        st.info(
            "Ninguna licitación supera el umbral con los criterios actuales. "
            "Prueba a bajar la relevancia mínima o a añadir CPV/palabras clave en la barra superior."
        )
        return

    resumen = grefa_filter.summarize(oportunidades)
    metrica_1, metrica_2, metrica_3 = st.columns(3)
    metrica_1.metric("Oportunidades", resumen["total"])
    metrica_2.metric("Alta relevancia", resumen["alta"])
    metrica_3.metric("Importe agregado", formato_importe(resumen["importe_oportunidades"]))

    botones_exportacion(oportunidades, "oportunidades", permitir_sheets=True)
    st.divider()

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


def pestana_buscador(df: pd.DataFrame) -> None:
    st.subheader("Buscador general PLACSP")
    st.caption(
        "Filtros adicionales sobre el listado ya filtrado por la búsqueda libre "
        "y las fechas de la barra superior."
    )

    importes = df["presupuesto_sin_iva"].dropna()
    tope = float(importes.max()) if not importes.empty else 0.0

    ubicaciones_disponibles = sorted({u for u in df["ubicacion"].unique() if u})
    ubicaciones = st.multiselect("Ubicación / Provincia", ubicaciones_disponibles)

    estados_globales = st.session_state.get("estados_aplicados") or None
    if estados_globales:
        st.caption(f"Estados aplicados: {', '.join(estados_globales)}")

    busqueda = (st.session_state.get("busqueda_aplicada") or "").strip()
    if busqueda:
        st.caption(f"Búsqueda libre activa: «{busqueda}»")

    if tope > 0:
        rango = st.slider(
            "Rango de presupuesto sin IVA (€)",
            min_value=0.0,
            max_value=tope,
            value=(0.0, tope),
            step=max(tope / 200, 1.0),
            format="%.0f",
        )
        incluir_sin_importe = st.checkbox("Incluir licitaciones sin presupuesto publicado", value=True)
    else:
        rango = (None, None)
        incluir_sin_importe = True
        st.caption("El feed descargado no incluye importes; el filtro de presupuesto está desactivado.")

    resultados = grefa_filter.search_dataframe(
        df,
        presupuesto_min=rango[0],
        presupuesto_max=rango[1],
        ubicaciones=ubicaciones,
        incluir_sin_presupuesto=incluir_sin_importe,
    )

    st.markdown(f"**{len(resultados)}** licitaciones coinciden con los filtros.")
    botones_exportacion(resultados, "busqueda")

    if resultados.empty:
        st.info("Sin coincidencias. Prueba con otros términos o amplía el rango de presupuesto.")
        return

    vista_tabla = tabla_para_mostrar(
        resultados,
        [
            "relevancia", "categoria", "expediente", "titulo", "organo_contratacion",
            "presupuesto_sin_iva", "ubicacion", "tipo_contrato", "cpvs_texto",
            "fecha_actualizacion", "fecha_limite", "estado", "url",
        ],
    )
    st.dataframe(
        vista_tabla,
        width="stretch",
        hide_index=True,
        column_config=CONFIG_COLUMNAS,
        height=620,
    )


# ---------------------------------------------------------------------------
# Aplicación
# ---------------------------------------------------------------------------
def main() -> None:
    if not st.session_state.get("_grefa_filter_reloaded"):
        _recargar_grefa_filter()
        st.session_state["_grefa_filter_reloaded"] = True

    usuario = auth.requiere_acceso()

    st.markdown(
        """
        <div class="bloque-titulo">
            <h1>🦅 GREFA · Monitor de Licitaciones Públicas</h1>
            <p>Plataforma de Contratación del Sector Público · Índice de Relevancia GREFA</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Los criterios compartidos mandan sobre los valores por defecto.
    if not st.session_state["sheets_sincronizado"]:
        cargar_criterios_de_sheets(inicial=True)

    # La primera carga se resuelve antes de pintar la barra lateral para que
    # esta refleje el estado real de los datos ya en el primer render.
    if st.session_state["datos"] is None and not st.session_state["error_descarga"]:
        actualizar_datos()

    sidebar_fuente_datos()
    sidebar_google_sheets()
    auth.barra_usuario(usuario)

    datos = st.session_state["datos"]
    if datos is None:
        datos = empty_dataframe()

    barra_criterios_superior(datos)
    barra_busqueda_filtros(datos)

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
    puntuadas = grefa_filter.score_licitaciones(
        datos,
        cpvs_activos,
        keywords_activas,
        conceptos=conceptos_activos,
    )
    puntuadas = grefa_filter.filter_by_estado(
        puntuadas, st.session_state.get("estados_aplicados") or None
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
    metrica_1, metrica_2, metrica_3, metrica_4, metrica_5 = st.columns(5)
    metrica_1.metric("Licitaciones descargadas", resumen["total"])
    metrica_2.metric("🟢 Alta relevancia", resumen["alta"])
    metrica_3.metric("🟡 Media relevancia", resumen["media"])
    metrica_4.metric("⚪ Baja relevancia", resumen["baja"])
    metrica_5.metric("Criterios activos", f"{len(cpvs_activos)} CPV · {len(conceptos_activos)} conceptos")

    if puntuadas.empty:
        st.warning("No hay datos cargados. Pulsa «Actualizar datos ahora» en la barra lateral.")
        return

    pestana_1, pestana_2 = st.tabs(["🎯 Oportunidades GREFA", "🔎 Buscador General PLACSP"])
    with pestana_1:
        pestana_oportunidades(puntuadas)
    with pestana_2:
        pestana_buscador(puntuadas)

    st.divider()
    st.caption(
        "Datos públicos de la Plataforma de Contratación del Sector Público (contrataciondelestado.es). "
        "El Índice de Relevancia GREFA es una estimación automática: revisa siempre el pliego original."
    )


if __name__ == "__main__":
    main()
