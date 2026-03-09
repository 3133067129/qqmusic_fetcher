from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_data_root(app_name: str) -> Path:
    if os.name == "nt":
        base = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA") or str(Path.home())
    else:
        base = os.getenv("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    root = Path(base) / app_name
    root.mkdir(parents=True, exist_ok=True)
    return root


def resolve_internal_file(path: str, *, app_name: str, create_parent: bool = False) -> str:
    p = Path((path or "").strip())
    if p.is_absolute():
        target = p
    elif is_frozen():
        target = app_data_root(app_name) / p
    else:
        target = p
    if create_parent:
        target.parent.mkdir(parents=True, exist_ok=True)
    return str(target)


def runtime_binary_dirs() -> list[str]:
    dirs: list[str] = []
    if os.getenv("PATH"):
        for seg in os.getenv("PATH", "").split(os.pathsep):
            if seg:
                dirs.append(seg)
    exe_dir = Path(sys.executable).resolve().parent
    dirs.append(str(exe_dir))
    dirs.append(str(exe_dir / "bin"))
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirs.append(str(Path(meipass)))
        dirs.append(str(Path(meipass) / "bin"))
    seen = set()
    out: list[str] = []
    for d in dirs:
        dn = os.path.normcase(os.path.normpath(d))
        if dn in seen:
            continue
        seen.add(dn)
        out.append(d)
    return out
