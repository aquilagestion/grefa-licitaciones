"""Compartir publicación de licitaciones (PLACSP) o ayudas (BDNS)."""

from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import quote, unquote

import pandas as pd
import streamlit as st

try:
    from config.default_criteria import RELEVANCE_LEVELS
except Exception:  # pragma: no cover
    RELEVANCE_LEVELS = {
        "Alta": {"badge": "Oportunidad GREFA", "color": "#1B873F", "emoji": "🟢"},
        "Media": {"badge": "Revisar", "color": "#B58100", "emoji": "🟡"},
        "Baja": {"badge": "Descartable", "color": "#6B7280", "emoji": "⚪"},
    }


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


def _url_compartible(url: str) -> str:
    """Normaliza la URL para no doble-codificar %3D → %253D en mailto/WA."""
    u = (url or "").strip()
    if not u:
        return ""
    if "%" in u:
        try:
            u = unquote(u)
        except Exception:
            pass
    return u


def _fmt_importe(valor: Any) -> str:
    if valor is None:
        return "No publicado"
    try:
        if pd.isna(valor):
            return "No publicado"
    except Exception:
        pass
    try:
        num = float(valor)
    except (TypeError, ValueError):
        texto = str(valor).strip()
        return texto or "No publicado"
    return f"{num:,.2f} €".replace(",", "@").replace(".", ",").replace("@", ".")


def _fmt_fecha(valor: Any) -> str:
    if valor is None:
        return "—"
    try:
        if pd.isna(valor):
            return "—"
    except Exception:
        pass
    if isinstance(valor, str):
        return valor.strip() or "—"
    try:
        return pd.to_datetime(valor).strftime("%d/%m/%Y %H:%M")
    except (ValueError, TypeError):
        return str(valor)


def _lista_texto(valor: Any, *, limite: int = 8) -> str:
    if valor is None:
        return ""
    if isinstance(valor, (list, tuple)):
        items = [str(x).strip() for x in valor if str(x).strip()]
        return ", ".join(items[:limite])
    texto = str(valor).strip()
    return texto if texto and texto.lower() != "nan" else ""


def _asunto(fuente_label: str, titulo: str, expediente: str) -> str:
    base = f"GREFA · {fuente_label}: "
    resto = (titulo or expediente or "publicación").strip()
    max_resto = 90
    if len(resto) <= max_resto:
        return base + resto
    cortado = resto[: max_resto - 1].rsplit(" ", 1)[0]
    return base + (cortado or resto[: max_resto - 1]) + "…"


def _campos_desde_fila(
    fila: Any = None,
    *,
    fuente_label: str = "PLACSP",
    titulo: str = "",
    expediente: str = "",
    url: str = "",
) -> dict[str, str]:
    """Extrae los mismos campos visibles en la tarjeta de la app."""
    if fila is not None:
        titulo = titulo or _get(fila, "titulo", "title")
        expediente = expediente or _get(fila, "expediente", "id")
        url = url or _get(fila, "url", "enlace", "link")
        organo = _get(fila, "organo_contratacion", "organo")
        estado = _get(fila, "estado")
        ubicacion = _get(fila, "ubicacion")
        presupuesto = _fmt_importe(
            fila.get("presupuesto_sin_iva") if hasattr(fila, "get") else None
        )
        fecha = _fmt_fecha(
            fila.get("fecha_actualizacion") if hasattr(fila, "get") else None
        )
        fecha_limite = _fmt_fecha(
            fila.get("fecha_limite") if hasattr(fila, "get") else None
        )
        keywords = _lista_texto(
            fila.get("keywords_match") if hasattr(fila, "get") else None
        )
        cpvs = _lista_texto(fila.get("cpvs") if hasattr(fila, "get") else None)
        nif_organo = _get(fila, "nif_organo")
        adjudicatario = _get(fila, "adjudicatario")
        nif_adj = _get(fila, "nif_adjudicatario")
        nivel_admin = _get(fila, "nivel_admin")
        instrumento = _get(fila, "tipo_contrato")
        categoria = _get(fila, "categoria") or "Baja"
        badge = _get(fila, "badge")
        relevancia = _get(fila, "relevancia")
        justificacion = _get(fila, "justificacion")
    else:
        organo = estado = ubicacion = keywords = cpvs = ""
        nif_organo = adjudicatario = nif_adj = nivel_admin = instrumento = ""
        categoria = "Baja"
        badge = relevancia = justificacion = ""
        presupuesto = "No publicado"
        fecha = fecha_limite = "—"

    nivel = RELEVANCE_LEVELS.get(categoria, RELEVANCE_LEVELS.get("Baja", {}))
    if not badge:
        badge = str(nivel.get("badge") or categoria)
    emoji = str(nivel.get("emoji") or "⚪")
    color = str(nivel.get("color") or "#6B7280")
    if relevancia:
        try:
            relevancia = str(int(float(str(relevancia).replace("%", "").strip())))
        except ValueError:
            relevancia = str(relevancia).replace("%", "").strip()

    return {
        "fuente_label": fuente_label,
        "titulo": (titulo or "Publicación de interés GREFA").strip(),
        "expediente": (expediente or "").strip(),
        "url": _url_compartible(url),
        "organo": organo,
        "estado": estado,
        "ubicacion": ubicacion,
        "presupuesto": presupuesto,
        "fecha": fecha,
        "fecha_limite": fecha_limite,
        "keywords": keywords or "—",
        "cpvs": cpvs,
        "nif_organo": nif_organo,
        "adjudicatario": adjudicatario,
        "nif_adjudicatario": nif_adj,
        "nivel_admin": nivel_admin,
        "instrumento": instrumento,
        "badge": badge,
        "emoji": emoji,
        "color": color,
        "relevancia": relevancia,
        "justificacion": justificacion[:400] if justificacion else "",
        "etiqueta_enlace": "PLACSP" if fuente_label.upper() == "PLACSP" else fuente_label,
    }


def mensaje_tarjeta_texto(campos: dict[str, str], *, compacto: bool = False) -> str:
    """Tarjeta en texto plano (mismo contenido que la UI) para correo / WhatsApp."""
    c = campos
    cab = f"{c['emoji']} {c['badge']}"
    if c.get("relevancia"):
        cab += f" · {c['relevancia']}%"
    sep = "-" * 36
    lineas = [
        f"GREFA · {c['fuente_label']}",
        sep,
        cab,
    ]
    if c.get("fecha") and c["fecha"] not in ("—", "-", ""):
        lineas.append(f"Actualizada: {c['fecha']}")
    lineas.extend(["", c["titulo"], ""])

    if c.get("organo"):
        lineas.append(f"Órgano: {c['organo']}")

    def _guion(v: str) -> str:
        return v if v and v != "—" else "-"

    if c["fuente_label"].upper() == "BDNS":
        meta_imp = [
            f"Presupuesto: {c['presupuesto']}",
            f"Nivel: {_guion(c['nivel_admin'])}",
            f"Estado: {_guion(c['estado'])}",
        ]
        lineas.append(" · ".join(meta_imp))
        meta_bdns = [
            f"BDNS: {_guion(c['expediente'])}",
            f"Fin solicitud: {_guion(c['fecha_limite'])}",
            f"Instrumento: {_guion(c['instrumento'])}",
        ]
        lineas.append(" · ".join(meta_bdns))
    else:
        meta_imp = [
            f"Presupuesto (sin IVA): {c['presupuesto']}",
            f"Ubicación: {_guion(c['ubicacion'])}",
            f"Estado: {_guion(c['estado'])}",
        ]
        lineas.append(" · ".join(meta_imp))
        lineas.append(
            f"Expediente: {_guion(c['expediente'])} · Palabras clave: {c['keywords']}"
        )
        if c.get("nif_organo") or c.get("adjudicatario"):
            adj = c["adjudicatario"] or "-"
            if c.get("nif_adjudicatario"):
                adj = f"{adj} ({c['nif_adjudicatario']})"
            lineas.append(
                f"NIF órgano: {_guion(c['nif_organo'])} · Adjudicatario: {adj}"
            )
        if c.get("cpvs") and not compacto:
            lineas.append(f"CPV: {c['cpvs']}")

    if not compacto and c.get("justificacion"):
        lineas.extend(["", f"Motivo puntuación: {c['justificacion']}"])

    lineas.append("")
    if c.get("url"):
        lineas.append(f"Ver expediente en {c['etiqueta_enlace']}:")
        lineas.append(c["url"])
    lineas.append(sep)
    return "\n".join(lineas)


def mensaje_tarjeta_html(campos: dict[str, str]) -> str:
    """HTML autocontenido con el mismo aspecto aproximado que la tarjeta GREFA."""
    c = campos
    esc = html.escape
    badge = f"{c['emoji']} {esc(c['badge'])}"
    if c.get("relevancia"):
        badge += f" · {esc(c['relevancia'])}%"
    color = esc(c.get("color") or "#6B7280")
    filas_meta: list[str] = []
    if c.get("organo"):
        filas_meta.append(
            f"<p style='margin:4px 0;color:#4b5563;font-size:14px;'>"
            f"<strong style='color:#1f2937;'>Órgano:</strong> {esc(c['organo'])}</p>"
        )
    if c["fuente_label"].upper() == "BDNS":
        filas_meta.append(
            "<p style='margin:4px 0;color:#4b5563;font-size:14px;'>"
            f"<strong style='color:#1f2937;'>Presupuesto:</strong> {esc(c['presupuesto'])}"
            f" · <strong style='color:#1f2937;'>Nivel:</strong> {esc(c['nivel_admin'] or '—')}"
            f" · <strong style='color:#1f2937;'>Estado:</strong> {esc(c['estado'] or '—')}"
            "</p>"
        )
        filas_meta.append(
            "<p style='margin:4px 0;color:#4b5563;font-size:14px;'>"
            f"<strong style='color:#1f2937;'>BDNS:</strong> {esc(c['expediente'] or '—')}"
            f" · <strong style='color:#1f2937;'>Fin solicitud:</strong> {esc(c['fecha_limite'] or '—')}"
            f" · <strong style='color:#1f2937;'>Instrumento:</strong> {esc(c['instrumento'] or '—')}"
            "</p>"
        )
    else:
        filas_meta.append(
            "<p style='margin:4px 0;color:#4b5563;font-size:14px;'>"
            f"<strong style='color:#1f2937;'>Presupuesto (sin IVA):</strong> {esc(c['presupuesto'])}"
            f" · <strong style='color:#1f2937;'>Ubicación:</strong> {esc(c['ubicacion'] or '—')}"
            f" · <strong style='color:#1f2937;'>Estado:</strong> {esc(c['estado'] or '—')}"
            "</p>"
        )
        filas_meta.append(
            "<p style='margin:4px 0;color:#4b5563;font-size:14px;'>"
            f"<strong style='color:#1f2937;'>Expediente:</strong> {esc(c['expediente'] or '—')}"
            f" · <strong style='color:#1f2937;'>Palabras clave:</strong> {esc(c['keywords'])}"
            "</p>"
        )
        if c.get("cpvs"):
            filas_meta.append(
                "<p style='margin:4px 0;color:#4b5563;font-size:13px;'>"
                f"<strong style='color:#1f2937;'>CPV:</strong> {esc(c['cpvs'])}</p>"
            )

    enlace = ""
    if c.get("url"):
        u = esc(c["url"])
        enlace = (
            f"<p style='margin:14px 0 0 0;'>"
            f"<a href=\"{u}\" style='display:inline-block;background:#1B873F;color:#fff;"
            f"text-decoration:none;padding:10px 14px;border-radius:8px;font-weight:700;'>"
            f"Ver expediente en {esc(c['etiqueta_enlace'])} ↗</a></p>"
            f"<p style='margin:8px 0 0 0;color:#4b5563;font-size:12px;word-break:break-all;'>"
            f"{u}</p>"
        )

    fecha_html = ""
    if c.get("fecha") and c["fecha"] != "—":
        fecha_html = (
            f"<span style='color:#6b7280;font-size:12px;'>{esc(c['fecha'])}</span>"
        )

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>GREFA · {esc(c['fuente_label'])}</title></head>
<body style="margin:0;padding:16px;background:#f3f4f6;font-family:Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
  <div style="max-width:640px;margin:0 auto;background:#fff;border:1px solid #e2e6e3;
              border-left:6px solid {color};border-radius:10px;padding:16px 18px;
              box-shadow:0 1px 2px rgba(16,24,40,0.05);">
    <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;">
      <span style="display:inline-block;background:{color};color:#fff;padding:4px 10px;
                   border-radius:999px;font-size:12px;font-weight:700;">{badge}</span>
      {fecha_html}
    </div>
    <p style="margin:6px 0 0 0;color:#6b7280;font-size:12px;">GREFA · {esc(c['fuente_label'])}</p>
    <h2 style="margin:10px 0 8px 0;font-size:18px;line-height:1.35;color:#10241a;">
      {esc(c['titulo'])}
    </h2>
    {"".join(filas_meta)}
    {enlace}
  </div>
</body></html>
"""


def mensaje_compartir(
    *,
    titulo: str = "",
    expediente: str = "",
    url: str = "",
    fuente_label: str = "PLACSP",
    fila: Any = None,
    compacto: bool = False,
) -> str:
    """Texto listo para WhatsApp / email / Telegram (formato tarjeta)."""
    campos = _campos_desde_fila(
        fila,
        fuente_label=fuente_label,
        titulo=titulo,
        expediente=expediente,
        url=url,
    )
    return mensaje_tarjeta_texto(campos, compacto=compacto)


def enlace_whatsapp(texto: str) -> str:
    # wa.me tiene límite práctico de longitud de URL
    t = texto or ""
    if len(quote(t)) > 1800:
        t = re.sub(r"\nMotivo puntuación:.*", "", t, flags=re.DOTALL).strip()
        if len(quote(t)) > 1800:
            lineas = t.splitlines()
            t = "\n".join(lineas[:12] + ["…", lineas[-3], lineas[-2], lineas[-1]])
    return f"https://wa.me/?text={quote(t)}"


def enlace_email_mailto(asunto: str, cuerpo: str) -> str:
    """Cliente de correo local (puede fallar dentro del iframe del Space)."""
    return f"mailto:?subject={quote(asunto or '')}&body={quote(cuerpo or '')}"


def enlace_email_gmail(asunto: str, cuerpo: str) -> str:
    """Gmail web: funciona en Hugging Face / iframes (es https)."""
    # Gmail compose: body en texto; URLs del expediente se vuelven clicables.
    cuerpo_ok = cuerpo or ""
    if len(quote(cuerpo_ok)) > 6000:
        cuerpo_ok = re.sub(
            r"\nMotivo puntuación:.*?(?=\n🔗|\n─|\Z)",
            "",
            cuerpo_ok,
            flags=re.DOTALL,
        ).strip()
    return (
        "https://mail.google.com/mail/?view=cm&fs=1"
        f"&su={quote(asunto or '')}&body={quote(cuerpo_ok)}"
    )


def enlace_email_outlook(asunto: str, cuerpo: str) -> str:
    """Outlook web compose."""
    return (
        "https://outlook.office.com/mail/deeplink/compose"
        f"?subject={quote(asunto or '')}&body={quote(cuerpo or '')}"
    )


def enlace_email(asunto: str, cuerpo: str) -> str:
    return enlace_email_gmail(asunto, cuerpo)


def enlace_telegram(texto: str, url: str = "") -> str:
    return (
        "https://t.me/share/url"
        f"?url={quote(_url_compartible(url) or '')}&text={quote(texto or '')}"
    )


def meta_publicacion(fila: Any, *, fuente_label: str = "PLACSP") -> dict[str, str]:
    campos = _campos_desde_fila(fila, fuente_label=fuente_label)
    return {
        "titulo": campos["titulo"],
        "expediente": campos["expediente"],
        "url": campos["url"],
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
    campos = _campos_desde_fila(
        fila,
        fuente_label=fuente_label,
        titulo=titulo,
        expediente=expediente,
        url=url,
    )
    url = campos["url"]
    if not url:
        st.caption("Sin enlace público para compartir.")
        return

    texto = mensaje_tarjeta_texto(campos, compacto=False)
    texto_wa = mensaje_tarjeta_texto(campos, compacto=True)
    html_tarjeta = mensaje_tarjeta_html(campos)
    asunto = _asunto(fuente_label, campos["titulo"], campos["expediente"])

    with st.popover("📤 Compartir", width=width):
        st.caption(
            f"Se comparte la **tarjeta** completa + enlace al expediente en {fuente_label}."
        )
        st.code(url, language=None)
        c1, c2 = st.columns(2)
        with c1:
            st.link_button(
                "WhatsApp",
                enlace_whatsapp(texto_wa),
                width="stretch",
            )
            st.link_button(
                "Telegram",
                enlace_telegram(texto_wa, url),
                width="stretch",
            )
        with c2:
            st.link_button(
                "Gmail",
                enlace_email_gmail(asunto, texto),
                width="stretch",
                help="Abre Gmail con la tarjeta en el cuerpo y el enlace PLACSP/BDNS",
            )
            st.link_button(
                f"Abrir {fuente_label} ↗",
                url,
                width="stretch",
            )
        c3, c4 = st.columns(2)
        with c3:
            st.link_button(
                "Outlook",
                enlace_email_outlook(asunto, texto),
                width="stretch",
            )
        with c4:
            st.link_button(
                "App correo",
                enlace_email_mailto(asunto, texto),
                width="stretch",
                help="mailto: del PC. En el Space a veces no abre.",
            )
        st.caption(
            "Gmail/Outlook reciben la tarjeta en texto (mismo contenido que en la app). "
            "El enlace del expediente queda clicable. "
            "Si quieres el aspecto visual HTML, descarga o copia el bloque de abajo."
        )
        st.text_area(
            "Tarjeta (texto del correo)",
            value=texto,
            height=220,
            key=f"{key}_txt",
        )
        st.download_button(
            "⬇️ Descargar tarjeta HTML",
            data=html_tarjeta.encode("utf-8"),
            file_name=f"grefa_{fuente_label.lower()}_{(campos['expediente'] or 'pub')[:40].replace('/', '-')}.html",
            mime="text/html",
            key=f"{key}_dl_html",
            help="Ábrela o adjúntala al correo para ver el formato visual de tarjeta",
        )
        with st.expander("HTML de la tarjeta (copiar)"):
            st.code(html_tarjeta, language="html")


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
        campos = _campos_desde_fila(fila, fuente_label=fuente_label)
        if not campos["url"]:
            wa.append("")
            mail.append("")
            continue
        texto = mensaje_tarjeta_texto(campos, compacto=False)
        texto_wa = mensaje_tarjeta_texto(campos, compacto=True)
        asunto = _asunto(fuente_label, campos["titulo"], campos["expediente"])
        wa.append(enlace_whatsapp(texto_wa))
        mail.append(enlace_email_gmail(asunto, texto))
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
        display_text="✉️ Gmail",
        width="small",
    ),
    "Compartir WhatsApp": st.column_config.LinkColumn(
        "Compartir WhatsApp",
        display_text="📤 WhatsApp",
        width="small",
    ),
    "Compartir Email": st.column_config.LinkColumn(
        "Compartir Email",
        display_text="✉️ Gmail",
        width="small",
    ),
}
