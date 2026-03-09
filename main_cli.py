from __future__ import annotations

import argparse
import logging
import os
from logging.handlers import RotatingFileHandler
from dataclasses import replace

from config.persistence import load_user_config
from config.runtime_paths import resolve_internal_file
from config.settings import APP_NAME, Defaults, env_override
from core.pipeline import process_playlist, search_single, download_selected
from core.utils import ensure_writable_dir

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

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser("qqmusic2bilibili")
    sub = p.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("playlist", help="歌单批量处理")
    p1.add_argument("--playlist-url", required=True)
    p1.add_argument("--outdir", default=".")
    p1.add_argument("--audio-dir", default="./mp3")
    p1.add_argument("--start", type=int, default=0)
    p1.add_argument("--limit", type=int, default=1000)
    p1.add_argument("--keep-collab", action="store_true")
    p1.add_argument("--checkpoint", default="_checkpoint_search.json")
    p1.add_argument("--no-download", action="store_true")
    p1.add_argument("--rate", type=float, default=0.35)
    p1.add_argument("--min-sleep", type=float, default=0.3)
    p1.add_argument("--max-sleep", type=float, default=1.2)
    p1.add_argument("--retry-search", type=int, default=4)
    p1.add_argument("--retry-download", type=int, default=3)
    p1.add_argument("--backoff-base", type=float, default=2.0)
    p1.add_argument("--audio-format", choices=["mp3","m4a","flac"], default="flac")
    p1.add_argument("--audio-quality", default="320")

    p2 = sub.add_parser("single-search", help="单曲搜索（多条）")
    p2.add_argument("--query", required=True)
    p2.add_argument("--max-results", type=int, default=20)
    p2.add_argument("--no-enrich", action="store_true")
    p2.add_argument("--rate", type=float, default=0.35)
    p2.add_argument("--min-sleep", type=float, default=0.3)
    p2.add_argument("--max-sleep", type=float, default=1.2)
    p2.add_argument("--retry-search", type=int, default=4)
    p2.add_argument("--backoff-base", type=float, default=2.0)

    p3 = sub.add_parser("single-download", help="从 URL 列表下载")
    p3.add_argument("--audio-dir", default="./mp3")
    p3.add_argument("--audio-format", choices=["mp3","m4a","flac"], default="flac")
    p3.add_argument("--audio-quality", default="320")
    p3.add_argument("--url", action="append", required=True)

    return p

def main() -> int:
    setup_logging()
    args = build_parser().parse_args()
    base_cfg = env_override(load_user_config(Defaults()))
    default_checkpoint_name = Defaults().checkpoint
    cfg_checkpoint = base_cfg.checkpoint
    if cfg_checkpoint == default_checkpoint_name:
        cfg_checkpoint = resolve_internal_file(cfg_checkpoint, app_name=APP_NAME, create_parent=True)
    base_cfg = replace(base_cfg, checkpoint=cfg_checkpoint)

    if args.cmd == "playlist":
        checkpoint = args.checkpoint
        if checkpoint == default_checkpoint_name:
            checkpoint = resolve_internal_file(checkpoint, app_name=APP_NAME, create_parent=True)
        cfg = replace(
            base_cfg,
            playlist_url=args.playlist_url,
            outdir=ensure_writable_dir(args.outdir),
            audio_dir=ensure_writable_dir(args.audio_dir),
            start=args.start,
            limit=args.limit,
            keep_collab=args.keep_collab,
            checkpoint=checkpoint,
            no_download=args.no_download,
            rate=args.rate,
            min_sleep=args.min_sleep,
            max_sleep=args.max_sleep,
            retry_search=args.retry_search,
            retry_download=args.retry_download,
            backoff_base=args.backoff_base,
            audio_format=args.audio_format,
            audio_quality=args.audio_quality,
        )
        res = process_playlist(cfg, progress_cb=lambda d,t,s: logging.info("Progress %s %d/%d", s,d,t))
        logging.info("Done: playlist=%s downloaded=%d failed=%d", res.playlist_name, res.downloaded, len(res.failed_downloads))
        return 0

    if args.cmd == "single-search":
        cfg = replace(base_cfg, rate=args.rate, min_sleep=args.min_sleep, max_sleep=args.max_sleep, retry_search=args.retry_search, backoff_base=args.backoff_base)
        results = search_single(cfg, query=args.query, max_results=args.max_results, enrich_detail=not args.no_enrich,
                               progress_cb=lambda d,t,s: logging.info("Progress %s %d/%d", s,d,t))
        for i,r in enumerate(results, start=1):
            print(f"{i}. {r.get('title')} | {r.get('uploader')} | {r.get('view_count')} | {r.get('duration_h')} | {r.get('url')}")
        return 0

    if args.cmd == "single-download":
        cfg = replace(base_cfg, audio_dir=ensure_writable_dir(args.audio_dir), audio_format=args.audio_format, audio_quality=args.audio_quality)
        items = [{"title":"", "uploader":"", "view_count":0, "duration":None, "id":"", "url":u} for u in args.url]
        ok, failed = download_selected(cfg, items=items, progress_cb=lambda d,t,s: logging.info("Progress %s %d/%d", s,d,t))
        logging.info("Downloaded ok=%d failed=%d", ok, len(failed))
        return 0

    return 1

if __name__ == "__main__":
    raise SystemExit(main())
