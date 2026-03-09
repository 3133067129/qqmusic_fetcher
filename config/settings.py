from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List

APP_NAME = "qqmusic2bilibili"


@dataclass(frozen=True)
class Defaults:
    # 网络
    user_agent: str = "Mozilla/5.0 (compatible; QQMusic2Bili/2.0)"
    timeout: int = 12

    # 歌单
    playlist_url: str = "https://i2.y.qq.com/n3/other/pages/details/playlist.html?id=8553762669"
    start: int = 0
    limit: int = 1000
    keep_collab: bool = False
    checkpoint: str = "_checkpoint_search.json"

    # 歌单匹配策略
    playlist_best_by_views: bool = True  # GUI 复选框控制
    playlist_search_max_results: int = 12  # 单次 query 的 N（bilisearchN）
    playlist_candidate_limit: int = 45     # 多 query 合并后的候选上限（去重后）
    playlist_detail_top_k: int = 12        # 精排阶段最多拉多少条详情
    playlist_score_min: float = 0.55       # 低于该阈值不自动下载（记录为未匹配）
    playlist_allow_cover: bool = False     # 默认不鼓励翻唱（软惩罚），True 则降低惩罚

    # 辅助排序开关（仅在 score 接近或 tie 时使用）
    aux_sort_publish_time: bool = True
    aux_sort_like_count: bool = True

    # 节流与重试
    rate: float = 0.35
    min_sleep: float = 0.3
    max_sleep: float = 1.2
    retry_search: int = 4
    retry_download: int = 3
    backoff_base: float = 2.0

    # 输出
    outdir: str = "."
    audio_dir: str = "./mp3"
    no_download: bool = False

    # 音频
    audio_format: str = "flac"   # mp3/m4a/flac
    audio_quality: str = "320"  # mp3 only; m4a fixed 128; flac ignore

    # 单曲
    single_max_results: int = 20
    enrich_detail: bool = True

    # ===== 关键词表（强过滤/软惩罚/加分信号）=====
    # 强过滤：一票否决（采访/教程/BGM/合集等）
    hard_filter_keywords: List[str] = field(default_factory=lambda: [
        "采访", "访谈", "对谈", "专访", "幕后", "花絮", "reaction", "react", "解说", "讲解",
        "教学", "教程", "伴奏", "BGM", "bgm", "纯音乐", "instrumental", "卡点", "混剪",
        "合集", "串烧", "歌单", "全专", "整专", "专辑", "作业", "翻弹", "开箱", "测评",
        "高能", "剪辑", "AMV", "MAD", "鬼畜", "remix合集",
    ])

    # 软惩罚：默认降权（翻唱/现场/remix 等）
    soft_penalty_keywords: List[str] = field(default_factory=lambda: [
        "翻唱", "cover", "live", "现场", "纯享", "remix", "DJ", "改编", "重制", "rework",
        "翻弹", "弹唱", "伴奏版", "钢琴版", "吉他版", "八音盒", "女声版", "男声版", "rap版",
    ])

    # 官方信号加分
    official_boost_keywords: List[str] = field(default_factory=lambda: [
        "官方", "Official", "MV", "Music Video", "Audio", "音源", "完整版", "完整版音源", "版权",
    ])

    # ===== 打分权重（可调参）=====
    score_weights: Dict[str, float] = field(default_factory=lambda: {
        "title_sim": 0.45,        # 标题相似度主权重
        "artist_hit": 0.18,       # 歌手命中
        "official_boost": 0.12,   # 官方信号
        "duration_fit": 0.10,     # 时长匹配（无QQ时长时走区间与惩罚）
        "view_tiebreak": 0.06,    # 播放量仅作为小权重
        "like_tiebreak": 0.04,    # 点赞小权重
        "penalty": 0.25,          # 软惩罚强度（作为扣分系数使用）
    })

    # 时长规则（秒）：没有 QQ 时长时，用这个区间做“弱过滤/弱加分”
    duration_min_s: int = 90
    duration_max_s: int = 420

    # 若未来上游能提供 QQ 歌曲时长（秒），可启用更强规则：
    duration_strong_bonus_diff_s: int = 5
    duration_strong_penalty_diff_s: int = 30


def env_override(d: Defaults) -> Defaults:
    """允许用环境变量覆盖少数关键项。"""
    ua = os.getenv("QQ2BILI_UA", d.user_agent)
    timeout = int(os.getenv("QQ2BILI_TIMEOUT", str(d.timeout)))
    return Defaults(**{**d.__dict__, "user_agent": ua, "timeout": timeout})
