from __future__ import annotations

import json
import logging
import os
import random
import re
import shutil
import sys
import time
import unicodedata
from threading import Lock
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import urlparse

from config.runtime_paths import runtime_binary_dirs


def safe_filename(text: str) -> str:
    text = text or ""
    return re.sub(r'[\\/:*?"<>|]', "", text).strip()


def load_json(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logging.exception("Failed to load json: %s", path)
        return {}


def save_json_atomic(path: str, data: Dict[str, Any]) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def normalize_text(text: str) -> str:
    if not text:
        return ""
    return unicodedata.normalize("NFKC", text).strip()


class RateLimiter:
    def __init__(self, rate: float, min_sleep: float, max_sleep: float) -> None:
        self.rate = max(rate, 0.1)
        self.min_sleep = max(0.0, min_sleep)
        self.max_sleep = max(self.min_sleep, max_sleep)
        self._lock = Lock()
        self._next_allowed = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.time()
            interval = 1.0 / self.rate
            sleep_s = max(0.0, self._next_allowed - now)
            jitter = random.uniform(self.min_sleep, self.max_sleep)
            self._next_allowed = max(self._next_allowed, now) + interval
        time.sleep(sleep_s + interval + jitter)


def retry_call(
    func: Callable[[], Any],
    *,
    retries: int,
    backoff_base: float,
    exc_types: Tuple[type, ...] = (Exception,),
    label: str = "",
) -> Any:
    last: Optional[BaseException] = None
    for attempt in range(1, retries + 1):
        try:
            return func()
        except exc_types as e:
            last = e
            wait_s = (backoff_base ** (attempt - 1)) + random.uniform(0, 0.5)
            logging.warning(
                "%s attempt %d/%d failed: %s; backoff %.2fs",
                label,
                attempt,
                retries,
                repr(e),
                wait_s,
            )
            time.sleep(wait_s)
    raise last if last else RuntimeError("retry_call failed")


def ensure_ffmpeg() -> None:
    if shutil.which("ffmpeg") is not None:
        return
    bin_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    for d in runtime_binary_dirs():
        ffmpeg_path = os.path.join(d, bin_name)
        if not os.path.exists(ffmpeg_path):
            continue
        os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
        if shutil.which("ffmpeg") is not None:
            return
    if getattr(sys, "frozen", False):
        raise RuntimeError("ffmpeg is missing. Put ffmpeg.exe next to the executable or in PATH.")
    raise RuntimeError("ffmpeg is missing. Install ffmpeg and ensure it is available in PATH.")


def describe_audio_quality(audio_format: str, audio_quality: str) -> str:
    fmt = (audio_format or "").lower()
    if fmt == "mp3":
        return f"{audio_quality}kbps"
    if fmt == "m4a":
        return "128kbps (default)"
    if fmt == "flac":
        return "lossless (ignore bitrate)"
    return "unknown"


def human_duration(seconds: Optional[int]) -> str:
    if seconds is None:
        return ""
    try:
        s = int(seconds)
    except Exception:
        return ""
    m, s = divmod(max(0, s), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def validate_url(url: str) -> bool:
    try:
        u = urlparse(url)
        return bool(u.scheme and u.netloc)
    except Exception:
        return False


def ensure_writable_dir(path: str) -> str:
    p = (path or "").strip() or "."
    os.makedirs(p, exist_ok=True)
    t = os.path.join(p, ".write_test")
    try:
        with open(t, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(t)
    except PermissionError as e:
        raise PermissionError(f"Directory is not writable: {p}") from e
    return p
