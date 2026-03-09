# 验证指南：歌单“二阶段检索 + 打分精排”策略

## 1) 运行方式
GUI：
```bash
python main_gui.py
```

CLI：
```bash
python main_cli.py playlist --playlist-url "QQ歌单URL" --limit 5 --audio-format flac --audio-dir ./mp3
```

## 2) 推荐验证方法（看日志）
新策略会输出“可解释日志”，包含：
- 多 query 召回数量、去重后候选数
- 轻量过滤后候选数、detail 拉取数量
- Top3 的 score 与命中/惩罚原因（cover/live/官方/歌手命中/时长等）

示例（格式类似）：
- 【歌曲：XXX - 歌手】多query=6 候选合并=38 轻量过滤后=25 detail=12 有效打分=9 → 选中BV=BVxxxx score=0.742 view=123456
  Top3: 0.742 BV=... view=... | sim=0.81,artist:+hit,official:+Audio,dur:ok(215),view=...
       || 0.701 BV=... view=... | sim=0.79,penalty:-cover,view=...
       || 0.688 BV=... view=... | sim=0.76,penalty:-live,view=...

若最高分 < 阈值，会记录：
- 精排最高分=0.49 < 阈值0.55，不自动下载

## 3) 快速测试建议（6类场景）
1) 同名歌曲（不同歌手）：检查“歌手命中”是否起作用，避免错选同名不同人
2) 短歌名（如“后来”“晴天”）：检查多 query + 官方信号能否抑制采访/合集
3) 无原曲（仅二创/剪辑）：应触发阈值拦截，不自动下载
4) 翻唱更火：应因“cover/翻唱”软惩罚与相似度/歌手命中被压制
5) 现场更火：应因“live/现场”软惩罚与时长不匹配被压制
6) 标题含版本信息（Remix/DJ/钢琴版）：应被软惩罚降权

## 4) 参数调优入口（config/settings.py）
- `playlist_candidate_limit`：候选上限（默认45）
- `playlist_detail_top_k`：拉详情数量（默认12）
- `playlist_score_min`：自动下载阈值（默认0.55）
- `hard_filter_keywords/soft_penalty_keywords/official_boost_keywords`
- `score_weights`：各特征权重

