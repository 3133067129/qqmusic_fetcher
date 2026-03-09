from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from dataclasses import replace

from config.persistence import load_user_config
from config.runtime_paths import resolve_internal_file
from config.settings import APP_NAME, Defaults, env_override
from gui.main_window import run_gui

def setup_logging() -> None:
    log_file = resolve_internal_file("logs/app.log", app_name=APP_NAME, create_parent=True)
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    fh = RotatingFileHandler(log_file, maxBytes=2*1024*1024, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

def main() -> int:
    setup_logging()
    cfg = env_override(load_user_config(Defaults()))
    if cfg.checkpoint == Defaults().checkpoint:
        cfg = replace(
            cfg,
            checkpoint=resolve_internal_file(cfg.checkpoint, app_name=APP_NAME, create_parent=True),
        )
    run_gui(cfg)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
