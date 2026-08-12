"""Despliega la app en Hugging Face Spaces (gratis, PC apagado).

Requiere token en HF_TOKEN o huggingface-cli login.
Uso:  python scripts/deploy_hf_space.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SPACE_ID = os.environ.get("HF_SPACE_ID", "aquilagestion/grefa-licitaciones")
IGNORE_PATTERNS = [
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".streamlit/secrets.toml",
    "service-account.json",
    "*.pyc",
    ".public-url",
    "data/cpv_official",
]


def main() -> int:
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if not token:
        print("ERROR: Define HF_TOKEN con un token de https://huggingface.co/settings/tokens")
        print("Scope minimo: write")
        return 1

    try:
        from huggingface_hub import HfApi, upload_folder
    except ImportError:
        print("Instala: pip install huggingface_hub")
        return 1

    api = HfApi(token=token)
    who = api.whoami()
    print(f"Conectado como: {who.get('name', who)}")

    try:
        # HF ya no admite space_sdk="streamlit"; Streamlit va como plantilla Docker.
        api.create_repo(
            repo_id=SPACE_ID,
            repo_type="space",
            space_sdk="docker",
            space_template="Streamlit",
            exist_ok=True,
            private=False,
        )
        print(f"Space listo: https://huggingface.co/spaces/{SPACE_ID}")
    except Exception as exc:
        texto = str(exc)
        print(f"Aviso create_repo: {exc}")
        if "402" in texto or "PRO subscription" in texto:
            print(
                "Hugging Face ya no hospeda Spaces Docker/Streamlit en el plan gratis.\n"
                "Opciones: suscribirse a HF PRO, o desplegar en Streamlit Community Cloud\n"
                "(https://grefa-licitaciones.streamlit.app) conectado al repo de GitHub."
            )
            return 1

    # README con metadatos Docker/Streamlit (puerto del Dockerfile: 8080)
    readme = ROOT / "README_HF.md"
    readme.write_text(
        """---
title: GREFA Licitaciones PLACSP
emoji: 🦅
colorFrom: green
colorTo: blue
sdk: docker
app_port: 8080
pinned: false
---

Monitor de licitaciones publicas PLACSP para GREFA.
""",
        encoding="utf-8",
    )

    upload_folder(
        repo_id=SPACE_ID,
        repo_type="space",
        folder_path=str(ROOT),
        path_in_repo=".",
        token=token,
        ignore_patterns=IGNORE_PATTERNS,
        delete_patterns=["README_HF.md"],
    )

    # Subir README HF como README.md del Space
    api.upload_file(
        path_or_fileobj=readme.read_bytes(),
        path_in_repo="README.md",
        repo_id=SPACE_ID,
        repo_type="space",
        token=token,
    )
    readme.unlink(missing_ok=True)

    print(f"\nDesplegado. URL: https://{SPACE_ID.replace('/', '-')}.hf.space")
    print("Configura secrets en: Settings -> Repository secrets -> HF Secrets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
