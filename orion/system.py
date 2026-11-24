"""Small cross-cutting helpers shared by the Orion apps."""
from __future__ import annotations

import os
import platform
import subprocess


def safe_popen(target: str, shell: bool = True) -> bool:
    """Launch a whitelisted app/command without raising into the main loop."""
    try:
        subprocess.Popen(target, shell=shell)
        return True
    except Exception:
        return False


def machine_info() -> dict:
    return {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "user": os.getenv("USERNAME") or os.getenv("USER") or "unknown",
    }
