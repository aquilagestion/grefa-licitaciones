"""Compartir publicación de licitaciones (PLACSP) o ayudas (BDNS)."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import pandas as pd
import streamlit as st


def _get(fila: Any, *claves: str, default: str = "") -> str:
    if fila is None:
        return default
    getter = fila.get if hasattr(fila, "get") else None
    for clave in claves:
        if getter:
            valor = getter(clave, None)
        else:
            try:
                valor = fila[clave]
            except Exception:
                valor = None
        if valor is not None and str(valor).strip() and str(valor).lower() != "nan":
            return str(valor).strip()
    return default


def mensaje_compartir(
    *,
    titulo: str = "",
    expediente: str = "",
    url: str = "",
    fuente_label: str = "PLACSP",
) -> str:
    """Texto listo para WhatsApp / email / Telegram."""
    tit = (titulo or "Publicación de interés GREFA").strip()
    exp = (expediente or "").strip()
    lineas = [f"GREFA · {fuente_label}", tit]
    if exp:
        lineas.append(f"Expediente / código: {exp}")
    if url:
        lineas.append(url)
    return "\n".join(lineas)


def enlace_whatsapp(texto: str) -> str:
    return f"https://wa.me/?text={quote(texto or '')}"


def enlace_email(asunto: str, cuerpo: str) -> str:
    return f"mailto:?subject={quote(asunto or '')}&body={quote(cuerpo or '')}"


def enlace_telegram(texto: str, url: str = "") -> str:
    return (
        "https://t.me/share/url"
        f"?url={quote(url or '')}&text={quote(texto or '')}"
    )


def meta_publicacion(fila: Any, *, fuente_label: str = "PLACSP") -> dict[str, str]:
    return {
        "titulo": _get(fila, "titulo", "title"),
        "expediente": _get(fila, "expediente", "id"),
        "url": _get(fila, "url", "enlace", "link"),
        "fuente_label": fuente_label,
    }


def render_compartir(
    fila: Any = None,
    *,
    key: str,
    fuente_label: str = "PLACSP",
    titulo: str = "",
    expediente: str = "",
    url: str = "",
    width: str = "stretch",
) -> None:
    """Botón/popover para compartir la publicación oficial."""
    if fila is not None:
        meta = meta_publicacion(fila, fuente_label=fuente_label)
        titulo = titulo or meta["titulo"]
        expediente = expediente or meta["expediente"]
        url = url or meta["url"]
    url = (url or "").strip()
    if not url:
        st.caption("Sin enlace público para compartir.")
        return

    texto = mensaje_compartir(
        titulo=titulo,
        expediente=expediente,
        url=url,
        fuente_label=fuente_label,
    )
    asunto = f"GREFA · {fuente_label}: {(titulo or expediente or 'publicación')[:80]}"

    with st.popover("📤 Compartir", width=width):
        st.caption(f"Publicación en {fuente_label}")
        st.code(url, language=None)
        c1, c2 = st.columns(2)
        with c1:
            st.link_button(
                "WhatsApp",
                enlace_whatsapp(texto),
                width="stretch",
            )
            st.link_button(
                "Telegram",
                enlace_telegram(texto, url),
                width="stretch",
            )
        with c2:
            st.link_button(
                "Email",
                enlace_email(asunto, texto),
                width="stretch",
            )
            st.link_button(
                f"Abrir {fuente_label} ↗",
                url,
                width="stretch",
            )
        st.text_area(
            "Texto para copiar",
            value=texto,
            height=110,
            key=f"{key}_txt",
            label_visibility="collapsed",
        )


def enriquecer_dataframe_compartir(
    df: pd.DataFrame,
    *,
    fuente_label: str = "PLACSP",
) -> pd.DataFrame:
    """Añade columnas de enlace WhatsApp / Email para vistas tabla."""
    if df is None or df.empty:
        return df
    salida = df.copy()
    wa: list[str] = []
    mail: list[str] = []
    for _, fila in salida.iterrows():
        meta = meta_publicacion(fila, fuente_label=fuente_label)
        if not meta["url"]:
            wa.append("")
            mail.append("")
            continue
        texto = mensaje_compartir(**meta)
        asunto = (
            f"GREFA · {fuente_label}: "
            f"{(meta['titulo'] or meta['expediente'] or 'publicación')[:80]}"
        )
        wa.append(enlace_whatsapp(texto))
        mail.append(enlace_email(asunto, texto))
    salida["compartir_whatsapp"] = wa
    salida["compartir_email"] = mail
    return salida


COLUMNAS_COMPARTIR = ("compartir_whatsapp", "compartir_email")

COLUMN_CONFIG_COMPARTIR = {
    "compartir_whatsapp": st.column_config.LinkColumn(
        "Compartir WhatsApp",
        display_text="📤 WhatsApp",
        width="small",
    ),
    "compartir_email": st.column_config.LinkColumn(
        "Compartir Email",
        display_text="✉️ Email",
        width="small",
    ),
    "Compartir WhatsApp": st.column_config.LinkColumn(
        "Compartir WhatsApp",
        display_text="📤 WhatsApp",
        width="small",
    ),
    "Compartir Email": st.column_config.LinkColumn(
        "Compartir Email",
        display_text="✉️ Email",
        width="small",
    ),
}
