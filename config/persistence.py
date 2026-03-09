from __future__ import annotations

import configparser
import os
from dataclasses import asdict

from .settings import APP_NAME, Defaults

def _cfg_path() -> str:
    return os.path.join(os.path.expanduser("~"), f".{APP_NAME}.ini")

def load_user_config(defaults: Defaults) -> Defaults:
    p = _cfg_path()
    if not os.path.exists(p):
        return defaults
    cp = configparser.ConfigParser()
    cp.read(p, encoding="utf-8")
    sec = cp["settings"] if "settings" in cp else {}
    d = asdict(defaults)
    for k,v0 in d.items():
        if k not in sec:
            continue
        v = sec.get(k)
        try:
            if isinstance(v0, bool):
                d[k] = str(v).lower() in {"1","true","yes","y","on"}
            elif isinstance(v0, int):
                d[k] = int(v)
            elif isinstance(v0, float):
                d[k] = float(v)
            else:
                d[k] = v
        except Exception:
            pass
    return Defaults(**d)

def save_user_config(cfg: Defaults) -> None:
    p = _cfg_path()
    cp = configparser.ConfigParser()
    cp["settings"] = {k: str(v) for k,v in asdict(cfg).items()}
    with open(p, "w", encoding="utf-8") as f:
        cp.write(f)
