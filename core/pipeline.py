from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from config.settings import Defaults
from .audio_downloader import download_audio
from .bilibili_search import (
    normalize_item,
    pick_best_video_for_song_v2,
    yt_fetch_detail,
    yt_search_entries,
)
from .cleaner import professional_clean_and_dedup
from .excel_export import export_excels
from .qqmusic_parser import fetch_qqmusic_playlist
from .utils import RateLimiter, load_json, save_json_atomic

ProgressCB = Optional[Callable[[int, int, str], None]]


@dataclass
class PlaylistResult:
    playlist_name: str
    total_raw: int
    total_clean: int
    excel_resource: str
    excel_failed: str
    downloaded: int
    failed_downloads: List[Tuple[str, str]]


def process_playlist(
    cfg: Defaults,
    *,
    progress_cb: ProgressCB = None,
    cancel_event: Optional[Any] = None,
) -> PlaylistResult:
    """歌单批量处理：读取→清洗→B站匹配→导出→下载。"""
    limiter = RateLimiter(cfg.rate, cfg.min_sleep, cfg.max_sleep)
    session = requests.Session()

    playlist_name, raw = fetch_qqmusic_playlist(
        cfg.playlist_url,
        session=session,
        ua=cfg.user_agent,
        timeout=cfg.timeout,
    )
    cleaned = professional_clean_and_dedup(raw, keep_collab=cfg.keep_collab)

    start = max(0, cfg.start)
    end = min(start + max(0, cfg.limit), len(cleaned))
    sliced = cleaned[start:end]

    checkpoint = load_json(cfg.checkpoint) if cfg.checkpoint else {}
    if not isinstance(checkpoint, dict):
        checkpoint = {}

    items: List[Dict[str, str]] = []
    total = len(sliced)

    for idx, s in enumerate(sliced, start=1):
        if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
            break

        title, artist = s["title"], s["artist"]
        duration_s = s.get("duration_s")
        key = f"{title}|||{artist}".lower()

        url = ""
        # 断点：若已存在且有 url，则直接复用
        if key in checkpoint and (checkpoint[key] or {}).get("url"):
            url = (checkpoint[key].get("url") or "").strip()
            logging.info("【歌曲：%s - %s】使用断点结果：%s", title, artist, url)
        else:
            query = f"{title} {artist}".strip()

            if getattr(cfg, "playlist_best_by_views", True):
                url, best, reason = pick_best_video_for_song_v2(
                    title,
                    artist,
                    duration_s=duration_s,
                    ua=cfg.user_agent,
                    timeout=cfg.timeout,
                    limiter=limiter,
                    retries=cfg.retry_search,
                    backoff_base=cfg.backoff_base,
                    search_max_results=cfg.playlist_search_max_results,
                    candidate_limit=cfg.playlist_candidate_limit,
                    detail_top_k=cfg.playlist_detail_top_k,
                    score_min=cfg.playlist_score_min,
                    allow_cover=cfg.playlist_allow_cover,
                    hard_keywords=cfg.hard_filter_keywords,
                    soft_keywords=cfg.soft_penalty_keywords,
                    official_keywords=cfg.official_boost_keywords,
                    weights=cfg.score_weights,
                    duration_min_s=cfg.duration_min_s,
                    duration_max_s=cfg.duration_max_s,
                    strong_bonus_diff_s=cfg.duration_strong_bonus_diff_s,
                    strong_penalty_diff_s=cfg.duration_strong_penalty_diff_s,
                )
                logging.info(reason)
            else:
                # 原策略：首个匹配（仍使用多条 query 的第一个 query 来取首条）
                entries = yt_search_entries(
                    query,
                    max_results=1,
                    ua=cfg.user_agent,
                    timeout=cfg.timeout,
                    limiter=limiter,
                    retries=cfg.retry_search,
                    backoff_base=cfg.backoff_base,
                )
                url = (entries[0].get("url") if entries else "") or ""
                if not url:
                    logging.info("【歌曲：%s - %s】B站无有效搜索结果，跳过", title, artist)

            checkpoint[key] = {"title": title, "artist": artist, "url": url}
            if idx % 10 == 0 and cfg.checkpoint:
                save_json_atomic(cfg.checkpoint, checkpoint)

        items.append(
            {"title": title, "artist": artist, "platform": "Bilibili" if url else "未找到", "url": url}
        )

        if progress_cb:
            progress_cb(idx, total, "搜索匹配")

    if cfg.checkpoint:
        save_json_atomic(cfg.checkpoint, checkpoint)

    excel_resource, excel_failed = export_excels(playlist_name, items, cfg.outdir)

    downloaded = 0
    failed: List[Tuple[str, str]] = []
    if not cfg.no_download:
        dl = [it for it in items if it.get("url")]
        for i, it in enumerate(dl, start=1):
            if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
                break
            try:
                download_audio(it, cfg.audio_dir, audio_format=cfg.audio_format, audio_quality=cfg.audio_quality)
                downloaded += 1
            except Exception as e:
                failed.append((it.get("title", ""), str(e)))
                logging.exception("Download failed: %s", it.get("url"))
            if progress_cb:
                progress_cb(i, len(dl), "下载音频")

    return PlaylistResult(playlist_name, len(raw), len(cleaned), excel_resource, excel_failed, downloaded, failed)


def search_single(
    cfg: Defaults,
    *,
    query: str,
    max_results: int,
    enrich_detail: bool,
    progress_cb: ProgressCB = None,
    cancel_event: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    limiter = RateLimiter(cfg.rate, cfg.min_sleep, cfg.max_sleep)
    entries = yt_search_entries(
        query,
        max_results=max_results,
        ua=cfg.user_agent,
        timeout=cfg.timeout,
        limiter=limiter,
        retries=cfg.retry_search,
        backoff_base=cfg.backoff_base,
    )
    results: List[Dict[str, Any]] = []
    total = len(entries)

    for idx, e in enumerate(entries, start=1):
        if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
            break

        url = e.get("url") or e.get("webpage_url") or ""
        detail = {}
        if enrich_detail and url:
            try:
                detail = yt_fetch_detail(
                    url,
                    ua=cfg.user_agent,
                    timeout=cfg.timeout,
                    limiter=limiter,
                    retries=max(1, cfg.retry_search - 1),
                    backoff_base=cfg.backoff_base,
                )
            except Exception:
                logging.exception("Detail fetch failed: %s", url)

        results.append(normalize_item(e, detail))
        if progress_cb:
            progress_cb(idx, total, "单曲搜索")
    return results


def download_selected(
    cfg: Defaults,
    *,
    items: List[Dict[str, Any]],
    progress_cb: ProgressCB = None,
    cancel_event: Optional[Any] = None,
) -> Tuple[int, List[Tuple[str, str]]]:
    dl = [it for it in items if it.get("url")]
    ok = 0
    failed: List[Tuple[str, str]] = []

    for idx, it in enumerate(dl, start=1):
        if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
            break
        payload = {
            "title": it.get("title", ""),
            "artist": it.get("uploader", ""),
            "uploader": it.get("uploader", ""),
            "url": it.get("url", ""),
        }
        try:
            download_audio(payload, cfg.audio_dir, audio_format=cfg.audio_format, audio_quality=cfg.audio_quality)
            ok += 1
        except Exception as e:
            failed.append((it.get("title", ""), str(e)))
            logging.exception("Selected download failed: %s", it.get("url"))
        if progress_cb:
            progress_cb(idx, len(dl), "下载选中")
    return ok, failed
