from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple
from urllib.parse import parse_qs, urljoin, urlparse

import requests

from .utils import retry_call, safe_filename


def _extract_playlist_id(candidate: str) -> str | None:
    """Best-effort extraction of QQMusic playlist ID from URL/text."""
    if not candidate:
        return None

    s = candidate.strip()
    if s.isdigit():
        return s

    # Common URL/text patterns.
    for pat in (
        r"/playlist/(\d+)",
        r"/playlist\.html[^0-9]*(\d+)",
        r"[?&#](?:disstid|id|tid)=(\d+)",
        r'"disstid"\s*:\s*"?(\d+)"?',
    ):
        m = re.search(pat, s, flags=re.IGNORECASE)
        if m:
            return m.group(1)

    # Query/fragment based extraction.
    parsed = urlparse(s)
    qs = parse_qs(parsed.query)
    fqs = parse_qs(parsed.fragment)
    for src in (qs, fqs):
        for k in ("disstid", "id", "tid"):
            if k in src and src[k]:
                v = (src[k][0] or "").strip()
                if v.isdigit():
                    return v

    return None


def _normalize_qq_short_url(url: str) -> str:
    """Fix known malformed QQ short-link shape: '?=token' -> '?__=token'."""
    parsed = urlparse(url.strip())
    host = (parsed.netloc or "").lower()
    if not host.endswith("y.qq.com"):
        return url
    if not parsed.path.endswith("/fcgi-bin/u"):
        return url
    if parsed.query.startswith("="):
        fixed_query = f"__{parsed.query}"
        return parsed._replace(query=fixed_query).geturl()
    return url


def _resolve_playlist_id_by_http(
    url: str,
    *,
    session: requests.Session,
    ua: str,
    timeout: int,
) -> str | None:
    """Resolve short/share links by following redirects and parsing response text."""
    headers = {"referer": "https://y.qq.com/", "user-agent": ua}

    request_url = _normalize_qq_short_url(url)

    def _do():
        r = session.get(request_url, headers=headers, timeout=timeout, allow_redirects=True)
        r.raise_for_status()
        return r

    try:
        resp = retry_call(_do, retries=2, backoff_base=1.6, label="QQMusic resolve")
    except Exception:
        return None

    # Redirect-chain URLs are the most reliable source.
    candidates: List[str] = [resp.url]
    for h in resp.history:
        candidates.append(h.url)
        loc = h.headers.get("location") or h.headers.get("Location")
        if loc:
            candidates.append(urljoin(h.url, loc))

    loc = resp.headers.get("location") or resp.headers.get("Location")
    if loc:
        candidates.append(urljoin(resp.url, loc))

    for c in candidates:
        pid = _extract_playlist_id(c)
        if pid:
            return pid

    text = resp.text or ""
    if text:
        pid = _extract_playlist_id(text)
        if pid:
            return pid
        # QQ pages often escape URL slashes in inline JS.
        pid = _extract_playlist_id(text.replace(r"\/", "/"))
        if pid:
            return pid

    return None


def resolve_playlist_id(
    url: str,
    *,
    session: requests.Session | None = None,
    ua: str = "Mozilla/5.0",
    timeout: int = 12,
) -> str:
    pid = _extract_playlist_id(url)
    if pid:
        return pid

    owned_session = session is None
    sess = session or requests.Session()
    try:
        pid = _resolve_playlist_id_by_http(url, session=sess, ua=ua, timeout=timeout)
        if pid:
            return pid
    finally:
        if owned_session:
            sess.close()

    raise ValueError(f"无法解析歌单ID: {url}")


def fetch_qqmusic_playlist(
    url: str,
    *,
    session: requests.Session,
    ua: str,
    timeout: int,
) -> Tuple[str, List[Dict[str, Any]]]:
    pid = resolve_playlist_id(url, session=session, ua=ua, timeout=timeout)
    api = "https://c.y.qq.com/qzone/fcg-bin/fcg_ucc_getcdinfo_byids_cp.fcg"
    params = {"type": 1, "json": 1, "utf8": 1, "disstid": pid, "format": "json"}
    headers = {"referer": "https://y.qq.com/", "user-agent": ua}

    def _do():
        r = session.get(api, params=params, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r

    r = retry_call(_do, retries=3, backoff_base=2.0, label="QQMusic fetch")
    data = r.json()
    cdlist = data.get("cdlist") or []
    if not cdlist:
        raise RuntimeError(f"QQ音乐接口返回结构异常：{data}")

    cd0 = cdlist[0] or {}
    name = safe_filename(cd0.get("dissname") or f"playlist_{pid}") or f"playlist_{pid}"
    songs: List[Dict[str, Any]] = []
    for s in cd0.get("songlist", []) or []:
        title = (s.get("songname") or "").strip()
        singers = s.get("singer") or []
        artist = (singers[0].get("name") if singers else "") or ""
        artist = artist.strip()
        duration_s = s.get("interval")
        try:
            duration_s = int(duration_s)
        except Exception:
            duration_s = None
        if title and artist:
            songs.append({"title": title, "artist": artist, "duration_s": duration_s})
    return name, songs
