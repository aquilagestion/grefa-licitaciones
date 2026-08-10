"""Interfaz Streamlit del modo Convocatorias: ayudas y premios (BDNS)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
import streamlit as st

from config.default_criteria import (
    CUSTOM_KEYWORD_CATEGORY,
    HIGH_RELEVANCE_THRESHOLD,
    MEDIUM_RELEVANCE_THRESHOLD,
    RELEVANCE_LEVELS,
    flatten_keywords,
)
from config.entidades_catalog import (
    active_entidades,
    active_entidades_detalle,
    default_entidades,
    normalizar_entidad,
)
from config.keyword_catalog import active_keywords_grouped, default_term_catalog
from modules import ayuda_faq, grefa_filter, sheets_store, ui_compartir
from modules.exporter import timestamped_filename, to_csv_bytes, to_excel_bytes
from modules.ingestion_bdns import (
    IngestionError,
    empty_dataframe,
    fetch_convocatorias_bdns,
    filter_by_nivel,
)
from modules.translator import complete_from_any
from modules.web_search_entidades import (
    WebSearchError,
    buscar_entidades_en_web,
    contiene_cadena,
    empty_web_dataframe,
    google_cse_configured,
)

NAV_AYUDAS = [
    "🎯 Oportunidades GREFA",
    "🌐 Web por entidad",
    "🔎 Buscador General BDNS",
    "⭐ Mis Convocatorias",
    "📋 Seguimiento",
    "❓ Ayuda y FAQ",
]

NAV_WEB = "🌐 Web por entidad"


def _ir_a_web_por_entidad() -> None:
    """Callback Streamlit: debe ejecutarse ANTES del radio ``nav_ayudas``."""
    st.session_state["nav_ayudas"] = NAV_WEB


def _ir_a_web_y_buscar() -> None:
    st.session_state["refresh_token_web"] = int(
        st.session_state.get("refresh_token_web") or 0
    ) + 1
    st.session_state["cargando_web_entidades"] = True
    # También refresca BDNS (fase 2 de la cascada).
    st.session_state["refresh_token_ayudas"] = int(
        st.session_state.get("refresh_token_ayudas") or 0
    ) + 1
    st.session_state["cargando_datos_ayudas"] = True
    st.session_state["nav_ayudas"] = NAV_WEB


NIVELES_BDNS = ("ESTADO", "AUTONOMICA", "LOCAL", "OTROS")


def _init_state_ayudas() -> None:
    defaults: dict[str, Any] = {
        "datos_ayudas": None,
        "origen_datos_ayudas": "",
        "ultima_actualizacion_ayudas": None,
        "error_descarga_ayudas": "",
        "refresh_token_ayudas": 0,
        "cargando_datos_ayudas": False,
        "bdns_max_terms": 8,
        "bdns_pages_per_term": 1,
        "bdns_page_size": 40,
        "bdns_max_enrich": 80,
        "bdns_incluir_ultimas": True,
        "bdns_pages_ultimas": 1,
        # Filtros Oportunidades GREFA (independientes)
        "opp_niveles": list(NIVELES_BDNS),
        "opp_estados": ["Abierta", "Publicada"],
        "opp_min_relevancia": MEDIUM_RELEVANCE_THRESHOLD,
        "opp_categorias": ["Alta", "Media"],
        "opp_vista": "Tarjetas",
        "opp_busqueda": "",
        "opp_excluir_convenios": True,
        "opp_solo_entidad": False,
        # Filtros Buscador General BDNS (independientes)
        "bus_niveles": list(NIVELES_BDNS),
        "bus_estados": ["Abierta", "Publicada", "Cerrada"],
        "bus_min_relevancia": 0,
        "bus_categorias": ["Alta", "Media", "Baja"],
        "bus_vista": "Tarjetas",
        "bus_busqueda": "",
        "bus_excluir_convenios": True,
        "bus_solo_entidad": False,
        # Filtros Web por entidad (independientes)
        "web_busqueda": "",
        "web_excluir_convenios": True,
        "web_entidades_filtro": [],
        "web_fases": ["1. Web propia", "3. Web abierta"],
        "seguimiento_cache_ayudas": {},
        "mis_convocatorias_cache": None,
        "mis_convocatorias_local": [],
        "nav_ayudas": NAV_AYUDAS[0],
        "catalogo_entidades": default_entidades(),
        "datos_web_entidades": None,
        "origen_web_entidades": "",
        "error_web_entidades": "",
        "web_max_por_entidad": 8,
        "web_extra_query": "",
        "cargando_web_entidades": False,
        "refresh_token_web": 0,
        "entidades_sheets_sync": False,
        "web_solo_abierta_si_sin_sitio": True,
    }
    for clave, valor in defaults.items():
        st.session_state.setdefault(clave, valor)
    # Si la sesión guardó un menú antiguo (antes de «Web por entidad»), resetear.
    if st.session_state.get("nav_ayudas") not in NAV_AYUDAS:
        st.session_state["nav_ayudas"] = NAV_AYUDAS[0]
    if "catalogo_terminos" not in st.session_state:
        st.session_state["catalogo_terminos"] = default_term_catalog()
    if "keywords" not in st.session_state:
        st.session_state["keywords"] = active_keywords_grouped(
            st.session_state["catalogo_terminos"]
        )


def _clave(expediente: str, url: str) -> str:
    return f"{str(expediente).strip().lower()}|{str(url).strip().lower()}"


def _formato_importe(valor: Any) -> str:
    if valor is None:
        return "—"
    try:
        if pd.isna(valor):
            return "—"
        return f"{float(valor):,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return str(valor)


def _formato_fecha(valor: Any) -> str:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return "—"
    texto = str(valor).strip()
    if not texto:
        return "—"
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(texto[:19], fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return texto[:10]


@st.cache_data(ttl=1800, show_spinner=False)
def _cargar_bdns_cached(
    token: int,
    keywords_key: str,
    entidades_key: str,
    max_terms: int,
    pages_per_term: int,
    page_size: int,
    max_enrich: int,
    incluir_ultimas: bool,
    pages_ultimas: int,
    _cache_ver: str = "entidades-v2",
) -> tuple[pd.DataFrame, str]:
    """Descarga BDNS. ``_cache_ver`` invalida cachés de firmas antiguas."""
    import importlib
    import inspect

    from modules import ingestion_bdns as _ing

    _ing = importlib.reload(_ing)
    keywords = [k for k in keywords_key.split("||") if k]
    entidades = [e for e in entidades_key.split("||") if e]
    fn = _ing.fetch_convocatorias_bdns
    kwargs: dict[str, Any] = {
        "keywords": keywords,
        "max_terms": max_terms,
        "pages_per_term": pages_per_term,
        "page_size": page_size,
        "enrich": True,
        "max_enrich": max_enrich,
        "incluir_ultimas": incluir_ultimas,
        "pages_ultimas": pages_ultimas,
    }
    if "entidades" in inspect.signature(fn).parameters:
        kwargs["entidades"] = entidades
    elif entidades:
        # Compatibilidad con Space/caché que aún no tiene el kwarg.
        kwargs["keywords"] = list(entidades) + list(keywords)
    return fn(**kwargs)


@st.cache_data(ttl=1800, show_spinner=False)
def _cargar_web_cached(
    token: int,
    entidades_payload: str,
    max_por_entidad: int,
    extra_query: str,
    solo_abierta_si_sin_sitio: bool,
    _cache_ver: str = "cascada-v1",
) -> tuple[pd.DataFrame, str]:
    """``entidades_payload``: lineas ``nombre||web`` separadas por ``\\n``."""
    detalle: list[dict[str, str]] = []
    for linea in entidades_payload.split("\n"):
        if not linea.strip():
            continue
        partes = linea.split("||", 1)
        detalle.append(
            {
                "nombre": partes[0].strip(),
                "web": partes[1].strip() if len(partes) > 1 else "",
            }
        )
    return buscar_entidades_en_web(
        detalle,
        max_por_entidad=max_por_entidad,
        extra_query=extra_query,
        solo_abierta_si_sin_sitio=solo_abierta_si_sin_sitio,
    )


def _payload_entidades_web() -> str:
    lineas = []
    for e in active_entidades_detalle(st.session_state.get("catalogo_entidades") or []):
        lineas.append(f"{e['nombre']}||{e.get('web') or ''}")
    return "\n".join(lineas)


def _cargar_entidades_de_sheets(*, forzar: bool = False) -> None:
    if not sheets_store.is_configured():
        return
    if st.session_state.get("entidades_sheets_sync") and not forzar:
        return
    try:
        filas = sheets_store.load_entidades_ayudas()
        if filas:
            st.session_state["catalogo_entidades"] = [
                normalizar_entidad(f) for f in filas
            ]
        elif not st.session_state.get("catalogo_entidades"):
            st.session_state["catalogo_entidades"] = default_entidades()
            sheets_store.save_entidades_ayudas(st.session_state["catalogo_entidades"])
        st.session_state["entidades_sheets_sync"] = True
    except Exception as exc:
        LOGGER = __import__("logging").getLogger(__name__)
        LOGGER.debug("EntidadesAyudas no cargadas: %s", exc)
        st.session_state["entidades_sheets_sync"] = True


def _guardar_entidades_en_sheets() -> None:
    if not sheets_store.is_configured():
        return
    try:
        sheets_store.save_entidades_ayudas(
            list(st.session_state.get("catalogo_entidades") or [])
        )
    except Exception as exc:
        st.warning(f"No se pudieron guardar entidades en Sheets: {exc}")


def _cargar_datos() -> None:
    keywords = flatten_keywords(st.session_state.get("keywords") or {})
    keywords_key = "||".join(sorted({k.strip().lower() for k in keywords if k.strip()}))
    entidades = active_entidades(st.session_state.get("catalogo_entidades") or [])
    entidades_key = "||".join(entidades)
    try:
        df, origen = _cargar_bdns_cached(
            int(st.session_state.get("refresh_token_ayudas") or 0),
            keywords_key,
            entidades_key,
            int(st.session_state.get("bdns_max_terms") or 8),
            int(st.session_state.get("bdns_pages_per_term") or 1),
            int(st.session_state.get("bdns_page_size") or 40),
            int(st.session_state.get("bdns_max_enrich") or 80),
            bool(st.session_state.get("bdns_incluir_ultimas", True)),
            int(st.session_state.get("bdns_pages_ultimas") or 1),
        )
        st.session_state["datos_ayudas"] = df
        st.session_state["origen_datos_ayudas"] = origen
        st.session_state["ultima_actualizacion_ayudas"] = datetime.now()
        st.session_state["error_descarga_ayudas"] = ""
    except IngestionError as exc:
        st.session_state["error_descarga_ayudas"] = str(exc)
        if st.session_state.get("datos_ayudas") is None:
            st.session_state["datos_ayudas"] = empty_dataframe()
    except Exception as exc:
        st.session_state["error_descarga_ayudas"] = f"Error inesperado: {exc}"
        if st.session_state.get("datos_ayudas") is None:
            st.session_state["datos_ayudas"] = empty_dataframe()
    finally:
        st.session_state["cargando_datos_ayudas"] = False


def _cargar_web() -> None:
    try:
        df, origen = _cargar_web_cached(
            int(st.session_state.get("refresh_token_web") or 0),
            _payload_entidades_web(),
            int(st.session_state.get("web_max_por_entidad") or 8),
            str(st.session_state.get("web_extra_query") or ""),
            bool(st.session_state.get("web_solo_abierta_si_sin_sitio", True)),
        )
        st.session_state["datos_web_entidades"] = df
        st.session_state["origen_web_entidades"] = origen
        st.session_state["error_web_entidades"] = ""
    except WebSearchError as exc:
        st.session_state["error_web_entidades"] = str(exc)
        if st.session_state.get("datos_web_entidades") is None:
            st.session_state["datos_web_entidades"] = empty_web_dataframe()
    except Exception as exc:
        st.session_state["error_web_entidades"] = f"Error inesperado: {exc}"
        if st.session_state.get("datos_web_entidades") is None:
            st.session_state["datos_web_entidades"] = empty_web_dataframe()
    finally:
        st.session_state["cargando_web_entidades"] = False


def _sidebar() -> None:
    st.sidebar.header("🔄 Fuente BDNS")
    if st.session_state.get("origen_datos_ayudas"):
        st.sidebar.success(
            f"Actualizado: "
            f"{(st.session_state.get('ultima_actualizacion_ayudas') or datetime.now()):%H:%M:%S}"
        )
        st.sidebar.caption(st.session_state["origen_datos_ayudas"])
    else:
        st.sidebar.info("Sin datos cargados todavía.")

    with st.sidebar.expander("Parámetros de extracción"):
        st.slider("Términos de búsqueda API", 3, 15, key="bdns_max_terms")
        st.slider("Páginas por término", 1, 3, key="bdns_pages_per_term")
        st.slider("Tamaño de página", 20, 100, key="bdns_page_size", step=10)
        st.slider("Máx. fichas enriquecidas", 20, 200, key="bdns_max_enrich", step=10)
        st.checkbox("Incluir convocatorias últimas", key="bdns_incluir_ultimas")
        st.slider("Páginas de últimas", 1, 5, key="bdns_pages_ultimas")

    with st.sidebar.expander("Búsqueda web por entidad", expanded=True):
        motor = "Google CSE" if google_cse_configured() else "DuckDuckGo (sin API key)"
        st.caption(
            f"Motor: {motor}. Orden: **1) web propia** → **2) BDNS** → **3) resto de internet**."
        )
        st.slider("Máx. resultados / entidad", 3, 15, key="web_max_por_entidad")
        st.text_input(
            "Texto extra en la consulta web",
            key="web_extra_query",
            placeholder="ej. 2026 OR 2025",
        )
        st.checkbox(
            "Web abierta solo si el sitio propio no da premios",
            key="web_solo_abierta_si_sin_sitio",
            help="Si la web de la entidad ya devolvió convocatorias, no rastrea toda la red.",
        )
        if st.button(
            "🌐 Ir a Web por entidad",
            type="primary",
            width="stretch",
            key="btn_web_goto",
            on_click=_ir_a_web_por_entidad,
        ):
            pass
        if st.button(
            "🔎 Buscar en webs de entidades",
            width="stretch",
            key="btn_web_now",
            on_click=_ir_a_web_y_buscar,
        ):
            pass

    if st.session_state.get("cargando_datos_ayudas"):
        st.sidebar.info("⏳ Descargando convocatorias…")
    if st.session_state.get("cargando_web_entidades"):
        st.sidebar.info("⏳ Buscando en la web…")

    if st.sidebar.button("🔁 Actualizar datos ahora", type="primary", width="stretch"):
        st.session_state["refresh_token_ayudas"] = int(
            st.session_state.get("refresh_token_ayudas") or 0
        ) + 1
        st.session_state["cargando_datos_ayudas"] = True
        st.rerun()

    st.sidebar.header("📗 Google Sheets")
    if sheets_store.is_configured():
        st.sidebar.markdown(
            f"[Abrir hoja compartida ↗]({sheets_store.spreadsheet_url()})"
        )
        st.sidebar.caption(
            "OportunidadesAyudas · MisConvocatorias · EntidadesAyudas · CatalogoTerminos"
        )
    else:
        st.sidebar.caption("Sheets no configurado (modo local).")

    if st.sidebar.button("🏠 Cambiar de modo", width="stretch"):
        st.session_state["modo_app"] = None
        st.rerun()


def _cargar_mis_cache(*, forzar: bool = False) -> list[dict]:
    if not sheets_store.is_configured():
        return list(st.session_state.get("mis_convocatorias_local") or [])
    if forzar or st.session_state.get("mis_convocatorias_cache") is None:
        try:
            st.session_state["mis_convocatorias_cache"] = sheets_store.load_mis_convocatorias()
        except Exception as exc:
            st.session_state["mis_convocatorias_cache"] = list(
                st.session_state.get("mis_convocatorias_local") or []
            )
            st.caption(f"Mis Convocatorias (caché local): {exc}")
    return list(st.session_state.get("mis_convocatorias_cache") or [])


def _claves_interes() -> set[str]:
    return {
        _clave(f.get("expediente", ""), f.get("url", ""))
        for f in _cargar_mis_cache()
    }


def _marcar_interes(fila: pd.Series | dict, *, interesa: bool) -> None:
    get = fila.get if hasattr(fila, "get") else lambda k, d="": d
    expediente = str(get("expediente", "") or "")
    url = str(get("url", "") or "")
    presupuesto = get("presupuesto_sin_iva", "")
    if presupuesto is not None and str(presupuesto) not in {"", "nan", "None"}:
        try:
            presupuesto = (
                f"{float(presupuesto):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            )
        except Exception:
            presupuesto = str(presupuesto)
    else:
        presupuesto = ""

    if sheets_store.is_configured():
        sheets_store.upsert_mi_convocatoria(
            expediente,
            url,
            titulo=str(get("titulo", "") or ""),
            organo=str(get("organo_contratacion", "") or ""),
            presupuesto=presupuesto,
            estado=str(get("estado", "") or ""),
            relevancia=str(get("relevancia", "") or ""),
            me_interesa=interesa,
        )
        st.session_state["mis_convocatorias_cache"] = None
    else:
        local = list(st.session_state.get("mis_convocatorias_local") or [])
        clave = _clave(expediente, url)
        if interesa:
            if clave not in {_clave(x.get("expediente", ""), x.get("url", "")) for x in local}:
                local.append(
                    {
                        "expediente": expediente,
                        "url": url,
                        "titulo": str(get("titulo", "") or ""),
                        "organo": str(get("organo_contratacion", "") or ""),
                        "presupuesto": presupuesto,
                        "estado": str(get("estado", "") or ""),
                        "relevancia": str(get("relevancia", "") or ""),
                        "me_interesa": "sí",
                        "me_presento": "no",
                        "fecha_interes": datetime.now().strftime("%d/%m/%Y %H:%M"),
                        "notas": "",
                    }
                )
        else:
            local = [
                x
                for x in local
                if _clave(x.get("expediente", ""), x.get("url", "")) != clave
            ]
        st.session_state["mis_convocatorias_local"] = local
        st.session_state["mis_convocatorias_cache"] = local


def _exportar(df: pd.DataFrame, sufijo: str, *, sheets: bool = False) -> None:
    if df.empty:
        st.caption("No hay resultados que exportar.")
        return
    c1, c2, c3, _ = st.columns([1, 1, 1.4, 1.6])
    with c1:
        st.download_button(
            "⬇️ CSV",
            data=to_csv_bytes(df),
            file_name=timestamped_filename(f"ayudas_{sufijo}", "csv"),
            mime="text/csv",
            width="stretch",
            key=f"csv_ayudas_{sufijo}",
        )
    with c2:
        st.download_button(
            "⬇️ Excel",
            data=to_excel_bytes(df),
            file_name=timestamped_filename(f"ayudas_{sufijo}", "xlsx"),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
            key=f"xlsx_ayudas_{sufijo}",
        )
    if sheets and sheets_store.is_configured():
        with c3:
            if st.button(
                "📗 Enviar a Sheets",
                width="stretch",
                key=f"sheets_ayudas_{sufijo}",
            ):
                try:
                    anadidas, omitidas = sheets_store.append_opportunities_ayudas(df)
                    st.toast(
                        f"{anadidas} nuevas en OportunidadesAyudas "
                        f"({omitidas} ya estaban).",
                        icon="✅",
                    )
                except sheets_store.SheetsError as exc:
                    st.error(str(exc))


def _tarjeta(fila: pd.Series, *, key_prefix: str = "opp") -> None:
    nivel = RELEVANCE_LEVELS.get(fila["categoria"], RELEVANCE_LEVELS["Baja"])
    keywords = ", ".join(fila.get("keywords_match") or []) or "—"
    entidades_txt = ", ".join(fila.get("entidades_match") or []) or "—"
    titulo = fila.get("titulo") or "(Sin título)"
    st.markdown(
        f"""
        <div class="tarjeta" style="--color-acento: {nivel['color']};">
            <div style="display:flex; justify-content:space-between; align-items:center; gap:1rem;">
                <span class="badge" style="background:{nivel['color']};">
                    {nivel['emoji']} {fila['badge']} · {fila['relevancia']}%
                </span>
                <span class="meta">{_formato_fecha(fila.get('fecha_actualizacion'))}</span>
            </div>
            <h4>{titulo}</h4>
            <p class="meta"><strong>Órgano:</strong> {fila.get('organo_contratacion') or '—'}</p>
            <p class="meta">
                <strong>Presupuesto:</strong> {_formato_importe(fila.get('presupuesto_sin_iva'))}
                &nbsp;·&nbsp; <strong>Nivel:</strong> {fila.get('nivel_admin') or '—'}
                &nbsp;·&nbsp; <strong>Estado:</strong> {fila.get('estado') or '—'}
            </p>
            <p class="meta"><strong>BDNS:</strong> {fila.get('expediente') or '—'}
                &nbsp;·&nbsp; <strong>Fin solicitud:</strong> {_formato_fecha(fila.get('fecha_limite'))}
                &nbsp;·&nbsp; <strong>Instrumento:</strong> {fila.get('tipo_contrato') or '—'}
            </p>
            <p class="meta"><strong>Palabras clave:</strong> {keywords}</p>
            <p class="meta"><strong>Entidades:</strong> {entidades_txt}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    clave = _clave(str(fila.get("expediente") or ""), str(fila.get("url") or ""))
    en_mis = clave in _claves_interes()
    c1, c2, c3, c4 = st.columns([1, 1.2, 1.2, 1.2])
    with c1:
        if fila.get("url"):
            st.link_button("Ver BDNS ↗", fila["url"], width="stretch")
    with c2:
        etiqueta = "⭐ Ya en Mis Conv." if en_mis else "⭐ Mis Convocatorias"
        if st.button(
            etiqueta,
            key=f"{key_prefix}_mis_{clave[:40]}",
            width="stretch",
            type="primary" if not en_mis else "secondary",
        ):
            try:
                _marcar_interes(fila, interesa=not en_mis)
                st.toast(
                    "Añadida a Mis Convocatorias." if not en_mis else "Quitada.",
                    icon="⭐" if not en_mis else "🗑️",
                )
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    with c3:
        url = str(fila.get("url") or "")
        if url:
            titulo_mail = str(fila.get("titulo") or "")
            exp = str(fila.get("expediente") or "")
            asunto = f"GREFA · BDNS · {exp or titulo_mail[:50]}"
            cuerpo = (
                f"{titulo_mail}\n\n"
                f"Expediente BDNS: {exp or '—'}\n"
                f"Órgano: {fila.get('organo_contratacion') or '—'}\n"
                f"Relevancia: {fila.get('relevancia', '—')}%\n\n"
                f"Enlace: {url}"
            )
            st.link_button(
                "✉️ Correo",
                ui_compartir.enlace_email_gmail(asunto, cuerpo),
                width="stretch",
                help="Abre Gmail con el enlace de la convocatoria",
            )
        else:
            st.caption("Sin enlace")
    with c4:
        ui_compartir.render_compartir(
            fila, key=f"{key_prefix}_share_{clave[:40]}", fuente_label="BDNS"
        )
    with st.expander("¿Por qué esta puntuación?", expanded=False):
        st.write(fila.get("justificacion", ""))
        if fila.get("descripcion"):
            st.caption(str(fila["descripcion"])[:800])
        if fila.get("sede_electronica"):
            st.markdown(f"[Sede electrónica ↗]({fila['sede_electronica']})")


def _panel_entidades() -> None:
    catalogo = list(st.session_state.get("catalogo_entidades") or [])
    # Migrar entradas antiguas sin campo web
    catalogo = [normalizar_entidad(e) for e in catalogo]
    st.session_state["catalogo_entidades"] = catalogo
    activos = sum(1 for e in catalogo if e.get("activo"))
    st.caption(
        f"**{activos}** entidades activas de {len(catalogo)} en la relación. "
        "La búsqueda usa **todas las activas** por defecto."
    )
    with st.expander(
        f"Gestionar entidades · {activos} activas",
        expanded=False,
    ):
        st.caption(
            "Añade, edita o activa/desactiva entidades. "
            "La búsqueda web usa las activas (sitio propio → resto de internet si hace falta)."
        )

        nuevo = st.text_input(
            "Nombre de la entidad",
            key="ayu_nueva_entidad",
            placeholder="Ej. Fundación BBVA, SEO/BirdLife…",
        )
        nueva_web = st.text_input(
            "Página web de la entidad (opcional)",
            key="ayu_nueva_entidad_web",
            placeholder="https://www.ejemplo.org/",
        )
        nuevas_notas = st.text_input(
            "Notas (opcional)",
            key="ayu_nueva_entidad_notas",
            placeholder="Premios, área temática…",
        )
        c_btn, c_save = st.columns(2)
        with c_btn:
            if st.button("➕ Añadir entidad", key="ayu_add_ent", width="stretch") and nuevo.strip():
                nombre = nuevo.strip()
                if not any(
                    str(e.get("nombre", "")).strip().lower() == nombre.lower()
                    for e in catalogo
                ):
                    catalogo.append(
                        normalizar_entidad(
                            {
                                "nombre": nombre,
                                "web": nueva_web.strip(),
                                "notas": nuevas_notas.strip(),
                                "activo": True,
                            }
                        )
                    )
                    st.session_state["catalogo_entidades"] = catalogo
                    _guardar_entidades_en_sheets()
                st.rerun()
        with c_save:
            if st.button("💾 Guardar en Sheets", key="ayu_save_ent", width="stretch"):
                _guardar_entidades_en_sheets()
                st.toast("Entidades guardadas en Sheets", icon="✅")

        if not catalogo:
            st.info("No hay entidades. Añade al menos una para vigilar premios/convocatorias.")
            return

        for i, ent in enumerate(catalogo):
            nombre = str(ent.get("nombre") or f"entidad {i}")
            with st.container(border=True):
                c1, c2, c3 = st.columns([0.1, 0.72, 0.18])
                with c1:
                    activo = st.checkbox(
                        "On",
                        value=bool(ent.get("activo")),
                        key=f"ayu_ent_on_{i}",
                        label_visibility="collapsed",
                    )
                with c2:
                    st.markdown(f"**{nombre}**")
                    if ent.get("notas"):
                        st.caption(str(ent["notas"]))
                with c3:
                    if st.button("✕", key=f"ayu_ent_del_{i}", help="Eliminar"):
                        catalogo.pop(i)
                        st.session_state["catalogo_entidades"] = catalogo
                        _guardar_entidades_en_sheets()
                        st.rerun()

                web_key = f"ayu_ent_web_{i}"
                if web_key not in st.session_state:
                    st.session_state[web_key] = str(ent.get("web") or "")
                c_web, c_ok = st.columns([0.82, 0.18])
                with c_web:
                    st.text_input(
                        "Web oficial",
                        key=web_key,
                        placeholder="https://…",
                    )
                with c_ok:
                    st.write("")
                    if st.button("OK", key=f"ayu_ent_web_ok_{i}", help="Guardar URL"):
                        catalogo[i]["web"] = normalizar_entidad(
                            {"web": st.session_state.get(web_key) or ""}
                        )["web"]
                        st.session_state["catalogo_entidades"] = catalogo
                        _guardar_entidades_en_sheets()
                        st.rerun()
                if ent.get("web"):
                    st.markdown(f"[Abrir web ↗]({ent['web']})")

                if activo != bool(ent.get("activo")):
                    catalogo[i]["activo"] = activo
                    st.session_state["catalogo_entidades"] = catalogo
                    _guardar_entidades_en_sheets()
                    st.rerun()


def _anotar_entidades_bdns(df: pd.DataFrame) -> pd.DataFrame:
    """Añade columna entidades_match si el título/órgano/descripción contiene la cadena."""
    if df is None or df.empty:
        return df
    entidades = active_entidades(st.session_state.get("catalogo_entidades") or [])
    if not entidades:
        out = df.copy()
        out["entidades_match"] = [[] for _ in range(len(out))]
        return out

    matches: list[list[str]] = []
    for fila in df.to_dict("records"):
        blob = " ".join(
            str(fila.get(c) or "")
            for c in (
                "titulo",
                "organo_contratacion",
                "descripcion",
                "finalidad",
                "nivel_admin",
            )
        )
        halladas = [e for e in entidades if contiene_cadena(blob, e)]
        matches.append(halladas)
    out = df.copy()
    out["entidades_match"] = matches
    # Bonus si hay entidad vigilada (permite Alta aunque los términos sean genéricos).
    if "relevancia" in out.columns:
        bonus = out["entidades_match"].map(lambda xs: 25 if xs else 0)
        out["relevancia"] = (out["relevancia"].astype(int) + bonus).clip(upper=100)
        out["categoria"] = out["relevancia"].map(grefa_filter.classify)
        out["badge"] = out["categoria"].map(
            lambda c: RELEVANCE_LEVELS.get(c, RELEVANCE_LEVELS["Baja"])["badge"]
        )
        out["color"] = out["categoria"].map(
            lambda c: RELEVANCE_LEVELS.get(c, RELEVANCE_LEVELS["Baja"])["color"]
        )
        out = out.sort_values(
            by=["relevancia", "fecha_actualizacion"],
            ascending=[False, False],
            na_position="last",
        ).reset_index(drop=True)
    return out


def _asegurar_filtros_bdns(prefix: str) -> None:
    """Defaults por pestaña (opp / bus) para no dejar multiselects vacíos."""
    if not st.session_state.get(f"{prefix}_niveles"):
        st.session_state[f"{prefix}_niveles"] = list(NIVELES_BDNS)
    if not st.session_state.get(f"{prefix}_estados"):
        st.session_state[f"{prefix}_estados"] = ["Abierta", "Publicada"]
    if not st.session_state.get(f"{prefix}_categorias"):
        st.session_state[f"{prefix}_categorias"] = ["Alta", "Media"]
    if st.session_state.get(f"{prefix}_min_relevancia") is None:
        st.session_state[f"{prefix}_min_relevancia"] = (
            MEDIUM_RELEVANCE_THRESHOLD if prefix == "opp" else 0
        )
    if not st.session_state.get(f"{prefix}_vista"):
        st.session_state[f"{prefix}_vista"] = "Tarjetas"


def _render_filtros_bdns(prefix: str) -> None:
    """Filtros BDNS independientes por pestaña (opp / bus)."""
    _asegurar_filtros_bdns(prefix)
    c1, c2, c3 = st.columns(3)
    with c1:
        st.multiselect(
            "Nivel administrativo",
            list(NIVELES_BDNS),
            key=f"{prefix}_niveles",
        )
    with c2:
        st.multiselect(
            "Estado",
            ["Abierta", "Publicada", "Cerrada"],
            key=f"{prefix}_estados",
        )
    with c3:
        st.slider(
            "Relevancia mínima (%)",
            0,
            100,
            key=f"{prefix}_min_relevancia",
        )

    c4, c5, c6 = st.columns(3)
    with c4:
        st.multiselect(
            "Categorías",
            ["Alta", "Media", "Baja"],
            key=f"{prefix}_categorias",
        )
    with c5:
        st.radio(
            "Vista",
            ["Tarjetas", "Tabla"],
            horizontal=True,
            key=f"{prefix}_vista",
        )
    with c6:
        st.text_input("Búsqueda libre", key=f"{prefix}_busqueda")

    f1, f2 = st.columns(2)
    with f1:
        st.checkbox(
            "Excluir convenios (nominativos ya firmados)",
            key=f"{prefix}_excluir_convenios",
            help="Los convenios no son convocatorias abiertas a las que presentar.",
        )
    with f2:
        st.checkbox(
            "Solo con entidad vigilada en título/órgano",
            key=f"{prefix}_solo_entidad",
        )


def _filtrar_puntuadas(puntuadas: pd.DataFrame, prefix: str) -> pd.DataFrame:
    """Aplica en vivo los filtros BDNS de la pestaña indicada."""
    if puntuadas is None or puntuadas.empty:
        return puntuadas if puntuadas is not None else empty_dataframe()

    _asegurar_filtros_bdns(prefix)
    filtrado = filter_by_nivel(puntuadas, st.session_state.get(f"{prefix}_niveles"))
    filtrado = grefa_filter.filter_by_estado(
        filtrado, st.session_state.get(f"{prefix}_estados") or None
    )
    texto = str(st.session_state.get(f"{prefix}_busqueda") or "").strip()
    if texto:
        filtrado = grefa_filter.filter_by_texto_libre(filtrado, texto)

    if st.session_state.get(f"{prefix}_excluir_convenios", True) and not filtrado.empty:
        titulos = filtrado["titulo"].fillna("").astype(str).str.lower()
        filtrado = filtrado[~titulos.str.contains(r"\bconvenio\b", regex=True, na=False)]

    if st.session_state.get(f"{prefix}_solo_entidad") and not filtrado.empty:
        if "entidades_match" in filtrado.columns:
            filtrado = filtrado[filtrado["entidades_match"].map(lambda xs: bool(xs))]

    minimo = int(st.session_state.get(f"{prefix}_min_relevancia") or 0)
    cats = list(st.session_state.get(f"{prefix}_categorias") or [])
    return grefa_filter.filter_opportunities(filtrado, minimo, cats)


def _asegurar_filtros_web() -> None:
    if st.session_state.get("web_fases") is None:
        st.session_state["web_fases"] = ["1. Web propia", "3. Web abierta"]


def _render_filtros_web() -> None:
    """Filtros solo para resultados web de entidades."""
    _asegurar_filtros_web()
    c1, c2 = st.columns(2)
    with c1:
        st.text_input("Búsqueda libre", key="web_busqueda")
        st.checkbox(
            "Excluir resultados con «convenio»",
            key="web_excluir_convenios",
        )
    with c2:
        st.multiselect(
            "Fase",
            ["1. Web propia", "3. Web abierta"],
            key="web_fases",
        )
        st.caption("Por defecto se buscan **todas** las entidades activas.")


def _filtrar_web_viva(df: pd.DataFrame) -> pd.DataFrame:
    """Filtros propios de la pestaña Web por entidad.

    Sin selección de entidades (= vacío) se muestran resultados de **todas**.
    """
    if df is None or df.empty:
        return df if df is not None else empty_web_dataframe()
    _asegurar_filtros_web()
    out = df

    # Solo restringir si el usuario hubiera dejado un subconjunto (legado);
    # por defecto web_entidades_filtro queda vacío → todas.
    entidades = list(st.session_state.get("web_entidades_filtro") or [])
    if entidades and "entidad" in out.columns:
        out = out[out["entidad"].astype(str).isin(entidades)]

    fases = list(st.session_state.get("web_fases") or [])
    if fases and "fase" in out.columns:
        out = out[out["fase"].astype(str).isin(fases)]

    texto = str(st.session_state.get("web_busqueda") or "").strip().lower()
    if texto:
        mask = pd.Series(False, index=out.index)
        for col in ("titulo", "snippet", "entidad", "url"):
            if col in out.columns:
                mask = mask | (
                    out[col]
                    .fillna("")
                    .astype(str)
                    .str.lower()
                    .str.contains(texto, regex=False)
                )
        out = out[mask]
    if st.session_state.get("web_excluir_convenios", True) and not out.empty:
        if "titulo" in out.columns:
            titulos = out["titulo"].fillna("").astype(str).str.lower()
            out = out[~titulos.str.contains(r"\bconvenio\b", regex=True, na=False)]
    return out.reset_index(drop=True)


def _fila_web_a_interes(fila: pd.Series | dict) -> dict:
    get = fila.get if hasattr(fila, "get") else lambda k, d="": d
    entidad = str(get("entidad", "") or "")
    url = str(get("url", "") or "")
    return {
        "expediente": f"WEB:{entidad}" if entidad else "WEB",
        "url": url,
        "titulo": str(get("titulo", "") or ""),
        "organo_contratacion": entidad,
        "presupuesto_sin_iva": "",
        "estado": str(get("fase", "") or "Web"),
        "relevancia": "",
    }


def _acciones_resultado_web(fila: pd.Series, *, key: str) -> None:
    url = str(fila.get("url") or "")
    payload = _fila_web_a_interes(fila)
    clave = _clave(payload["expediente"], payload["url"])
    en_mis = clave in _claves_interes()
    c1, c2, c3, c4 = st.columns([1, 1.2, 1, 1.2])
    with c1:
        if url:
            st.link_button("Abrir ↗", url, width="stretch")
    with c2:
        etiqueta = "⭐ Ya en Mis Conv." if en_mis else "⭐ Mis Convocatorias"
        if st.button(
            etiqueta,
            key=f"{key}_mis",
            width="stretch",
            type="primary" if not en_mis else "secondary",
        ):
            try:
                _marcar_interes(payload, interesa=not en_mis)
                st.toast(
                    "Añadida a Mis Convocatorias." if not en_mis else "Quitada.",
                    icon="⭐" if not en_mis else "🗑️",
                )
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    with c3:
        if url:
            asunto = f"GREFA · Web · {payload['organo_contratacion'] or 'entidad'}"
            cuerpo = (
                f"{payload['titulo']}\n\n"
                f"Entidad: {payload['organo_contratacion']}\n"
                f"Fase: {fila.get('fase') or '—'}\n\n"
                f"Enlace: {url}"
            )
            st.link_button(
                "✉️ Correo",
                ui_compartir.enlace_email_gmail(asunto, cuerpo),
                width="stretch",
            )
    with c4:
        ui_compartir.render_compartir(
            {
                "titulo": payload["titulo"],
                "expediente": payload["organo_contratacion"],
                "url": url,
            },
            key=f"{key}_share",
            fuente_label="Web",
        )


def _panel_terminos() -> None:
    catalogo = st.session_state.get("catalogo_terminos") or []
    activos = sum(1 for t in catalogo if t.get("activo"))
    with st.expander(f"Términos GREFA activos · {activos}", expanded=False):
        st.caption(
            "Conceptos GREFA (biodiversidad, fauna, etc.) + nombres de entidades "
            "vigiladas: se usan para buscar en BDNS y puntuar las oportunidades."
        )
        nuevo = st.text_input("Añadir término", key="ayu_nuevo_termino")
        if st.button("Añadir", key="ayu_add_term") and nuevo.strip():
            term = complete_from_any(nuevo.strip())
            term["categoria"] = term.get("categoria") or CUSTOM_KEYWORD_CATEGORY
            term["activo"] = True
            catalogo.append(term)
            st.session_state["catalogo_terminos"] = catalogo
            st.session_state["keywords"] = active_keywords_grouped(catalogo)
            st.rerun()
        for i, term in enumerate(catalogo):
            etiqueta = term.get("castellano") or term.get("termino") or f"término {i}"
            activo = st.checkbox(
                etiqueta,
                value=bool(term.get("activo")),
                key=f"ayu_term_{i}_{etiqueta[:20]}",
            )
            if activo != bool(term.get("activo")):
                catalogo[i]["activo"] = activo
                st.session_state["catalogo_terminos"] = catalogo
                st.session_state["keywords"] = active_keywords_grouped(catalogo)
                st.rerun()


def _panel_control(puntuadas: pd.DataFrame, resumen: dict) -> tuple[pd.DataFrame, str]:
    _ = resumen
    with st.container(border=True):
        st.markdown(
            '<span class="cabecera-titulo">🦅 GREFA · Oportunidades (BDNS)</span>',
            unsafe_allow_html=True,
        )
        st.caption(
            "Ayudas y premios puntuados con el Índice GREFA "
            "(términos + coincidencias de entidades vigiladas). "
            "Las entidades se gestionan en **Web por entidad**."
        )

        _panel_terminos()
        st.markdown("#### Filtros de esta pestaña")
        st.caption("Independientes del Buscador y de Web. Se aplican al instante.")
        _render_filtros_bdns("opp")

        oportunidades = _filtrar_puntuadas(puntuadas, "opp")
        met = grefa_filter.summarize(oportunidades)
        m1, m2, m3, m4 = st.columns(4, gap="small")
        m1.metric("Ayudas", met.get("total", 0))
        m2.metric("Alta", met.get("alta", 0))
        m3.metric("Media", met.get("media", 0))
        m4.metric("Baja", met.get("baja", 0))

    vista = str(st.session_state.get("opp_vista") or "Tarjetas")
    return oportunidades, vista


def _pestana_oportunidades(
    oportunidades: pd.DataFrame, vista: str, *, key_prefix: str = "opp"
) -> None:
    if oportunidades.empty:
        st.info(
            "Ninguna convocatoria supera el umbral. Baja la relevancia mínima "
            "o ajusta los términos GREFA."
        )
        return
    _exportar(oportunidades, key_prefix, sheets=(key_prefix == "opp"))
    if vista == "Tarjetas":
        total = len(oportunidades)
        a_mostrar = min(total, 15)
        if total > 5:
            a_mostrar = st.slider(
                "Nº de tarjetas",
                5,
                min(total, 60),
                min(15, total),
                step=5,
                key=f"ayu_n_tarjetas_{key_prefix}",
            )
        for _, fila in oportunidades.head(a_mostrar).iterrows():
            _tarjeta(fila, key_prefix=key_prefix)
        if total > a_mostrar:
            st.caption(f"Mostrando {a_mostrar} de {total}. Usa la vista tabla o exporta.")
    else:
        cols = [
            "relevancia",
            "badge",
            "titulo",
            "organo_contratacion",
            "presupuesto_sin_iva",
            "nivel_admin",
            "tipo_contrato",
            "keywords_match",
            "fecha_limite",
            "estado",
            "url",
        ]
        base = oportunidades[[c for c in cols if c in oportunidades.columns]].copy()
        mostrar = ui_compartir.enriquecer_dataframe_compartir(
            base, fuente_label="BDNS"
        )
        st.dataframe(
            mostrar,
            width="stretch",
            hide_index=True,
            height=560,
            column_config={
                "url": st.column_config.LinkColumn(
                    "Enlace BDNS", display_text="Abrir BDNS"
                ),
                **ui_compartir.COLUMN_CONFIG_COMPARTIR,
            },
        )
        st.caption(
            "En cada fila: **Compartir WhatsApp** / **Compartir Email** "
            "y el enlace oficial BDNS."
        )


def _pestana_buscador(df: pd.DataFrame) -> None:
    st.subheader("Buscador General BDNS")
    st.caption(
        "Todas las convocatorias de la sesión. Filtros propios "
        "(no compartidos con Oportunidades GREFA)."
    )
    with st.container(border=True):
        st.markdown("#### Filtros de esta pestaña")
        _render_filtros_bdns("bus")
    filtrado = _filtrar_puntuadas(df, "bus")
    st.caption(f"{len(filtrado):,} resultados")
    vista = str(st.session_state.get("bus_vista") or "Tarjetas")
    _pestana_oportunidades(filtrado, vista, key_prefix="bus")


def _pestana_mis() -> None:
    st.subheader("Mis Convocatorias")
    if st.button("🔄 Recargar", key="mis_ayu_reload"):
        st.session_state["mis_convocatorias_cache"] = None
        st.rerun()
    filas = _cargar_mis_cache()
    if not filas:
        st.info("Aún no hay convocatorias guardadas. Usa ⭐ en Oportunidades, Web por entidad o Buscador.")
        return
    st.markdown(f"**{len(filas)}** de interés")
    for idx, fila in enumerate(filas):
        with st.container(border=True):
            st.markdown(
                f"**{fila.get('expediente') or '—'}** — {str(fila.get('titulo') or '')[:140]}"
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
            c1, c2, c3 = st.columns(3)
            with c1:
                if fila.get("url"):
                    st.link_button("BDNS ↗", fila["url"], width="stretch")
            with c2:
                ui_compartir.render_compartir(
                    {
                        "titulo": fila.get("titulo") or "",
                        "expediente": fila.get("expediente") or "",
                        "url": fila.get("url") or "",
                    },
                    key=f"mis_ayu_share_{idx}",
                    fuente_label="BDNS",
                )
            with c3:
                if st.button("Quitar ⭐", key=f"mis_ayu_del_{idx}", width="stretch"):
                    try:
                        _marcar_interes(fila, interesa=False)
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))


def _pestana_seguimiento() -> None:
    st.subheader("Seguimiento de ayudas y premios")
    if not sheets_store.is_configured():
        st.info("Configura Google Sheets para gestionar el seguimiento compartido.")
        return
    if st.button("🔄 Recargar seguimiento", key="seg_ayu_reload"):
        try:
            st.session_state["seguimiento_cache_ayudas"] = (
                sheets_store.load_opportunities_tracking_ayudas()
            )
        except Exception as exc:
            st.error(str(exc))
            return
        st.rerun()

    cache = st.session_state.get("seguimiento_cache_ayudas") or {}
    if not cache:
        try:
            cache = sheets_store.load_opportunities_tracking_ayudas()
            st.session_state["seguimiento_cache_ayudas"] = cache
        except Exception as exc:
            st.warning(str(exc))
            return
    if not cache:
        st.info(
            "No hay filas en OportunidadesAyudas. Envía oportunidades desde la pestaña "
            "Oportunidades con «Enviar a Sheets»."
        )
        return

    for clave, item in list(cache.items())[:80]:
        with st.container(border=True):
            st.markdown(f"**{item.get('expediente')}** — {item.get('titulo', '')[:120]}")
            st.caption(item.get("organo") or "")
            nuevo = st.selectbox(
                "Seguimiento",
                sheets_store.SEGUIMIENTO_OPTIONS,
                index=max(
                    0,
                    sheets_store.SEGUIMIENTO_OPTIONS.index(
                        item.get("seguimiento")
                        if item.get("seguimiento") in sheets_store.SEGUIMIENTO_OPTIONS
                        else sheets_store.DEFAULT_TRACKING
                    ),
                ),
                key=f"seg_ayu_est_{clave[:40]}",
            )
            notas = st.text_area(
                "Notas",
                value=item.get("notas") or "",
                key=f"seg_ayu_not_{clave[:40]}",
                height=80,
            )
            if st.button("Guardar", key=f"seg_ayu_save_{clave[:40]}"):
                try:
                    sheets_store.update_opportunity_tracking_ayudas(
                        item.get("expediente", ""),
                        item.get("url", ""),
                        seguimiento=nuevo,
                        notas=notas,
                    )
                    st.session_state["seguimiento_cache_ayudas"] = None
                    st.toast("Seguimiento guardado", icon="✅")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))


def _pestana_web(puntuadas_bdns: pd.DataFrame | None = None) -> None:
    _ = puntuadas_bdns  # BDNS se consulta en Oportunidades; aquí solo web de entidades
    st.subheader("Web por entidad")
    st.markdown(
        """
Busca en **todas las entidades activas** de la relación (web propia y, si hace falta, resto de internet).
Despliega **Gestionar entidades** solo para añadir o editar. Las ayudas BDNS están en **Oportunidades GREFA**.
"""
    )
    st.caption(
        f"Motor: {'Google CSE' if google_cse_configured() else 'DuckDuckGo'}."
    )

    _panel_entidades()

    detalle = active_entidades_detalle(st.session_state.get("catalogo_entidades") or [])
    if not detalle:
        st.warning("Despliega **Gestionar entidades** y añade o activa al menos una.")
        return

    with st.container(border=True):
        st.markdown("#### Filtros de resultados web")
        st.caption("Independientes de Oportunidades y del Buscador BDNS.")
        _render_filtros_web()

    c1, c2 = st.columns([1, 3])
    with c1:
        if st.button(
            "🔎 Buscar en webs de entidades",
            type="primary",
            key="web_tab_buscar",
            on_click=_ir_a_web_y_buscar,
        ):
            pass
    with c2:
        st.caption(
            "También actualiza BDNS en segundo plano (para Oportunidades GREFA)."
        )

    if st.session_state.get("cargando_web_entidades") or st.session_state.get(
        "cargando_datos_ayudas"
    ):
        with st.spinner("Buscando en webs de entidades…"):
            if st.session_state.get("cargando_datos_ayudas"):
                _cargar_datos()
            if st.session_state.get("cargando_web_entidades"):
                _cargar_web()

    if st.session_state.get("error_web_entidades"):
        st.error(st.session_state["error_web_entidades"])
    if st.session_state.get("error_descarga_ayudas"):
        st.caption(f"BDNS (segundo plano): {st.session_state['error_descarga_ayudas']}")

    st.markdown("### Resultados web")
    df = st.session_state.get("datos_web_entidades")
    if df is None:
        st.info("Pulsa **Buscar en webs de entidades** para lanzar la búsqueda.")
        return
    if st.session_state.get("origen_web_entidades"):
        st.caption(st.session_state["origen_web_entidades"])

    df = _filtrar_web_viva(df)
    if df.empty:
        st.warning(
            "Sin resultados web con los filtros actuales. "
            "Revisa entidades, URLs o lanza de nuevo la búsqueda."
        )
        return

    _exportar(df, "web_entidades")

    fases = []
    if "fase" in df.columns:
        fases = [
            f
            for f in ["1. Web propia", "3. Web abierta"]
            if f in set(df["fase"].astype(str))
        ]
    if not fases:
        fases = ["Resultados"]

    for fase in fases:
        bloque_fase = (
            df[df["fase"].astype(str) == fase] if "fase" in df.columns else df
        )
        if bloque_fase.empty:
            continue
        st.markdown(f"#### {fase} · {len(bloque_fase)}")
        for entidad in [e["nombre"] for e in detalle]:
            bloque = (
                bloque_fase[bloque_fase["entidad"].astype(str) == entidad]
                if "entidad" in bloque_fase.columns
                else bloque_fase
            )
            if bloque.empty:
                continue
            st.markdown(f"**{entidad}** · {len(bloque)}")
            for idx, fila in bloque.iterrows():
                with st.container(border=True):
                    st.markdown(f"**{fila.get('titulo') or '—'}**")
                    st.caption(str(fila.get("snippet") or "")[:320])
                    st.caption(
                        f"{fila.get('fuente') or ''} · {fila.get('consulta') or ''}"
                    )
                    safe_ent = "".join(ch if ch.isalnum() else "_" for ch in entidad)[:24]
                    _acciones_resultado_web(
                        fila,
                        key=f"web_res_{fase[:6]}_{safe_ent}_{idx}",
                    )


def _pestana_faq() -> None:
    st.subheader("Ayuda · Ayudas y premios")
    st.markdown(
        """
### Flujo recomendado
1. En **Web por entidad**: añade/activa entidades (con web propia si la conoces) y busca en sus webs.
2. En **Oportunidades GREFA**: revisa ayudas BDNS filtradas (términos GREFA + entidades).
3. Guarda lo interesante con **⭐ Mis Convocatorias** o compártelo por **✉️ Correo**.
"""
    )
    for item in ayuda_faq.SECCIONES_FAQ[:6]:
        with st.expander(item["pregunta"]):
            st.write(item["respuesta"])


def render_hub_selector() -> None:
    """Pantalla inicial: elegir Licitaciones o Ayudas/premios."""
    st.markdown(
        '<div class="cabecera-compacta">'
        '<span class="cabecera-titulo">🦅 GREFA · Monitor de oportunidades</span>'
        '<span class="cabecera-badge">Elige un modo</span>'
        "</div>",
        unsafe_allow_html=True,
    )
    st.caption(
        "Dos fuentes oficiales distintas: contratación pública (PLACSP) "
        "y subvenciones/ayudas/premios públicos (BDNS)."
    )
    c1, c2 = st.columns(2, gap="large")
    with c1:
        with st.container(border=True):
            st.markdown("### 📑 Licitaciones públicas")
            st.write(
                "Monitor PLACSP: CPV, palabras clave, Mis Licitaciones, "
                "pliegos, documentación y seguimiento."
            )
            if st.button(
                "Entrar a Licitaciones",
                type="primary",
                width="stretch",
                key="hub_licitaciones",
            ):
                st.session_state["modo_app"] = "licitaciones"
                st.rerun()
    with c2:
        with st.container(border=True):
            st.markdown("### 🏆 Ayudas y premios")
            st.write(
                "Convocatorias BDNS + búsqueda web por entidades "
                "(fundaciones, premios) con el Índice GREFA."
            )
            if st.button(
                "Entrar a Ayudas y premios",
                type="primary",
                width="stretch",
                key="hub_ayudas",
            ):
                st.session_state["modo_app"] = "ayudas"
                st.rerun()


def main_ayudas(usuario: Any = None) -> None:
    """Punto de entrada del modo ayudas/premios."""
    _init_state_ayudas()
    _cargar_entidades_de_sheets()
    _sidebar()
    if usuario is not None:
        try:
            from modules import auth

            auth.barra_usuario(usuario)
        except Exception:
            pass

    necesita = st.session_state.get("cargando_datos_ayudas") or (
        st.session_state.get("datos_ayudas") is None
        and not st.session_state.get("error_descarga_ayudas")
    )
    if necesita:
        with st.spinner("Descargando convocatorias de la BDNS…"):
            st.session_state["cargando_datos_ayudas"] = True
            _cargar_datos()

    if st.session_state.get("cargando_web_entidades"):
        with st.spinner("Buscando en la web…"):
            _cargar_web()

    if st.session_state.get("error_descarga_ayudas"):
        st.error(st.session_state["error_descarga_ayudas"])

    datos = st.session_state.get("datos_ayudas")
    if datos is None:
        datos = empty_dataframe()

    st.session_state["keywords"] = active_keywords_grouped(
        st.session_state.get("catalogo_terminos") or []
    )
    keywords = flatten_keywords(st.session_state["keywords"])
    conceptos = [
        t for t in st.session_state.get("catalogo_terminos", []) if t.get("activo")
    ]

    _asegurar_filtros_bdns("opp")
    _asegurar_filtros_bdns("bus")
    # Puntuar todo el corpus; cada pestaña aplica sus filtros propios.
    puntuadas_todas = grefa_filter.score_convocatorias(
        datos, keywords, conceptos=conceptos
    )
    puntuadas_todas = _anotar_entidades_bdns(puntuadas_todas)
    resumen = grefa_filter.summarize(_filtrar_puntuadas(puntuadas_todas, "opp"))

    with st.container():
        st.markdown('<span class="nav-principal-flag"></span>', unsafe_allow_html=True)
        st.caption("Menú del modo Ayudas y premios")
        pagina = st.radio(
            "Menú ayudas",
            NAV_AYUDAS,
            horizontal=True,
            key="nav_ayudas",
            label_visibility="collapsed",
        )

    if pagina == NAV_AYUDAS[0]:
        oportunidades, vista = _panel_control(puntuadas_todas, resumen)
        if puntuadas_todas.empty:
            st.info("Pulsa «Actualizar datos ahora» en la barra lateral.")
        else:
            _pestana_oportunidades(oportunidades, vista)
    elif pagina == NAV_WEB or pagina == NAV_AYUDAS[1]:
        _pestana_web(puntuadas_todas)
    elif pagina == NAV_AYUDAS[2]:
        if puntuadas_todas.empty:
            st.info("Carga convocatorias para usar el buscador.")
        else:
            _pestana_buscador(puntuadas_todas)
    elif pagina == NAV_AYUDAS[3]:
        _pestana_mis()
    elif pagina == NAV_AYUDAS[4]:
        _pestana_seguimiento()
    else:
        _pestana_faq()

    st.divider()
    st.caption(
        "Datos públicos de la Base de Datos Nacional de Subvenciones "
        "(infosubvenciones.es) y búsqueda web por entidades. "
        "El Índice de Relevancia GREFA es orientativo: revisa siempre la convocatoria oficial."
    )
