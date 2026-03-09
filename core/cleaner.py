from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .utils import normalize_text

VERSION_KEYWORDS = [
    "live","remix","mix","ver","version","cover",
    "伴奏","纯音乐","instrumental","edit","demo","现场","翻唱","版",
]

def _remove_all_brackets(text: str) -> str:
    patterns = [r"\(.*?\)", r"（.*?）", r"\[.*?\]", r"【.*?】", r"《.*?》"]
    for p in patterns:
        text = re.sub(p, "", text)
    return text.strip()

def _remove_version_words(text: str) -> str:
    lower = text.lower()
    for w in VERSION_KEYWORDS:
        lower = re.sub(rf"\b{re.escape(w)}\b", "", lower)
    return lower.strip()

def _remove_feat(text: str) -> str:
    for p in [r"\s+feat\..*", r"\s+ft\..*", r"\s+with\s+.*"]:
        text = re.sub(p, "", text, flags=re.IGNORECASE)
    return text.strip()

def _normalize_artist(artist: str, keep_collab: bool) -> str:
    if keep_collab:
        return artist.strip()
    for sep in ["/","&","、",",","，"," x "," X "]:
        if sep in artist:
            artist = artist.split(sep)[0]
    return artist.strip()

def _compress_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()

def clean_song(title: str, artist: str, keep_collab: bool, duration_s: Optional[int] = None) -> Dict[str, Any]:
    title = normalize_text(title)
    artist = normalize_text(artist)
    title = _compress_spaces(_remove_version_words(_remove_feat(_remove_all_brackets(title))))
    artist = _compress_spaces(_normalize_artist(_remove_feat(_remove_all_brackets(artist)), keep_collab))
    duration_val = None
    if duration_s is not None:
        try:
            duration_val = int(duration_s)
            if duration_val <= 0:
                duration_val = None
        except Exception:
            duration_val = None
    return {"title": title, "artist": artist, "duration_s": duration_val}

def professional_clean_and_dedup(songs: List[Dict[str, Any]], keep_collab: bool=False) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen: Dict[Tuple[str, str], int] = {}
    for s in songs:
        c = clean_song(s.get("title",""), s.get("artist",""), keep_collab, s.get("duration_s"))
        if not c["title"] or not c["artist"]:
            continue
        key=(c["title"].lower(), c["artist"].lower())
        if key in seen:
            idx = seen[key]
            if c.get("duration_s") and not out[idx].get("duration_s"):
                out[idx]["duration_s"] = c["duration_s"]
            continue
        seen[key] = len(out)
        out.append(c)
    return out
