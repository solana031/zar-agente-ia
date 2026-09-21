"""ZAR package bootstrap.

v30.3.0: local user data lives outside the code repository so updating/replacing
ZAR versions does not erase conversations, memory, files, research or Google
session state. Railway keeps using ZAR_DATA_DIR=/data when configured.
"""
from pathlib import Path
import os
import shutil


def _stable_local_data_dir():
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        return base / "ZAR" / "data"
    return Path.home() / ".zar" / "data"


if not os.environ.get("ZAR_DATA_DIR", "").strip():
    # Cloud/Railway convention remains /data. Local desktop installs use a
    # stable per-user directory independent of the folder containing the code.
    # Detect common cloud paths explicitly so a deployment without an env var
    # still keeps the historical /data behaviour.
    if os.environ.get("RAILWAY_ENVIRONMENT") or Path("/data").exists():
        os.environ["ZAR_DATA_DIR"] = "/data"
    else:
        target = _stable_local_data_dir()
        legacy = Path(__file__).resolve().parent.parent / "data"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if legacy.exists() and legacy.resolve() != target.resolve() and not target.exists():
                shutil.copytree(legacy, target, dirs_exist_ok=True)
            target.mkdir(parents=True, exist_ok=True)
            os.environ["ZAR_DATA_DIR"] = str(target)
        except Exception:
            # If the platform blocks the user-data directory, retain the old
            # project-local behaviour instead of preventing ZAR from starting.
            os.environ["ZAR_DATA_DIR"] = str(legacy)
