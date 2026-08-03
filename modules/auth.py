"""Control de acceso con la cuenta de Google del equipo de GREFA.

Usa el login OIDC nativo de Streamlit (``st.login`` / ``st.user``). El acceso se
restringe por dominio de correo (por ejemplo, todo ``@grefa.org``) o por lista
blanca de direcciones concretas.

Si no hay bloque ``[auth]`` en ``.streamlit/secrets.toml``, la aplicación queda
abierta: así el desarrollo en local no necesita configurar OAuth.
"""

from __future__ import annotations

import os
from typing import Any

import streamlit as st

#: Dominio corporativo de GREFA. Se aplica cuando el login está activo y no se
#: ha configurado ninguna otra restricción, para que un despliegue mal
#: configurado nunca quede abierto a cualquier cuenta de Google.
DOMINIOS_POR_DEFECTO = ("grefa.org",)


def _secret(*ruta: str) -> Any:
    try:
        valor: Any = st.secrets
        for clave in ruta:
            if clave not in valor:
                return None
            valor = valor[clave]
        return valor
    except Exception:
        return None


def _lista(valor: Any) -> list[str]:
    if not valor:
        return []
    if isinstance(valor, str):
        return [parte.strip().lower() for parte in valor.split(",") if parte.strip()]
    return [str(parte).strip().lower() for parte in valor if str(parte).strip()]


def login_habilitado() -> bool:
    """Hay login si existe configuración OIDC en los secretos."""
    return bool(_secret("auth"))


def dominios_permitidos() -> list[str]:
    return _lista(_secret("access", "allowed_domains") or os.environ.get("GREFA_ALLOWED_DOMAINS"))


def correos_permitidos() -> list[str]:
    return _lista(_secret("access", "allowed_emails") or os.environ.get("GREFA_ALLOWED_EMAILS"))


def _autorizado(email: str) -> bool:
    dominios = dominios_permitidos()
    correos = correos_permitidos()
    if not dominios and not correos:
        dominios = list(DOMINIOS_POR_DEFECTO)
    email = email.lower()
    if email in correos:
        return True
    return any(email.endswith(f"@{dominio.lstrip('@')}") for dominio in dominios)


def _pantalla_login() -> None:
    st.markdown(
        """
        <div style="max-width:560px; margin:12vh auto 0 auto; text-align:center;">
            <h1 style="margin-bottom:0.3rem;">🦅 GREFA · Monitor de Licitaciones</h1>
            <p style="color:#5b6b62;">
                Herramienta interna de seguimiento de licitaciones públicas.<br>
                Accede con tu cuenta corporativa de GREFA para continuar.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    _, centro, _ = st.columns([1, 1, 1])
    with centro:
        if st.button("Iniciar sesión con Google", type="primary", width="stretch"):
            st.login()


def _pantalla_denegada(email: str) -> None:
    dominios = dominios_permitidos() or list(DOMINIOS_POR_DEFECTO)
    st.error(
        f"La cuenta **{email}** no tiene acceso a esta herramienta. "
        f"Entra con tu cuenta corporativa (@{dominios[0]}) o solicita el alta "
        "a la persona responsable del equipo."
    )
    if st.button("Cerrar sesión"):
        st.logout()


def requiere_acceso() -> dict[str, str] | None:
    """Bloquea la ejecución si el usuario no está autenticado y autorizado.

    Returns:
        Datos del usuario, o ``None`` si el login está desactivado.
    """
    if not login_habilitado():
        return None

    try:
        conectado = bool(st.user.is_logged_in)
    except Exception as exc:
        # Fallo cerrado: si el login está configurado pero no se puede comprobar
        # la sesión, se bloquea el acceso en lugar de abrir la aplicación.
        st.error(
            "No se puede verificar la sesión de usuario, así que el acceso queda "
            "bloqueado por seguridad. Revisa el bloque [auth] de los secretos y "
            f"que Authlib esté instalado. Detalle: {exc}"
        )
        st.stop()

    if not conectado:
        _pantalla_login()
        st.stop()

    email = str(getattr(st.user, "email", "") or "").lower()
    if not _autorizado(email):
        _pantalla_denegada(email)
        st.stop()

    return {
        "email": email,
        "nombre": str(getattr(st.user, "name", "") or email),
        "foto": str(getattr(st.user, "picture", "") or ""),
    }


def barra_usuario(usuario: dict[str, str] | None) -> None:
    """Pie de la barra lateral con la identidad y el botón de salir."""
    if not usuario:
        return
    st.sidebar.divider()
    st.sidebar.caption(f"Conectado como **{usuario['nombre']}**  \n{usuario['email']}")
    if st.sidebar.button("Cerrar sesión", width="stretch"):
        st.logout()
