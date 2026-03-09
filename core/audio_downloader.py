from __future__ import annotations

import logging
import os
from typing import Dict, List

import yt_dlp
from mutagen.easyid3 import EasyID3
from mutagen.flac import FLAC
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4

from .utils import describe_audio_quality, ensure_ffmpeg, safe_filename

def write_tags(path: str, title: str, artist: str, audio_format: str) -> None:
    fmt = audio_format.lower()
    if fmt == "mp3":
        try:
            audio = EasyID3(path)
        except Exception:
            audio = MP3(path, ID3=EasyID3)
            audio.add_tags()
            audio = EasyID3(path)
        audio["title"] = title
        audio["artist"] = artist
        audio.save()
        return
    if fmt == "m4a":
        mp4 = MP4(path)
        mp4["\xa9nam"] = [title]
        mp4["\xa9ART"] = [artist]
        mp4.save()
        return
    if fmt == "flac":
        flac = FLAC(path)
        flac["title"] = [title]
        flac["artist"] = [artist]
        flac.save()
        return
    raise ValueError(f"不支持的音频格式: {audio_format}")

def build_postprocessors(audio_format: str, audio_quality: str) -> List[Dict[str,str]]:
    fmt = audio_format.lower()
    if fmt not in {"mp3","m4a","flac"}:
        raise ValueError(f"audio_format 不支持: {audio_format}")
    pp: Dict[str,str] = {"key":"FFmpegExtractAudio","preferredcodec":fmt}
    if fmt == "mp3":
        pp["preferredquality"] = str(audio_quality)
    elif fmt == "m4a":
        pp["preferredquality"] = "128"
    return [pp]

def download_audio(item: Dict[str,str], output_dir: str, *, audio_format: str, audio_quality: str) -> str:
    ensure_ffmpeg()
    url = (item.get("url") or "").strip()
    if not url:
        raise ValueError("download_audio: empty url")

    title = item.get("title") or ""
    artist = item.get("artist") or item.get("uploader") or ""
    base = safe_filename(f"{title} - {artist}") or "unknown"
    fmt = audio_format.lower()
    out_path = os.path.join(output_dir, f"{base}.{fmt}")
    os.makedirs(output_dir, exist_ok=True)

    if os.path.exists(out_path):
        logging.info("Skip exists: %s", out_path)
        return out_path

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(output_dir, base + ".%(ext)s"),
        "postprocessors": build_postprocessors(fmt, audio_quality),
        "quiet": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    if not os.path.exists(out_path):
        raise RuntimeError(f"下载完成但未生成目标文件：{out_path}")

    write_tags(out_path, title, artist, fmt)
    logging.info("Downloaded: %s | format=%s | quality=%s", out_path, fmt, describe_audio_quality(fmt, audio_quality))
    return out_path
