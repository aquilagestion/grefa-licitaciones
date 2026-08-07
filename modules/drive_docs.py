"""Subida de documentos de preparación a Google Drive (cuenta de servicio)."""

from __future__ import annotations

import io
import logging
import mimetypes
import os
import re
from typing import Any

from modules import sheets_store as store

LOGGER = logging.getLogger(__name__)

DRIVE_SCOPES = (
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
)


class DriveDocsError(RuntimeError):
    """Fallo al subir o compartir un fichero en Drive."""


def _folder_id_configurado() -> str | None:
    valor = store._secret("sheets", "drive_folder_id") or os.environ.get(
        "GREFA_DRIVE_FOLDER_ID"
    )
    return str(valor).strip() if valor else None


def _drive_service():
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise DriveDocsError(
            "Falta google-api-python-client. Añádelo a requirements e instálalo."
        ) from exc
    creds = store._credentials()
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _sanitizar_nombre(nombre: str) -> str:
    limpio = re.sub(r'[<>:"/\\|?*]+', "_", str(nombre or "documento").strip())
    return limpio[:180] or "documento"


def upload_bytes(
    contenido: bytes,
    nombre: str,
    *,
    mime_type: str | None = None,
    carpeta_id: str | None = None,
) -> dict[str, str]:
    """Sube un fichero y lo comparte con enlace de lectura.

    Returns:
        ``{"id", "name", "webViewLink", "webContentLink"}``
    """
    if not contenido:
        raise DriveDocsError("El fichero está vacío.")

    from googleapiclient.http import MediaIoBaseUpload

    service = _drive_service()
    mime = mime_type or mimetypes.guess_type(nombre)[0] or "application/octet-stream"
    meta: dict[str, Any] = {"name": _sanitizar_nombre(nombre)}
    padre = carpeta_id or _folder_id_configurado()
    if padre:
        meta["parents"] = [padre]

    media = MediaIoBaseUpload(io.BytesIO(contenido), mimetype=mime, resumable=False)
    try:
        creado = (
            service.files()
            .create(body=meta, media_body=media, fields="id,name,webViewLink,webContentLink")
            .execute()
        )
        fid = creado["id"]
        service.permissions().create(
            fileId=fid,
            body={"type": "anyone", "role": "reader"},
            fields="id",
        ).execute()
        fresco = (
            service.files()
            .get(fileId=fid, fields="id,name,webViewLink,webContentLink")
            .execute()
        )
        return {
            "id": fresco.get("id") or fid,
            "name": fresco.get("name") or nombre,
            "webViewLink": fresco.get("webViewLink") or "",
            "webContentLink": fresco.get("webContentLink") or "",
        }
    except Exception as exc:
        raise DriveDocsError(f"No se pudo subir a Drive: {exc}") from exc
