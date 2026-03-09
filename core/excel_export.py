from __future__ import annotations

import os
from typing import Dict, List, Tuple

import pandas as pd

from .utils import safe_filename

def export_excels(playlist_name: str, items: List[Dict[str,str]], outdir: str) -> Tuple[str,str]:
    os.makedirs(outdir, exist_ok=True)
    name = safe_filename(playlist_name) or "playlist"
    df = pd.DataFrame(items)
    for col in ("title","artist","platform","url"):
        if col not in df.columns:
            df[col] = ""
    df = df.fillna("").rename(columns={"title":"曲名","artist":"歌手","platform":"平台","url":"URL"})
    p1 = os.path.join(outdir, f"{name}_资源清单.xlsx")
    p2 = os.path.join(outdir, f"{name}_未匹配清单.xlsx")
    df.to_excel(p1, index=False)
    df[df["URL"] == ""].to_excel(p2, index=False)
    return p1, p2
