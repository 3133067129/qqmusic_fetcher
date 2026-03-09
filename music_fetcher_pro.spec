# -*- mode: python ; coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


project_root = Path(SPECPATH)

datas = []
binaries = []
hiddenimports = []

# Runtime assets needed by themed tkinter and TLS cert lookup.
datas += collect_data_files("ttkthemes")
datas += collect_data_files("certifi")

# yt-dlp and mutagen use dynamic module loading.
hiddenimports += collect_submodules("yt_dlp")
hiddenimports += collect_submodules("mutagen")

# Optional sidecar ffmpeg binaries, if user places them in repo root or bin/.
for rel_path, target_dir in (
    ("ffmpeg.exe", "."),
    ("ffprobe.exe", "."),
    ("bin/ffmpeg.exe", "bin"),
    ("bin/ffprobe.exe", "bin"),
):
    src = project_root / rel_path
    if src.exists():
        binaries.append((str(src), target_dir))

datas = list(dict.fromkeys(datas))
binaries = list(dict.fromkeys(binaries))
hiddenimports = list(dict.fromkeys(hiddenimports))


a = Analysis(
    ["main_gui.py"],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="music_fetcher_pro",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=str(project_root / "build_assets" / "version_info.txt"),
    icon=[str(project_root / "build_assets" / "app.ico")],
)
