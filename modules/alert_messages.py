"""Textos de aviso compartidos (email al espacio Chat, webhook, etc.)."""

from __future__ import annotations

from typing import Any


def format_nuevas_alta_email(
    nuevas: list[dict[str, Any]],
    *,
    app_url: str = "",
    total_alta: int = 0,
) -> tuple[str, str]:
    """Asunto y cuerpo en texto plano para email al espacio de Google Chat."""
    n = len(nuevas)
    asunto = f"GREFA: {n} nueva(s) oportunidad(es) Alta"
    lineas = [
        f"GREFA · Licitaciones — {n} nueva(s) oportunidad(es) Alta",
        "",
    ]
    if total_alta:
        lineas.append(f"Total Alta en el monitor: {total_alta}")
        lineas.append("")
    for fila in nuevas[:8]:
        titulo = str(fila.get("titulo") or "")[:90]
        exp = str(fila.get("expediente") or "—")
        rel = fila.get("relevancia", "")
        url = str(fila.get("url") or "").strip()
        if url:
            lineas.append(f"• {exp} ({rel} %) — {titulo}")
            lineas.append(f"  {url}")
        else:
            lineas.append(f"• {exp} ({rel} %) — {titulo}")
    if n > 8:
        lineas.append(f"… y {n - 8} más.")
    if app_url:
        lineas.extend(["", f"Monitor GREFA: {app_url}"])
    return asunto, "\n".join(lineas)


def format_nuevas_alta_chat_webhook(
    nuevas: list[dict[str, Any]],
    *,
    app_url: str = "",
    total_alta: int = 0,
) -> str:
    """Mensaje con markdown ligero para webhook de Google Chat."""
    lineas = [f"🦅 *GREFA · Licitaciones* — {len(nuevas)} nueva(s) oportunidad(es) *Alta*"]
    if total_alta:
        lineas.append(f"Total Alta en el monitor: {total_alta}")
    lineas.append("")
    for fila in nuevas[:8]:
        titulo = str(fila.get("titulo") or "")[:90]
        exp = str(fila.get("expediente") or "—")
        rel = fila.get("relevancia", "")
        lineas.append(f"• *{exp}* ({rel} %) — {titulo}")
    if len(nuevas) > 8:
        lineas.append(f"… y {len(nuevas) - 8} más.")
    if app_url:
        lineas.extend(["", f"<{app_url}|Abrir monitor GREFA>"])
    return "\n".join(lineas)
