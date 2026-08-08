"""Perfil reutilizable de GREFA (datos administrativos fijos)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from modules import sheets_store as store

LOGGER = logging.getLogger(__name__)

PERFIL_PATH = Path(__file__).resolve().parents[1] / "data" / "perfil_grefa.json"

CAMPOS_PERFIL: list[dict[str, str]] = [
    {"id": "razon_social", "label": "Razón social / entidad"},
    {"id": "nif", "label": "NIF / CIF"},
    {"id": "domicilio_social", "label": "Domicilio social"},
    {"id": "domicilio_notificaciones", "label": "Domicilio notificaciones"},
    {"id": "email", "label": "Email"},
    {"id": "telefono", "label": "Teléfono"},
    {"id": "representante_nombre", "label": "Representante (nombre)"},
    {"id": "representante_nif", "label": "NIF representante"},
    {"id": "representante_cargo", "label": "Cargo / poder"},
    {"id": "poderes_resumen", "label": "Poderes / escritura (resumen)"},
    {"id": "clasificacion", "label": "Clasificación empresarial"},
]

DEFAULT_PERFIL: dict[str, str] = {
    "razon_social": "GREFA (Grupo para la Recuperación de la Fauna Autóctona y su Hábitat)",
    "nif": "",
    "domicilio_social": "",
    "domicilio_notificaciones": "",
    "email": "",
    "telefono": "",
    "representante_nombre": "",
    "representante_nif": "",
    "representante_cargo": "",
    "poderes_resumen": "",
    "clasificacion": "",
}


def load_perfil() -> dict[str, str]:
    datos = dict(DEFAULT_PERFIL)
    if PERFIL_PATH.is_file():
        try:
            crudo = json.loads(PERFIL_PATH.read_text(encoding="utf-8"))
            if isinstance(crudo, dict):
                for k, v in crudo.items():
                    datos[str(k)] = str(v or "").strip()
        except Exception as exc:
            LOGGER.warning("No se pudo leer perfil GREFA: %s", exc)
    # Opcional: Config en Sheets
    if store.is_configured():
        try:
            from modules import sheets_historico

            raw = sheets_historico.get_config("perfil_grefa_json", "")
            if raw:
                crudo = json.loads(raw)
                if isinstance(crudo, dict):
                    for k, v in crudo.items():
                        if str(v or "").strip():
                            datos[str(k)] = str(v).strip()
        except Exception:
            pass
    return datos


def save_perfil(datos: dict[str, str]) -> Path:
    limpio = {k: str(datos.get(k) or "").strip() for k in DEFAULT_PERFIL}
    PERFIL_PATH.parent.mkdir(parents=True, exist_ok=True)
    PERFIL_PATH.write_text(
        json.dumps(limpio, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if store.is_configured():
        try:
            from modules import sheets_historico

            sheets_historico._escribir_config(
                "perfil_grefa_json",
                json.dumps(limpio, ensure_ascii=False),
            )
        except Exception as exc:
            LOGGER.warning("Perfil local OK; Sheets Config falló: %s", exc)
    return PERFIL_PATH


def aplicar_a_formulario(destino: dict[str, str], perfil: dict[str, str] | None = None) -> dict[str, str]:
    """Rellena huecos del formulario con el perfil (no pisa valores ya escritos)."""
    perfil = perfil or load_perfil()
    salida = dict(destino)
    for clave, valor in perfil.items():
        if not valor:
            continue
        actual = str(salida.get(clave) or "").strip()
        if not actual:
            salida[clave] = valor
    return salida
