"""Persistencia de formularios/borradores del asistente (Sheets + Drive)."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from modules import drive_docs, sheets_store as store

LOGGER = logging.getLogger(__name__)

ASISTENTE_SHEET = "AsistenteDocs"
ASISTENTE_HEADERS = [
    "ID Expediente",
    "Enlace",
    "Título",
    "Órgano",
    "Bloque",
    "Datos JSON",
    "Formato JSON",
    "Exigencias Drive",
    "Borrador Drive",
    "Verificación Drive",
    "Paquete Drive",
    "Actualizado",
]

BLOQUES = ("admin", "eco", "tec", "paquete", "revision")
LOCAL_DIR = Path(__file__).resolve().parents[1] / "data" / "asistente"
VERSIONS_DIR = LOCAL_DIR / "versions"
DOCS_DIR = LOCAL_DIR / "docs"
SESIONES_DIR = LOCAL_DIR / "sesiones"
MAX_VERSIONES = 25
MAX_SESIONES = 40

ESTADOS_REVISION = (
    "Borrador",
    "En revisión",
    "Con observaciones",
    "Aprobado interno",
    "Listo para presentar",
    "Presentada",
)


class AsistenteStoreError(RuntimeError):
    """Error al guardar/cargar el asistente."""


def _clave(expediente: str, enlace: str = "") -> str:
    return store._clave(expediente, enlace)


def _sanitizar_exp(expediente: str) -> str:
    limpio = re.sub(r"[^\w.\-]+", "_", str(expediente or "").strip())
    return (limpio or "sin_expediente")[:80]


def _local_path(expediente: str, enlace: str, bloque: str) -> Path:
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    clave = re.sub(r"[^\w]+", "_", _clave(expediente, enlace))[:60]
    return LOCAL_DIR / f"{clave}_{bloque}.json"


def _guardar_local(expediente: str, enlace: str, bloque: str, payload: dict[str, Any]) -> Path:
    ruta = _local_path(expediente, enlace, bloque)
    ruta.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return ruta


def _cargar_local(expediente: str, enlace: str, bloque: str) -> dict[str, Any] | None:
    ruta = _local_path(expediente, enlace, bloque)
    if not ruta.is_file():
        return None
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except Exception:
        return None


def _versions_path(expediente: str, enlace: str, bloque: str) -> Path:
    VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
    clave = re.sub(r"[^\w]+", "_", _clave(expediente, enlace))[:60]
    return VERSIONS_DIR / f"{clave}_{bloque}_versions.json"


def _cargar_indice_versiones(expediente: str, enlace: str, bloque: str) -> list[dict[str, Any]]:
    ruta = _versions_path(expediente, enlace, bloque)
    if not ruta.is_file():
        return []
    try:
        data = json.loads(ruta.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _guardar_indice_versiones(
    expediente: str, enlace: str, bloque: str, versiones: list[dict[str, Any]]
) -> None:
    ruta = _versions_path(expediente, enlace, bloque)
    ruta.write_text(json.dumps(versiones[:MAX_VERSIONES], ensure_ascii=False, indent=2), encoding="utf-8")


def _contenido_version_path(version_id: str) -> Path:
    VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
    seguro = re.sub(r"[^\w.\-]+", "_", version_id)[:80]
    return VERSIONS_DIR / f"{seguro}.md"


def registrar_version_borrador(
    *,
    expediente: str,
    enlace: str = "",
    bloque: str,
    borrador: str,
    etiqueta: str = "",
    organo: str = "",
    subir_drive: bool = True,
) -> dict[str, Any] | None:
    """Guarda una versión del borrador (local; Drive opcional)."""
    texto = (borrador or "").strip()
    if not texto or bloque not in BLOQUES:
        return None
    # Evita duplicar si es idéntico a la última versión
    previas = _cargar_indice_versiones(expediente, enlace, bloque)
    if previas and (previas[0].get("sha") == _sha_corto(texto)):
        return previas[0]

    momento = datetime.now()
    version_id = (
        f"{_sanitizar_exp(expediente)}_{bloque}_"
        f"{momento.strftime('%Y%m%d_%H%M%S')}_{_sha_corto(texto)}"
    )
    ruta_md = _contenido_version_path(version_id)
    ruta_md.write_text(texto, encoding="utf-8")

    link_drive = ""
    if subir_drive and store.is_configured():
        link_drive = _subir_texto_drive(
            texto,
            f"{version_id}.md",
            expediente=expediente,
            organo=organo,
        )

    entrada = {
        "id": version_id,
        "bloque": bloque,
        "expediente": expediente,
        "enlace": enlace or "",
        "timestamp": momento.strftime("%d/%m/%Y %H:%M:%S"),
        "etiqueta": (etiqueta or "").strip()[:120],
        "chars": len(texto),
        "sha": _sha_corto(texto),
        "ruta_local": str(ruta_md.name),
        "drive": link_drive,
    }
    previas.insert(0, entrada)
    # Limpia ficheros locales de versiones descartadas
    for vieja in previas[MAX_VERSIONES:]:
        try:
            _contenido_version_path(str(vieja.get("id") or "")).unlink(missing_ok=True)
        except Exception:
            pass
    _guardar_indice_versiones(expediente, enlace, bloque, previas[:MAX_VERSIONES])
    return entrada


def _sha_corto(texto: str) -> str:
    import hashlib

    return hashlib.sha1(texto.encode("utf-8")).hexdigest()[:12]


def listar_versiones(
    *,
    expediente: str,
    enlace: str = "",
    bloque: str,
) -> list[dict[str, Any]]:
    return _cargar_indice_versiones(expediente, enlace, bloque)


def cargar_version(
    *,
    expediente: str,
    enlace: str = "",
    bloque: str,
    version_id: str,
) -> str:
    """Devuelve el markdown de una versión (local o Drive)."""
    for entrada in _cargar_indice_versiones(expediente, enlace, bloque):
        if str(entrada.get("id")) != str(version_id):
            continue
        ruta = _contenido_version_path(str(version_id))
        if ruta.is_file():
            return ruta.read_text(encoding="utf-8")
        if entrada.get("drive"):
            return _leer_texto_drive(str(entrada["drive"]))
    # Intento directo por id
    ruta = _contenido_version_path(version_id)
    if ruta.is_file():
        return ruta.read_text(encoding="utf-8")
    return ""


def _subir_texto_drive(
    texto: str,
    nombre: str,
    *,
    expediente: str,
    organo: str,
) -> str:
    if not texto.strip():
        return ""
    try:
        subido = drive_docs.upload_bytes(
            texto.encode("utf-8"),
            nombre,
            mime_type="text/markdown; charset=utf-8",
            expediente=expediente,
            organo=organo,
        )
        return subido.get("webViewLink") or subido.get("id") or ""
    except Exception as exc:
        LOGGER.warning("No se pudo subir %s a Drive: %s", nombre, exc)
        return ""


def _leer_texto_drive(enlace_o_id: str) -> str:
    if not enlace_o_id:
        return ""
    fid = drive_docs.file_id_desde_enlace(enlace_o_id)
    if not fid:
        return ""
    try:
        return drive_docs.download_bytes(fid).decode("utf-8", errors="replace")
    except Exception as exc:
        LOGGER.warning("No se pudo leer Drive %s: %s", enlace_o_id, exc)
        return ""


def _docs_bloque_dir(expediente: str, enlace: str, bloque: str) -> Path:
    clave = re.sub(r"[^\w]+", "_", _clave(expediente, enlace))[:60]
    ruta = DOCS_DIR / f"{clave}_{bloque}"
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


def _sesiones_index_path(expediente: str, enlace: str, bloque: str) -> Path:
    SESIONES_DIR.mkdir(parents=True, exist_ok=True)
    clave = re.sub(r"[^\w]+", "_", _clave(expediente, enlace))[:60]
    return SESIONES_DIR / f"{clave}_{bloque}_sesiones.json"


def persistir_docs_apoyo(
    docs: list[dict[str, Any]] | None,
    *,
    expediente: str,
    enlace: str = "",
    bloque: str,
    organo: str = "",
) -> list[dict[str, Any]]:
    """Guarda binarios en local (y Drive si hay) y devuelve metadatos sin bytes."""
    salida: list[dict[str, Any]] = []
    if not docs:
        return salida
    carpeta = _docs_bloque_dir(expediente, enlace, bloque)
    for i, doc in enumerate(docs):
        if not isinstance(doc, dict):
            continue
        nombre = str(doc.get("nombre") or f"documento_{i + 1}.bin")
        seguro = re.sub(r"[^\w.\-]+", "_", nombre)[:120] or f"doc_{i + 1}.bin"
        datos = doc.get("bytes") or b""
        local_path = ""
        drive_link = ""
        if datos:
            ruta = carpeta / seguro
            try:
                ruta.write_bytes(datos)
                local_path = str(ruta)
            except Exception as exc:
                LOGGER.warning("No se pudo guardar doc local %s: %s", nombre, exc)
            if store.is_configured():
                try:
                    subido = drive_docs.upload_bytes(
                        datos,
                        f"{_sanitizar_exp(expediente)}_{bloque}_{seguro}",
                        expediente=expediente,
                        organo=organo,
                    )
                    drive_link = subido.get("webViewLink") or ""
                except Exception as exc:
                    LOGGER.warning("No se pudo subir doc apoyo a Drive: %s", exc)
        elif doc.get("local_path") and Path(str(doc["local_path"])).is_file():
            local_path = str(doc["local_path"])
            drive_link = str(doc.get("drive") or "")
        elif doc.get("drive"):
            drive_link = str(doc.get("drive") or "")
            local_path = str(doc.get("local_path") or "")

        salida.append(
            {
                "nombre": nombre,
                "tipo": str(doc.get("tipo") or "APOYO"),
                "campo_id": str(doc.get("campo_id") or ""),
                "campo_label": str(doc.get("campo_label") or ""),
                "comprobacion": str(doc.get("comprobacion") or "")[:20000],
                "local_path": local_path,
                "drive": drive_link,
            }
        )
    return salida


def hidratar_docs_apoyo(meta: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Recupera bytes desde disco local o Drive a partir de metadatos."""
    salida: list[dict[str, Any]] = []
    for doc in meta or []:
        if not isinstance(doc, dict):
            continue
        item = dict(doc)
        datos = b""
        ruta = str(doc.get("local_path") or "")
        if ruta and Path(ruta).is_file():
            try:
                datos = Path(ruta).read_bytes()
            except Exception:
                datos = b""
        if not datos and doc.get("drive"):
            fid = drive_docs.file_id_desde_enlace(str(doc["drive"]))
            if fid:
                try:
                    datos = drive_docs.download_bytes(fid)
                except Exception as exc:
                    LOGGER.warning("No se pudo descargar doc apoyo: %s", exc)
        if datos:
            item["bytes"] = datos
        salida.append(item)
    return salida


def registrar_sesion_borrador(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Guarda una foto completa del borrador de sesión (recuperable)."""
    if not isinstance(payload, dict):
        return None
    bloque = str(payload.get("bloque") or "")
    exp = str(payload.get("expediente") or "").strip() or "sin-expediente"
    enlace = str(payload.get("enlace") or "")
    if bloque not in BLOQUES:
        return None

    momento = datetime.now()
    # Snapshot sin bytes crudos
    snap = {
        k: v
        for k, v in payload.items()
        if k not in {"aviso_sheets"}
    }
    # docs_apoyo ya debe ir sin bytes
    docs = []
    for d in snap.get("docs_apoyo") or []:
        if isinstance(d, dict):
            docs.append({k: v for k, v in d.items() if k != "bytes"})
    snap["docs_apoyo"] = docs

    blob = json.dumps(snap, ensure_ascii=False, sort_keys=True)
    sha = _sha_corto(blob)
    indice = []
    ruta_idx = _sesiones_index_path(exp, enlace, bloque)
    if ruta_idx.is_file():
        try:
            indice = json.loads(ruta_idx.read_text(encoding="utf-8"))
            if not isinstance(indice, list):
                indice = []
        except Exception:
            indice = []
    if indice and indice[0].get("sha") == sha:
        return indice[0]

    version_id = (
        f"{_sanitizar_exp(exp)}_{bloque}_sesion_"
        f"{momento.strftime('%Y%m%d_%H%M%S')}_{sha}"
    )
    SESIONES_DIR.mkdir(parents=True, exist_ok=True)
    ruta_snap = SESIONES_DIR / f"{version_id}.json"
    ruta_snap.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")

    entrada = {
        "id": version_id,
        "bloque": bloque,
        "expediente": exp,
        "enlace": enlace,
        "timestamp": momento.strftime("%d/%m/%Y %H:%M:%S"),
        "sha": sha,
        "tiene_borrador": bool(str(snap.get("borrador") or "").strip()),
        "tiene_exigencias": bool(str(snap.get("exigencias") or "").strip()),
        "n_docs": len(docs),
        "n_campos": sum(
            1
            for k, v in (snap.get("datos") or {}).items()
            if v and not str(k).startswith("_")
        ),
        "ruta_local": ruta_snap.name,
    }
    indice.insert(0, entrada)
    for vieja in indice[MAX_SESIONES:]:
        try:
            (SESIONES_DIR / str(vieja.get("ruta_local") or "")).unlink(missing_ok=True)
        except Exception:
            pass
    ruta_idx.write_text(
        json.dumps(indice[:MAX_SESIONES], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return entrada


def listar_sesiones(
    *,
    expediente: str,
    enlace: str = "",
    bloque: str,
) -> list[dict[str, Any]]:
    ruta = _sesiones_index_path(expediente, enlace, bloque)
    if not ruta.is_file():
        return []
    try:
        data = json.loads(ruta.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def cargar_sesion(
    *,
    expediente: str,
    enlace: str = "",
    bloque: str,
    sesion_id: str,
) -> dict[str, Any] | None:
    """Carga un snapshot de sesión y rehidrata documentos aportados."""
    for entrada in listar_sesiones(expediente=expediente, enlace=enlace, bloque=bloque):
        if str(entrada.get("id")) != str(sesion_id):
            continue
        ruta = SESIONES_DIR / str(entrada.get("ruta_local") or f"{sesion_id}.json")
        if not ruta.is_file():
            ruta = SESIONES_DIR / f"{sesion_id}.json"
        if not ruta.is_file():
            return None
        try:
            payload = json.loads(ruta.read_text(encoding="utf-8"))
        except Exception:
            return None
        if isinstance(payload, dict):
            payload["docs_apoyo"] = hidratar_docs_apoyo(payload.get("docs_apoyo") or [])
        return payload
    ruta = SESIONES_DIR / f"{sesion_id}.json"
    if ruta.is_file():
        try:
            payload = json.loads(ruta.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                payload["docs_apoyo"] = hidratar_docs_apoyo(
                    payload.get("docs_apoyo") or []
                )
            return payload
        except Exception:
            return None
    return None


def save_bloque(
    *,
    expediente: str,
    enlace: str = "",
    titulo: str = "",
    organo: str = "",
    bloque: str,
    datos: dict[str, str] | None = None,
    formato: dict[str, Any] | None = None,
    exigencias: str = "",
    borrador: str = "",
    verificacion: str = "",
    paquete: str = "",
    docs_apoyo: list[dict[str, Any]] | None = None,
    modelos: dict[str, Any] | None = None,
    hoja_id: str | None = None,
) -> dict[str, Any]:
    """Guarda un bloque (admin/eco/tec/paquete) en local y, si hay Sheets, en la nube.

    Cada guardado actualiza el borrador actual y añade una sesión recuperable.
    """
    if bloque not in BLOQUES:
        raise AsistenteStoreError(f"Bloque no válido: {bloque}")

    momento = datetime.now().strftime("%d/%m/%Y %H:%M")
    exp = (expediente or "").strip() or "sin-expediente"
    docs_meta = persistir_docs_apoyo(
        docs_apoyo,
        expediente=exp,
        enlace=enlace,
        bloque=bloque,
        organo=organo,
    )
    payload = {
        "expediente": exp,
        "enlace": enlace or "",
        "titulo": titulo or "",
        "organo": organo or "",
        "bloque": bloque,
        "datos": datos or {},
        "formato": formato or {},
        "exigencias": exigencias or "",
        "borrador": borrador or "",
        "verificacion": verificacion or "",
        "paquete": paquete or "",
        "docs_apoyo": docs_meta,
        "modelos": modelos or {},
        "actualizado": momento,
        "links": {},
    }

    # Local siempre (fallback sin Sheets) — borrador actual recuperable
    _guardar_local(exp, enlace, bloque, payload)

    # Histórico de versiones del texto de borrador/paquete
    texto_version = (paquete if bloque == "paquete" else borrador) or ""
    if texto_version.strip() and bloque in {"admin", "eco", "tec", "paquete"}:
        try:
            ver = registrar_version_borrador(
                expediente=exp,
                enlace=enlace,
                bloque=bloque,
                borrador=texto_version,
                etiqueta=titulo or bloque,
                organo=organo,
                subir_drive=store.is_configured(),
            )
            if ver:
                payload["ultima_version_id"] = ver.get("id")
        except Exception as exc:
            LOGGER.warning("No se pudo registrar versión: %s", exc)

    # Snapshot de sesión (datos + docs + exigencias + borrador…)
    try:
        ses = registrar_sesion_borrador(payload)
        if ses:
            payload["ultima_sesion_id"] = ses.get("id")
            _guardar_local(exp, enlace, bloque, payload)
    except Exception as exc:
        LOGGER.warning("No se pudo registrar sesión de borrador: %s", exc)

    links: dict[str, str] = {}
    if store.is_configured():
        base = _sanitizar_exp(exp)
        if exigencias:
            links["exigencias"] = _subir_texto_drive(
                exigencias,
                f"{base}_{bloque}_exigencias.md",
                expediente=exp,
                organo=organo,
            )
        if borrador:
            links["borrador"] = _subir_texto_drive(
                borrador,
                f"{base}_{bloque}_borrador.md",
                expediente=exp,
                organo=organo,
            )
        if verificacion:
            links["verificacion"] = _subir_texto_drive(
                verificacion,
                f"{base}_{bloque}_verificacion.md",
                expediente=exp,
                organo=organo,
            )
        if paquete:
            links["paquete"] = _subir_texto_drive(
                paquete,
                f"{base}_paquete_final.md",
                expediente=exp,
                organo=organo,
            )
        payload["links"] = links
        _guardar_local(exp, enlace, bloque, payload)

        try:
            hoja = store.get_spreadsheet(hoja_id)
            pestana = store._worksheet(hoja, ASISTENTE_SHEET, ASISTENTE_HEADERS)
            # Incluye metadatos de docs en el JSON de datos (sin bytes)
            datos_nube = dict(datos or {})
            datos_nube["_docs_apoyo_meta"] = docs_meta
            if payload.get("ultima_sesion_id"):
                datos_nube["_ultima_sesion_id"] = payload["ultima_sesion_id"]
            fila = [
                exp,
                enlace or "",
                titulo or "",
                organo or "",
                bloque,
                json.dumps(datos_nube, ensure_ascii=False)[:45000],
                json.dumps(formato or {}, ensure_ascii=False)[:4000],
                links.get("exigencias", ""),
                links.get("borrador", ""),
                links.get("verificacion", ""),
                links.get("paquete", ""),
                momento,
            ]
            clave_obj = _clave(exp, enlace)
            registros = pestana.get_all_records()
            actualizado = False
            for indice, registro in enumerate(registros, start=2):
                misma = _clave(
                    store._campo(registro, "ID Expediente", "expediente"),
                    store._campo(registro, "Enlace", "enlace"),
                ) == clave_obj
                mismo_bloque = str(
                    store._campo(registro, "Bloque", "bloque") or ""
                ).strip().lower() == bloque
                if misma and mismo_bloque:
                    pestana.update(
                        f"A{indice}:L{indice}",
                        [fila],
                        value_input_option="USER_ENTERED",
                    )
                    actualizado = True
                    break
            if not actualizado:
                pestana.append_row(fila, value_input_option="USER_ENTERED")
        except Exception as exc:
            LOGGER.warning("AsistenteDocs Sheets falló (queda copia local): %s", exc)
            payload["aviso_sheets"] = str(exc)

    return payload


def load_bloque(
    *,
    expediente: str,
    enlace: str = "",
    bloque: str,
    hoja_id: str | None = None,
) -> dict[str, Any] | None:
    """Carga un bloque desde Sheets/Drive o, si falla, desde disco local."""
    if bloque not in BLOQUES:
        return None

    local = _cargar_local(expediente, enlace, bloque)

    if store.is_configured():
        try:
            hoja = store.get_spreadsheet(hoja_id)
            pestana = store._worksheet(hoja, ASISTENTE_SHEET, ASISTENTE_HEADERS)
            clave_obj = _clave(expediente, enlace)
            for registro in pestana.get_all_records():
                misma = _clave(
                    store._campo(registro, "ID Expediente", "expediente"),
                    store._campo(registro, "Enlace", "enlace"),
                ) == clave_obj
                mismo_bloque = str(
                    store._campo(registro, "Bloque", "bloque") or ""
                ).strip().lower() == bloque
                if not (misma and mismo_bloque):
                    continue
                datos_raw = store._campo(registro, "Datos JSON", "datos json") or "{}"
                formato_raw = store._campo(registro, "Formato JSON", "formato json") or "{}"
                try:
                    datos = json.loads(datos_raw) if isinstance(datos_raw, str) else {}
                except Exception:
                    datos = {}
                try:
                    formato = json.loads(formato_raw) if isinstance(formato_raw, str) else {}
                except Exception:
                    formato = {}
                links = {
                    "exigencias": store._campo(registro, "Exigencias Drive", "exigencias drive"),
                    "borrador": store._campo(registro, "Borrador Drive", "borrador drive"),
                    "verificacion": store._campo(
                        registro, "Verificación Drive", "verificacion drive"
                    ),
                    "paquete": store._campo(registro, "Paquete Drive", "paquete drive"),
                }
                exigencias = _leer_texto_drive(str(links.get("exigencias") or ""))
                borrador = _leer_texto_drive(str(links.get("borrador") or ""))
                verificacion = _leer_texto_drive(str(links.get("verificacion") or ""))
                paquete = _leer_texto_drive(str(links.get("paquete") or ""))
                # Si Drive no devolvió texto, usa local
                modelos = {}
                docs_meta: list[dict[str, Any]] = []
                if local:
                    exigencias = exigencias or local.get("exigencias") or ""
                    borrador = borrador or local.get("borrador") or ""
                    verificacion = verificacion or local.get("verificacion") or ""
                    paquete = paquete or local.get("paquete") or ""
                    if not datos:
                        datos = local.get("datos") or {}
                    if not formato:
                        formato = local.get("formato") or {}
                    modelos = local.get("modelos") or {}
                    docs_meta = list(local.get("docs_apoyo") or [])
                if isinstance(datos, dict) and not docs_meta:
                    docs_meta = list(datos.get("_docs_apoyo_meta") or [])
                docs_apoyo = hidratar_docs_apoyo(docs_meta)
                return {
                    "expediente": store._campo(registro, "ID Expediente", "expediente"),
                    "enlace": store._campo(registro, "Enlace", "enlace"),
                    "titulo": store._campo(registro, "Título", "titulo"),
                    "organo": store._campo(registro, "Órgano", "organo"),
                    "bloque": bloque,
                    "datos": datos if isinstance(datos, dict) else {},
                    "formato": formato if isinstance(formato, dict) else {},
                    "exigencias": exigencias,
                    "borrador": borrador,
                    "verificacion": verificacion,
                    "paquete": paquete,
                    "docs_apoyo": docs_apoyo,
                    "modelos": modelos if isinstance(modelos, dict) else {},
                    "links": links,
                    "actualizado": store._campo(registro, "Actualizado", "actualizado"),
                }
        except Exception as exc:
            LOGGER.warning("Carga AsistenteDocs falló, uso local: %s", exc)

    if local and isinstance(local, dict):
        local = dict(local)
        local["docs_apoyo"] = hidratar_docs_apoyo(local.get("docs_apoyo") or [])
    return local


def load_borradores_expediente(
    expediente: str,
    enlace: str = "",
) -> dict[str, str]:
    """Devuelve {admin|eco|tec: borrador} para el paquete final."""
    salida: dict[str, str] = {}
    for bloque in ("admin", "eco", "tec"):
        cargado = load_bloque(expediente=expediente, enlace=enlace, bloque=bloque)
        if cargado and cargado.get("borrador"):
            salida[bloque] = str(cargado["borrador"])
    return salida


def save_revision(
    *,
    expediente: str,
    enlace: str = "",
    titulo: str = "",
    organo: str = "",
    estado: str,
    observaciones: str = "",
    revisor: str = "",
    fecha_limite: str = "",
) -> dict[str, Any]:
    if estado not in ESTADOS_REVISION:
        raise AsistenteStoreError(f"Estado no válido: {estado}")
    return save_bloque(
        expediente=expediente,
        enlace=enlace,
        titulo=titulo,
        organo=organo,
        bloque="revision",
        datos={
            "estado": estado,
            "observaciones": observaciones,
            "revisor": revisor,
            "fecha_limite_presentacion": fecha_limite,
        },
    )


def load_revision(
    *,
    expediente: str,
    enlace: str = "",
) -> dict[str, Any] | None:
    return load_bloque(expediente=expediente, enlace=enlace, bloque="revision")


def listar_alertas_plazo(*, dias: int = 14) -> list[dict[str, Any]]:
    """Expedientes en preparación con plazo próximo o vencido."""
    from datetime import date, timedelta

    hoy = date.today()
    limite = hoy + timedelta(days=max(0, int(dias)))
    alertas: list[dict[str, Any]] = []
    vistos: set[str] = set()

    def _add(exp: str, datos: dict[str, Any], titulo: str = "", enlace: str = "") -> None:
        fl = str(datos.get("fecha_limite_presentacion") or "").strip()[:10]
        if not fl or not re.match(r"20\d{2}-\d{2}-\d{2}", fl):
            return
        try:
            fdate = date.fromisoformat(fl)
        except Exception:
            return
        if fdate > limite and fdate >= hoy:
            return
        clave = f"{exp}|{enlace}|{fl}"
        if clave in vistos:
            return
        vistos.add(clave)
        dias_rest = (fdate - hoy).days
        alertas.append(
            {
                "expediente": exp,
                "titulo": titulo,
                "enlace": enlace,
                "fecha_limite": fl,
                "dias": dias_rest,
                "estado": datos.get("estado") or "",
                "urgencia": "vencido" if dias_rest < 0 else ("hoy" if dias_rest == 0 else "próximo"),
            }
        )

    # Local
    if LOCAL_DIR.is_dir():
        for ruta in LOCAL_DIR.glob("*_revision.json"):
            try:
                payload = json.loads(ruta.read_text(encoding="utf-8"))
            except Exception:
                continue
            _add(
                str(payload.get("expediente") or ""),
                payload.get("datos") or {},
                str(payload.get("titulo") or ""),
                str(payload.get("enlace") or ""),
            )

    # Sheets
    if store.is_configured():
        try:
            hoja = store.get_spreadsheet()
            pestana = store._worksheet(hoja, ASISTENTE_SHEET, ASISTENTE_HEADERS)
            for registro in pestana.get_all_records():
                if str(store._campo(registro, "Bloque", "bloque")).strip().lower() != "revision":
                    continue
                raw = store._campo(registro, "Datos JSON", "datos json") or "{}"
                try:
                    datos = json.loads(raw) if isinstance(raw, str) else {}
                except Exception:
                    datos = {}
                _add(
                    str(store._campo(registro, "ID Expediente", "expediente") or ""),
                    datos if isinstance(datos, dict) else {},
                    str(store._campo(registro, "Título", "titulo") or ""),
                    str(store._campo(registro, "Enlace", "enlace") or ""),
                )
        except Exception as exc:
            LOGGER.debug("Alertas plazo Sheets: %s", exc)

    alertas.sort(key=lambda a: (a.get("fecha_limite") or "9999", a.get("expediente") or ""))
    return alertas
