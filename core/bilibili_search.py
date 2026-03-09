from __future__ import annotations

import logging
import math
import re
from collections import OrderedDict
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Optional, Tuple

import yt_dlp

from .utils import RateLimiter, human_duration, retry_call

# 复用既有播放量解析（保持兼容，不重复造轮子）
def parse_play_count(value: Any) -> Optional[int]:
    """解析播放量字段为整数。

    支持：
    - int/float/数字字符串：1234 / "1,234"
    - 中文单位："1.2万" / "100万" / "3亿"
    - 其它异常格式返回 None

    Args:
        value: 原始播放量字段（可能是 int/str/None 等）。

    Returns:
        解析后的播放量整数；无法解析返回 None。
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            v = int(value)
            return v if v >= 0 else None
        except Exception:
            return None

    s = str(value).strip()
    if not s:
        return None

    s = s.replace(",", "").replace(" ", "")

    if re.fullmatch(r"\d+", s):
        try:
            return int(s)
        except Exception:
            return None

    m = re.fullmatch(r"(\d+(?:\.\d+)?)([万亿])", s)
    if not m:
        m = re.search(r"(\d+(?:\.\d+)?)([万亿])", s)
    if m:
        try:
            num = float(m.group(1))
            unit = m.group(2)
            mult = {"万": 10_000, "亿": 100_000_000}.get(unit, 1)
            return int(num * mult)
        except Exception:
            return None

    return None


# -----------------------------
# 轻量 tokenizer / 相似度（不引入 rapidfuzz）
# -----------------------------

def _normalize_for_match(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[\[\]【】()（）<>《》{}]", " ", s)
    s = re.sub(r"[_\-—–·•|丨]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _tokenize(s: str) -> List[str]:
    s = _normalize_for_match(s)
    # 保留中文/英文/数字
    parts = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", s)
    return [p for p in parts if p]


def token_jaccard(a: str, b: str) -> float:
    """token 级 Jaccard 相似度（0~1）。"""
    ta = set(_tokenize(a))
    tb = set(_tokenize(b))
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0


def seq_ratio(a: str, b: str) -> float:
    """SequenceMatcher ratio（0~1），对短文本比较稳定。"""
    a = _normalize_for_match(a)
    b = _normalize_for_match(b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def title_similarity(song_title: str, candidate_title: str) -> float:
    """综合相似度：Jaccard + Sequence ratio。

    目标：近似 rapidfuzz 的 token_set_ratio 效果，但不引入新依赖。
    """
    j = token_jaccard(song_title, candidate_title)
    r = seq_ratio(song_title, candidate_title)
    # 偏向 token 交集，兼顾序列相似
    return 0.65 * j + 0.35 * r


# -----------------------------
# yt-dlp 搜索与详情（保留 RateLimiter + retry_call）
# -----------------------------

def yt_search_entries(
    query: str,
    *,
    max_results: int,
    ua: str,
    timeout: int,
    limiter: Optional[RateLimiter] = None,
    retries: int = 3,
    backoff_base: float = 2.0,
) -> List[Dict[str, Any]]:
    q = (query or "").strip()
    if not q:
        return []

    def _do():
        if limiter:
            limiter.wait()
        ydl_opts = {
            "quiet": True,
            "extract_flat": True,
            "noplaylist": True,
            "nocheckcertificate": True,
            "socket_timeout": timeout,
            "http_headers": {"User-Agent": ua, "Referer": "https://www.bilibili.com/"},
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"bilisearch{max(1, int(max_results))}:{q}", download=False)
            return (info or {}).get("entries") or []

    entries = retry_call(_do, retries=retries, backoff_base=backoff_base, label=f"bilisearch({q})")
    return [e for e in entries if isinstance(e, dict)]


# 详情缓存：同一次歌单处理中，同 URL 不重复拉详情
_DETAIL_CACHE: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
_DETAIL_CACHE_MAX = 256


def _cache_get(url: str) -> Optional[Dict[str, Any]]:
    if url in _DETAIL_CACHE:
        _DETAIL_CACHE.move_to_end(url)
        return _DETAIL_CACHE[url]
    return None


def _cache_put(url: str, detail: Dict[str, Any]) -> None:
    _DETAIL_CACHE[url] = detail
    _DETAIL_CACHE.move_to_end(url)
    while len(_DETAIL_CACHE) > _DETAIL_CACHE_MAX:
        _DETAIL_CACHE.popitem(last=False)


def yt_fetch_detail(
    url: str,
    *,
    ua: str,
    timeout: int,
    limiter: Optional[RateLimiter] = None,
    retries: int = 3,
    backoff_base: float = 2.0,
) -> Dict[str, Any]:
    u = (url or "").strip()
    if not u:
        return {}

    cached = _cache_get(u)
    if cached is not None:
        return cached

    def _do():
        if limiter:
            limiter.wait()
        ydl_opts = {
            "quiet": True,
            "noplaylist": True,
            "nocheckcertificate": True,
            "socket_timeout": timeout,
            "http_headers": {"User-Agent": ua, "Referer": "https://www.bilibili.com/"},
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(u, download=False) or {}

    detail = retry_call(_do, retries=retries, backoff_base=backoff_base, label="bili_detail")
    if isinstance(detail, dict) and detail:
        _cache_put(u, detail)
    return detail


def _extract_like_count(detail: Dict[str, Any]) -> int:
    for k in ("like_count", "like", "likes", "up_count"):
        v = detail.get(k)
        n = parse_play_count(v)
        if n is not None:
            return n
    return 0


def _extract_publish_ts(detail: Dict[str, Any]) -> int:
    for k in ("timestamp", "release_timestamp", "upload_date"):
        v = detail.get(k)
        if v is None:
            continue
        if isinstance(v, int):
            return v
        s = str(v).strip()
        if re.fullmatch(r"\d{8}", s):
            try:
                return int(s)
            except Exception:
                pass
        n = parse_play_count(v)
        if n is not None:
            return n
    return 0


def normalize_item(entry: Dict[str, Any], detail: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    d = detail or {}
    title = d.get("title") or entry.get("title") or ""
    uploader = d.get("uploader") or entry.get("uploader") or ""
    raw_v = d.get("view_count") if d else entry.get("view_count")
    v = parse_play_count(raw_v)
    view_count = int(v or 0)

    duration = d.get("duration") or entry.get("duration")
    url = d.get("webpage_url") or entry.get("webpage_url") or entry.get("url") or ""
    vid = d.get("id") or entry.get("id") or ""

    like_count = _extract_like_count(d)
    ts = _extract_publish_ts(d)

    # 额外字段：描述/标签（用于更强过滤/加分）
    desc = d.get("description") or ""
    tags = d.get("tags") or d.get("categories") or []
    if isinstance(tags, str):
        tags = [tags]

    return {
        "title": title,
        "uploader": uploader,
        "view_count": view_count,
        "duration": int(duration or 0) if duration is not None else None,
        "duration_h": human_duration(duration),
        "id": vid,
        "url": url,
        "like_count": like_count,
        "timestamp": ts,
        "description": desc,
        "tags": tags,
    }


# -----------------------------
# 新策略：二阶段召回 + 多特征评分精排
# -----------------------------

@dataclass(frozen=True)
class SongMeta:
    title: str
    artist: str
    duration_s: Optional[int] = None  # 预留：未来可从QQ接口拿到时长


def build_queries(song: SongMeta) -> List[str]:
    """构造多条 query 召回，提高包含原曲的概率。"""
    t = (song.title or "").strip()
    a = (song.artist or "").strip()
    if not t:
        return []

    base = f"{t} {a}".strip()
    queries = [base]
    if a:
        queries.append(f"{a} {t}".strip())
    title_tokens = _tokenize(t)
    if len(title_tokens) >= 2 or len(t) >= 6:
        queries.append(t)
    queries.extend([
        f"{base} 原唱".strip(),
        f"{base} 官方".strip(),
        f"{base} MV".strip(),
        f"{base} Audio".strip(),
        f"{base} 音源".strip(),
    ])
    # 去重保持顺序
    seen = set()
    out = []
    for q in queries:
        qn = q.strip()
        if qn and qn not in seen:
            seen.add(qn)
            out.append(qn)
    return out


def merge_dedupe_entries(all_entries: Iterable[List[Dict[str, Any]]], limit: int) -> List[Dict[str, Any]]:
    """合并多次搜索结果并按 url/id 去重，限制候选总数。"""
    seen = set()
    merged: List[Dict[str, Any]] = []
    for entries in all_entries:
        for e in entries:
            url = (e.get("url") or e.get("webpage_url") or "").strip()
            vid = (e.get("id") or "").strip()
            key = url or vid
            if not key:
                continue
            if key in seen:
                continue
            seen.add(key)
            merged.append(e)
            if len(merged) >= limit:
                return merged
    return merged


def _contains_any(text: str, keywords: List[str]) -> Optional[str]:
    low = _normalize_for_match(text)
    for kw in keywords:
        if _normalize_for_match(kw) in low:
            return kw
    return None


def hard_filter_light(entry: Dict[str, Any], *, hard_keywords: List[str]) -> Tuple[bool, str]:
    """轻量强过滤（不拉详情）：仅基于 entry.title/uploader 做一票否决。"""
    title = str(entry.get("title") or "")
    uploader = str(entry.get("uploader") or "")
    hit = _contains_any(title, hard_keywords) or _contains_any(uploader, hard_keywords)
    if hit:
        return True, f"hard:{hit}"
    return False, ""


def hard_filter_detail(item: Dict[str, Any], *, hard_keywords: List[str]) -> Tuple[bool, str]:
    """详情强过滤：title/uploader/description/tags 任一命中即淘汰。"""
    fields = [
        str(item.get("title") or ""),
        str(item.get("uploader") or ""),
        str(item.get("description") or ""),
        " ".join([str(x) for x in (item.get("tags") or [])]),
    ]
    blob = " ".join(fields)
    hit = _contains_any(blob, hard_keywords)
    if hit:
        return True, f"hard:{hit}"
    return False, ""


def soft_penalties(item: Dict[str, Any], *, soft_keywords: List[str]) -> List[str]:
    """软惩罚命中列表（不直接淘汰）。"""
    blob = " ".join([
        str(item.get("title") or ""),
        str(item.get("uploader") or ""),
        str(item.get("description") or ""),
    ])
    hits = []
    low = _normalize_for_match(blob)
    for kw in soft_keywords:
        if _normalize_for_match(kw) in low:
            hits.append(kw)
    return list(dict.fromkeys(hits))


def official_signals(item: Dict[str, Any], *, official_keywords: List[str]) -> List[str]:
    blob = " ".join([
        str(item.get("title") or ""),
        str(item.get("uploader") or ""),
        str(item.get("description") or ""),
    ])
    hits = []
    low = _normalize_for_match(blob)
    for kw in official_keywords:
        if _normalize_for_match(kw) in low:
            hits.append(kw)
    return list(dict.fromkeys(hits))


def duration_score(song: SongMeta, item: Dict[str, Any], *, min_s: int, max_s: int,
                   strong_bonus_diff_s: int, strong_penalty_diff_s: int) -> Tuple[float, str]:
    d = item.get("duration")
    if d is None:
        return 0.0, "dur:unknown"
    try:
        d = int(d)
    except Exception:
        return 0.0, "dur:bad"

    # 有 QQ 时长：强规则
    if song.duration_s is not None:
        diff = abs(int(song.duration_s) - d)
        if diff <= strong_bonus_diff_s:
            return 1.0, f"dur:+match(diff={diff})"
        if diff >= strong_penalty_diff_s:
            return 0.0, f"dur:-mismatch(diff={diff})"
        # 线性衰减
        return max(0.0, 1.0 - diff / strong_penalty_diff_s), f"dur:mid(diff={diff})"

    # 无 QQ 时长：区间规则（弱）
    if d < min_s:
        return 0.0, f"dur:too_short({d})"
    if d > max_s:
        return 0.0, f"dur:too_long({d})"
    return 0.6, f"dur:ok({d})"


def score_item(
    song: SongMeta,
    item: Dict[str, Any],
    *,
    weights: Dict[str, float],
    hard_keywords: List[str],
    soft_keywords: List[str],
    official_keywords: List[str],
    allow_cover: bool,
    duration_min_s: int,
    duration_max_s: int,
    strong_bonus_diff_s: int,
    strong_penalty_diff_s: int,
) -> Tuple[float, List[str]]:
    """多特征打分：返回 (score, reasons)。

    score 归一化到 0~1 左右（不是严格概率，但可用阈值筛选）。
    """
    reasons: List[str] = []

    # 强过滤
    hard, why = hard_filter_detail(item, hard_keywords=hard_keywords)
    if hard:
        return -1.0, [why]

    # 标题相似
    sim = title_similarity(song.title, item.get("title", ""))
    reasons.append(f"sim={sim:.3f}")

    # 歌手命中：title/uploader/desc 出现 artist token
    artist_hit = 0.0
    if song.artist:
        blob = " ".join([str(item.get("title") or ""), str(item.get("uploader") or ""), str(item.get("description") or "")])
        if _contains_any(blob, [song.artist]):
            artist_hit = 1.0
            reasons.append("artist:+hit")
        else:
            # 处理多字歌手名拆 token 的弱命中
            tokens = _tokenize(song.artist)
            if tokens:
                low = _normalize_for_match(blob)
                hit_cnt = sum(1 for t in tokens if t in low)
                if hit_cnt:
                    artist_hit = min(1.0, hit_cnt / max(1, len(tokens)))
                    reasons.append(f"artist:partial({hit_cnt}/{len(tokens)})")

    # 官方信号
    off_hits = official_signals(item, official_keywords=official_keywords)
    official = 1.0 if off_hits else 0.0
    if off_hits:
        reasons.append(f"official:+{','.join(off_hits[:2])}")

    # 时长匹配
    dur_s, dur_reason = duration_score(
        song,
        item,
        min_s=duration_min_s,
        max_s=duration_max_s,
        strong_bonus_diff_s=strong_bonus_diff_s,
        strong_penalty_diff_s=strong_penalty_diff_s,
    )
    reasons.append(dur_reason)

    # 播放量 tie-break：log 缩放，避免“最火翻唱”碾压
    view = int(item.get("view_count") or 0)
    view_scaled = 0.0
    if view > 0:
        view_scaled = min(1.0, math.log10(view + 1) / 8.0)  # 10^8 约为 1.0
    reasons.append(f"view={view}")

    like = int(item.get("like_count") or 0)
    like_scaled = 0.0
    if like > 0:
        like_scaled = min(1.0, math.log10(like + 1) / 6.0)
    if like:
        reasons.append(f"like={like}")

    # 软惩罚
    pen_hits = soft_penalties(item, soft_keywords=soft_keywords)
    penalty = 0.0
    if pen_hits:
        # cover/live/remix 等降权：默认强度更高；若 allow_cover 则减弱
        base = 0.25 if not allow_cover else 0.12
        penalty = min(1.0, base + 0.06 * (len(pen_hits) - 1))
        reasons.append(f"penalty:-{','.join(pen_hits[:3])}")

    # 组合得分
    w = weights
    score = (
        w.get("title_sim", 0.45) * sim
        + w.get("artist_hit", 0.18) * artist_hit
        + w.get("official_boost", 0.12) * official
        + w.get("duration_fit", 0.10) * dur_s
        + w.get("view_tiebreak", 0.06) * view_scaled
        + w.get("like_tiebreak", 0.04) * like_scaled
    )
    score = max(0.0, score - w.get("penalty", 0.25) * penalty)
    return score, reasons


def pick_best_video_for_song_v2(
    song_title: str,
    song_artist: str,
    *,
    duration_s: Optional[int] = None,
    ua: str,
    timeout: int,
    limiter: Optional[RateLimiter],
    retries: int,
    backoff_base: float,
    # config
    search_max_results: int,
    candidate_limit: int,
    detail_top_k: int,
    score_min: float,
    allow_cover: bool,
    hard_keywords: List[str],
    soft_keywords: List[str],
    official_keywords: List[str],
    weights: Dict[str, float],
    duration_min_s: int,
    duration_max_s: int,
    strong_bonus_diff_s: int,
    strong_penalty_diff_s: int,
) -> Tuple[str, Optional[Dict[str, Any]], str]:
    """二阶段检索 + 多特征精排，返回最优 url。

    流程：
    A) 多 query 召回（3~5条） -> 合并去重 -> 候选上限
    B1) 轻量强过滤（只看 entry.title/uploader）
    B2) 对 TopK 候选拉 detail 并 normalize -> 强过滤 + 打分精排
    B3) 若总分不足阈值：不自动下载（返回空），或 fallback（首条中最合理的）

    Returns:
        (best_url, best_item, explain_log)
    """
    song = SongMeta(title=song_title, artist=song_artist, duration_s=duration_s)

    queries = build_queries(song)
    if not queries:
        return "", None, f"【歌曲：{song_title} - {song_artist}】query 为空，跳过"

    # A) 多 query 召回
    all_entries: List[List[Dict[str, Any]]] = []
    merged: List[Dict[str, Any]] = []
    for q in queries:
        entries = yt_search_entries(
            q,
            max_results=search_max_results,
            ua=ua,
            timeout=timeout,
            limiter=limiter,
            retries=retries,
            backoff_base=backoff_base,
        )
        all_entries.append(entries)
        merged = merge_dedupe_entries(all_entries, limit=candidate_limit)
        if len(merged) >= candidate_limit:
            break
    if not merged:
        return "", None, f"【歌曲：{song_title} - {song_artist}】B站无搜索结果，跳过"

    # B1) 轻量强过滤：减少详情拉取
    light_kept: List[Dict[str, Any]] = []
    light_dropped = 0
    for e in merged:
        drop, why = hard_filter_light(e, hard_keywords=hard_keywords)
        if drop:
            light_dropped += 1
            continue
        light_kept.append(e)

    if not light_kept:
        # 轻量强过滤把所有干掉，降级为“第一个不是硬过滤”的策略（这里直接用 merged[0]）
        first_url = (merged[0].get("url") or merged[0].get("webpage_url") or "").strip()
        return (
            first_url,
            None,
            f"【歌曲：{song_title} - {song_artist}】轻量强过滤后无候选（drop={light_dropped}），降级为首条",
        )

    # 选择 TopK 做详情
    topk = light_kept[:max(1, int(detail_top_k))]

    scored: List[Tuple[float, Dict[str, Any], List[str]]] = []
    parse_failed = True

    for e in topk:
        url = (e.get("url") or e.get("webpage_url") or "").strip()
        if not url:
            continue
        try:
            detail = yt_fetch_detail(
                url,
                ua=ua,
                timeout=timeout,
                limiter=limiter,
                retries=retries,
                backoff_base=backoff_base,
            )
        except Exception:
            logging.exception("Detail fetch failed: %s", url)
            detail = {}

        item = normalize_item(e, detail)
        if item.get("view_count", 0) > 0:
            parse_failed = False

        # 再做一次强过滤（含 description/tags）
        hard, why = hard_filter_detail(item, hard_keywords=hard_keywords)
        if hard:
            continue

        s, reasons = score_item(
            song,
            item,
            weights=weights,
            hard_keywords=hard_keywords,
            soft_keywords=soft_keywords,
            official_keywords=official_keywords,
            allow_cover=allow_cover,
            duration_min_s=duration_min_s,
            duration_max_s=duration_max_s,
            strong_bonus_diff_s=strong_bonus_diff_s,
            strong_penalty_diff_s=strong_penalty_diff_s,
        )
        if s >= 0:
            scored.append((s, item, reasons))

    if not scored:
        # 降级：不要直接取 entries[0]，而是尽量从 light_kept 找一个“最合理”的
        fallback_url = (light_kept[0].get("url") or light_kept[0].get("webpage_url") or "").strip()
        if parse_failed:
            return (
                fallback_url,
                None,
                f"【歌曲：{song_title} - {song_artist}】详情打分阶段无有效候选（播放量/字段解析失败），降级为轻量过滤后的首条",
            )
        return "", None, f"【歌曲：{song_title} - {song_artist}】无有效候选（可能全被过滤），跳过"

    # 精排：按 score 主排序；播放量/发布时间/点赞仅作 tie-break
    scored.sort(key=lambda x: (x[0], x[1].get("view_count", 0), x[1].get("timestamp", 0), x[1].get("like_count", 0)), reverse=True)
    best_score, best_item, best_reasons = scored[0]

    # 阈值：低于阈值不自动下载（避免误下采访/BGM/翻唱等）
    if best_score < float(score_min):
        # fallback：从 Top3 中挑一个 score 最高且没有强烈惩罚的（这里直接返回空，交给上游记录未匹配）
        top3 = scored[:3]
        desc = " | ".join([f"{s:.3f}:{it.get('id','')}" for s,it,_ in top3])
        return "", None, (
            f"【歌曲：{song_title} - {song_artist}】精排最高分={best_score:.3f} < 阈值{score_min}，不自动下载（Top3: {desc}）"
        )

    # 日志：输出 Top3 score + 原因
    top3 = scored[:3]
    top_lines = []
    for s, it, reasons in top3:
        top_lines.append(f"{s:.3f} BV={it.get('id','')} view={it.get('view_count',0)} | " + ",".join(reasons[:5]))
    explain = (
        f"【歌曲：{song_title} - {song_artist}】多query={len(all_entries)} 候选合并={len(merged)} 轻量过滤后={len(light_kept)} "
        f"detail={len(topk)} 有效打分={len(scored)} → 选中BV={best_item.get('id','')} score={best_score:.3f} view={best_item.get('view_count',0)}\n"
        f"Top3: " + " || ".join(top_lines)
    )
    return best_item.get("url",""), best_item, explain
