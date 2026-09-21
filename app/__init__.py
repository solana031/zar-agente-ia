"""ZAR package bootstrap.


Persistent-state rule:
- Code/releases live in the repository and may be replaced on deployment.
- User state lives outside the repository in ZAR_DATA_DIR.
- Railway uses the attached Volume mount path.
- A Railway deployment without the expected persistent storage fails fast
  instead of silently writing user data to ephemeral storage.
"""
from pathlib import Path
import json
import os
import shutil
from datetime import datetime, timezone


def _stable_local_data_dir():
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        return base / "ZAR" / "data"
    return Path.home() / ".zar" / "data"


def _is_railway():
    return bool(os.environ.get("RAILWAY_ENVIRONMENT"))


def _configure_data_dir():
    explicit = os.environ.get("ZAR_DATA_DIR", "").strip()
    volume_mount = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", "").strip()

    if _is_railway():
        # Railway exposes this automatically when a Volume is attached.
        # Prefer the actual mount path and never silently fall back to the
        # deployment's ephemeral filesystem.
        if volume_mount:
            target = Path(volume_mount)
        elif explicit:
            target = Path(explicit)
        else:
            target = Path("/data")

        if not target.exists():
            raise RuntimeError(
                f"ZAR no puede iniciar: el almacenamiento persistente de Railway "
                f"no está montado en {target}."
            )

        if volume_mount and target.resolve() != Path(volume_mount).resolve():
            raise RuntimeError(
                "ZAR detectó una configuración inconsistente entre "
                "ZAR_DATA_DIR y RAILWAY_VOLUME_MOUNT_PATH."
            )

        if not os.access(target, os.W_OK):
            raise RuntimeError(
                f"ZAR no puede escribir en el almacenamiento persistente: {target}"
            )

        os.environ["ZAR_DATA_DIR"] = str(target)
        return target

    if explicit:
        target = Path(explicit)
        target.mkdir(parents=True, exist_ok=True)
        os.environ["ZAR_DATA_DIR"] = str(target)
        return target

    # Local desktop installs use a stable per-user directory independent of
    # the folder containing the current ZAR release.
    target = _stable_local_data_dir()
    legacy = Path(__file__).resolve().parent.parent / "data"

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if legacy.exists() and legacy.resolve() != target.resolve() and not target.exists():
            shutil.copytree(legacy, target, dirs_exist_ok=True)
        target.mkdir(parents=True, exist_ok=True)
        os.environ["ZAR_DATA_DIR"] = str(target)
        return target
    except Exception:
        os.environ["ZAR_DATA_DIR"] = str(legacy)
        return legacy


def _ensure_persistent_layout(data_dir):
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    for name in ("users", "backups", "jobs", "audio_studio", "video_creator"):
        (data_dir / name).mkdir(parents=True, exist_ok=True)

    marker = data_dir / ".zar_persistence.json"
    if not marker.exists():
        marker.write_text(
            json.dumps(
                {
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "schema": 1,
                    "purpose": "ZAR persistent runtime state",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    if not os.access(data_dir, os.W_OK):
        raise RuntimeError(f"ZAR no puede escribir en {data_dir}")

    print(f"[ZAR persistence] DATA_DIR={data_dir}")


DATA_DIR = _configure_data_dir()
_ensure_persistent_layout(DATA_DIR)
