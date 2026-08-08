"""Subida de documentos de preparación a Google Drive (cuenta de servicio).

Carpeta raíz (por defecto GREFA):
https://drive.google.com/drive/folders/13CfLk_CQx1bf4XIZOWFAkQKLUbvPi3KZ

Debe estar compartida como *Editor* con:
licitacionesplacsp@licitacionesplacsp-504412.iam.gserviceaccount.com

Por cada licitación se crea (si no existe) una subcarpeta:
``{expediente} — {órgano / contratista}``
"""

from __future__ import annotations

import io
import logging
import mimetypes
import os
import re
from typing import Any

from modules import sheets_store as store

LOGGER = logging.getLogger(__name__)

#: Carpeta raíz donde GREFA guarda la documentación de ofertas.
DEFAULT_ROOT_FOLDER_ID = "13CfLk_CQx1bf4XIZOWFAkQKLUbvPi3KZ"

FOLDER_MIME = "application/vnd.google-apps.folder"

# Caché en proceso: padre|nombre → id
_CARPETA_CACHE: dict[str, str] = {}


class DriveDocsError(RuntimeError):
    """Fallo al subir o compartir un fichero en Drive."""


def _folder_id_configurado() -> str:
    valor = store._secret("sheets", "drive_folder_id") or os.environ.get(
        "GREFA_DRIVE_FOLDER_ID"
    )
    if valor and str(valor).strip():
        return str(valor).strip()
    return DEFAULT_ROOT_FOLDER_ID


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
    limpio = re.sub(r'[<>:"/\\|?*\n\r\t]+', "_", str(nombre or "").strip())
    limpio = re.sub(r"\s+", " ", limpio).strip(" ._")
    return limpio[:160] or ""


def nombre_carpeta_expediente(expediente: str, organo: str = "") -> str:
    """Nombre de subcarpeta: expediente — órgano/contratista."""
    exp = _sanitizar_nombre(expediente) or "sin-expediente"
    org = _sanitizar_nombre(organo)
    if org:
        return f"{exp} — {org}"[:180]
    return exp[:180]


def _escape_drive_query(valor: str) -> str:
    return str(valor).replace("\\", "\\\\").replace("'", "\\'")


def ensure_subcarpeta(
    nombre: str,
    *,
    padre_id: str | None = None,
    service: Any | None = None,
) -> dict[str, str]:
    """Crea o reutiliza una subcarpeta bajo la carpeta raíz configurada."""
    nombre = _sanitizar_nombre(nombre) or "sin-nombre"
    # Restaurar guión tipográfico en el nombre final (sanitizar no lo quita)
    nombre_mostrar = nombre
    padre = (padre_id or _folder_id_configurado()).strip()
    cache_key = f"{padre}|{nombre_mostrar.lower()}"
    if cache_key in _CARPETA_CACHE:
        fid = _CARPETA_CACHE[cache_key]
        return {
            "id": fid,
            "name": nombre_mostrar,
            "webViewLink": f"https://drive.google.com/drive/folders/{fid}",
        }

    svc = service or _drive_service()
    consulta = (
        f"name = '{_escape_drive_query(nombre_mostrar)}' and "
        f"mimeType = '{FOLDER_MIME}' and "
        f"'{padre}' in parents and trashed = false"
    )
    try:
        hallados = (
            svc.files()
            .list(
                q=consulta,
                spaces="drive",
                fields="files(id,name,webViewLink)",
                pageSize=5,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        files = hallados.get("files") or []
        if files:
            fid = files[0]["id"]
            _CARPETA_CACHE[cache_key] = fid
            return {
                "id": fid,
                "name": files[0].get("name") or nombre_mostrar,
                "webViewLink": files[0].get("webViewLink")
                or f"https://drive.google.com/drive/folders/{fid}",
            }

        creado = (
            svc.files()
            .create(
                body={
                    "name": nombre_mostrar,
                    "mimeType": FOLDER_MIME,
                    "parents": [padre],
                },
                fields="id,name,webViewLink",
                supportsAllDrives=True,
            )
            .execute()
        )
        fid = creado["id"]
        _CARPETA_CACHE[cache_key] = fid
        return {
            "id": fid,
            "name": creado.get("name") or nombre_mostrar,
            "webViewLink": creado.get("webViewLink")
            or f"https://drive.google.com/drive/folders/{fid}",
        }
    except Exception as exc:
        raise DriveDocsError(
            "No se pudo crear/abrir la subcarpeta en Drive. "
            "Comparte la carpeta raíz como Editor con "
            "licitacionesplacsp@licitacionesplacsp-504412.iam.gserviceaccount.com. "
            f"Detalle: {exc}"
        ) from exc


def ensure_carpeta_licitacion(
    expediente: str,
    organo: str = "",
    *,
    padre_id: str | None = None,
    service: Any | None = None,
) -> dict[str, str]:
    """Subcarpeta ``{expediente} — {órgano}`` bajo la raíz GREFA."""
    # No pasar por _sanitizar completo el compuesto: conservar " — "
    exp = _sanitizar_nombre(expediente) or "sin-expediente"
    org = _sanitizar_nombre(organo)
    nombre = f"{exp} — {org}"[:180] if org else exp[:180]
    return ensure_subcarpeta(nombre, padre_id=padre_id, service=service)


def upload_bytes(
    contenido: bytes,
    nombre: str,
    *,
    mime_type: str | None = None,
    carpeta_id: str | None = None,
    expediente: str = "",
    organo: str = "",
) -> dict[str, str]:
    """Sube un fichero a la subcarpeta del expediente (o a ``carpeta_id``).

    Returns:
        ``{"id", "name", "webViewLink", "webContentLink", "folderId", "folderLink"}``
    """
    if not contenido:
        raise DriveDocsError("El fichero está vacío.")

    from googleapiclient.http import MediaIoBaseUpload

    service = _drive_service()
    if carpeta_id:
        padre = carpeta_id
        folder_link = f"https://drive.google.com/drive/folders/{padre}"
        folder_id = padre
    elif expediente or organo:
        carpeta = ensure_carpeta_licitacion(
            expediente, organo, service=service
        )
        padre = carpeta["id"]
        folder_link = carpeta.get("webViewLink") or f"https://drive.google.com/drive/folders/{padre}"
        folder_id = padre
    else:
        padre = _folder_id_configurado()
        folder_link = f"https://drive.google.com/drive/folders/{padre}"
        folder_id = padre

    mime = mime_type or mimetypes.guess_type(nombre)[0] or "application/octet-stream"
    meta: dict[str, Any] = {
        "name": _sanitizar_nombre(nombre) or "documento",
        "parents": [padre],
    }
    media = MediaIoBaseUpload(io.BytesIO(contenido), mimetype=mime, resumable=False)
    try:
        creado = (
            service.files()
            .create(
                body=meta,
                media_body=media,
                fields="id,name,webViewLink,webContentLink",
                supportsAllDrives=True,
            )
            .execute()
        )
        fid = creado["id"]
        fresco = (
            service.files()
            .get(
                fileId=fid,
                fields="id,name,webViewLink,webContentLink",
                supportsAllDrives=True,
            )
            .execute()
        )
        return {
            "id": fresco.get("id") or fid,
            "name": fresco.get("name") or nombre,
            "webViewLink": fresco.get("webViewLink") or "",
            "webContentLink": fresco.get("webContentLink") or "",
            "folderId": folder_id,
            "folderLink": folder_link,
        }
    except Exception as exc:
        raise DriveDocsError(
            "No se pudo subir a Drive. Comprueba que la carpeta esté compartida "
            "como Editor con licitacionesplacsp@licitacionesplacsp-504412.iam.gserviceaccount.com. "
            f"Detalle: {exc}"
        ) from exc


def download_bytes(file_id: str) -> bytes:
    """Descarga el contenido binario de un fichero de Drive por ID."""
    if not file_id:
        raise DriveDocsError("Falta file_id de Drive.")
    from googleapiclient.http import MediaIoBaseDownload

    service = _drive_service()
    buf = io.BytesIO()
    try:
        peticion = service.files().get_media(fileId=file_id, supportsAllDrives=True)
        downloader = MediaIoBaseDownload(buf, peticion)
        hecho = False
        while not hecho:
            _status, hecho = downloader.next_chunk()
        return buf.getvalue()
    except Exception as exc:
        raise DriveDocsError(f"No se pudo descargar de Drive ({file_id}): {exc}") from exc


def file_id_desde_enlace(enlace: str) -> str:
    """Extrae el ID de un enlace Drive (file/d/ID o open?id=)."""
    texto = str(enlace or "").strip()
    if not texto:
        return ""
    m = re.search(r"/file/d/([^/]+)", texto)
    if m:
        return m.group(1)
    m = re.search(r"[?&]id=([^&]+)", texto)
    if m:
        return m.group(1)
    if re.fullmatch(r"[\w-]{10,}", texto):
        return texto
    return ""
