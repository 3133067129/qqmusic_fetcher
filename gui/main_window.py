from __future__ import annotations

import logging
import os
import queue
import threading
import tkinter as tk
from dataclasses import replace
from tkinter import filedialog, messagebox, ttk
from typing import Any, Dict, List, Optional

from ttkthemes import ThemedTk

from config.persistence import save_user_config
from config.settings import Defaults
from core.pipeline import download_selected, process_playlist, search_single
from core.utils import describe_audio_quality, ensure_writable_dir, validate_url
from gui.logging_handler import TkTextHandler

def human_views(n: int) -> str:
    try:
        n = int(n)
    except Exception:
        return ""
    if n >= 100_000_000:
        return f"{n/100_000_000:.2f}亿"
    if n >= 10_000:
        return f"{n/10_000:.2f}万"
    return str(n)

class PlaylistPanel(ttk.Frame):
    def __init__(self, master: tk.Misc, app: "MainWindow") -> None:
        super().__init__(master)
        self.app = app
        self._build()

    def _build(self) -> None:
        self.columnconfigure(1, weight=1)
        cfg = self.app.cfg

        lf = ttk.LabelFrame(self, text="歌单批量处理")
        lf.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        lf.columnconfigure(1, weight=1)

        ttk.Label(lf, text="歌单URL:").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        ttk.Entry(lf, textvariable=self.app.playlist_url).grid(row=0, column=1, sticky="ew", padx=6, pady=6)

        ttk.Checkbutton(lf, text="保留合作歌手", variable=self.app.keep_collab).grid(row=0, column=2, padx=6, pady=6)

        ttk.Label(lf, text="start").grid(row=1, column=0, sticky="w", padx=6, pady=6)
        ttk.Entry(lf, textvariable=self.app.start, width=8).grid(row=1, column=1, sticky="w", padx=6, pady=6)
        ttk.Label(lf, text="limit").grid(row=1, column=2, sticky="e", padx=6, pady=6)
        ttk.Entry(lf, textvariable=self.app.limit, width=8).grid(row=1, column=3, sticky="w", padx=6, pady=6)

        ttk.Label(lf, text="outdir").grid(row=2, column=0, sticky="w", padx=6, pady=6)
        ttk.Entry(lf, textvariable=self.app.outdir).grid(row=2, column=1, sticky="ew", padx=6, pady=6)
        ttk.Button(lf, text="浏览", command=self.app.pick_outdir).grid(row=2, column=2, padx=6, pady=6)

        ttk.Label(lf, text="audio_dir").grid(row=3, column=0, sticky="w", padx=6, pady=6)
        ttk.Entry(lf, textvariable=self.app.audio_dir).grid(row=3, column=1, sticky="ew", padx=6, pady=6)
        ttk.Button(lf, text="浏览", command=self.app.pick_audio_dir).grid(row=3, column=2, padx=6, pady=6)

        ttk.Label(lf, text="format").grid(row=4, column=0, sticky="w", padx=6, pady=6)
        ttk.Combobox(lf, textvariable=self.app.audio_format, values=["mp3","m4a","flac"], width=8, state="readonly").grid(row=4, column=1, sticky="w", padx=6, pady=6)
        ttk.Label(lf, text="quality").grid(row=4, column=2, sticky="e", padx=6, pady=6)
        ttk.Entry(lf, textvariable=self.app.audio_quality, width=8).grid(row=4, column=3, sticky="w", padx=6, pady=6)

        ttk.Checkbutton(lf, text="仅导出不下载", variable=self.app.no_download).grid(row=5, column=0, columnspan=2, sticky="w", padx=6, pady=6)

        ttk.Button(lf, text="开始处理", command=self.app.start_playlist).grid(row=6, column=0, padx=6, pady=10)
        ttk.Button(lf, text="打开下载目录", command=self.app.open_audio_dir).grid(row=6, column=1, sticky="w", padx=6, pady=10)

class SinglePanel(ttk.Frame):
    def __init__(self, master: tk.Misc, app: "MainWindow") -> None:
        super().__init__(master)
        self.app = app
        self.results: List[Dict[str,Any]] = []
        self._build()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        top = ttk.LabelFrame(self, text="单曲精准搜索")
        top.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="关键词").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        ttk.Entry(top, textvariable=self.app.single_query).grid(row=0, column=1, sticky="ew", padx=6, pady=6)
        ttk.Button(top, text="搜索", command=self.app.start_single_search).grid(row=0, column=2, padx=6, pady=6)

        ttk.Label(top, text="max").grid(row=1, column=0, sticky="w", padx=6, pady=6)
        ttk.Entry(top, textvariable=self.app.single_max, width=8).grid(row=1, column=1, sticky="w", padx=6, pady=6)

        box = ttk.LabelFrame(self, text="结果（可多选）")
        box.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)

        cols=("title","uploader","views","duration","id","url")
        self.tree = ttk.Treeview(box, columns=cols, show="headings", selectmode="extended")
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=vsb.set)

        self.tree.heading("title", text="标题")
        self.tree.heading("uploader", text="UP主")
        self.tree.heading("views", text="播放")
        self.tree.heading("duration", text="时长")
        self.tree.heading("id", text="BV")
        self.tree.heading("url", text="链接")

        self.tree.column("title", width=320, anchor="w")
        self.tree.column("uploader", width=120, anchor="w")
        self.tree.column("views", width=90, anchor="e")
        self.tree.column("duration", width=80, anchor="center")
        self.tree.column("id", width=110, anchor="w")
        self.tree.column("url", width=260, anchor="w")

        bottom = ttk.LabelFrame(self, text="下载选中")
        bottom.grid(row=2, column=0, sticky="ew", padx=10, pady=(0,10))
        bottom.columnconfigure(6, weight=1)

        self.btn_dl = ttk.Button(bottom, text="下载选中音频", command=self.app.start_single_download)
        self.btn_dl.grid(row=0, column=0, padx=6, pady=8)

        ttk.Label(bottom, text="format").grid(row=0, column=1, padx=(10,6), pady=8)
        ttk.Combobox(bottom, textvariable=self.app.audio_format, values=["mp3","m4a","flac"], width=8, state="readonly").grid(row=0, column=2, pady=8)
        ttk.Label(bottom, text="quality").grid(row=0, column=3, padx=(10,6), pady=8)
        ttk.Entry(bottom, textvariable=self.app.audio_quality, width=8).grid(row=0, column=4, pady=8)
        ttk.Label(bottom, text="仅mp3生效；m4a固定128；flac忽略", foreground="#666").grid(row=0, column=5, sticky="w", padx=6, pady=8)

        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._sync_dl_btn())
        self._sync_dl_btn()

    def _sync_dl_btn(self) -> None:
        self.btn_dl.configure(state="normal" if self.tree.selection() else "disabled")

    def set_results(self, results: List[Dict[str,Any]]) -> None:
        self.results = results
        for i in self.tree.get_children():
            self.tree.delete(i)
        for idx,r in enumerate(results):
            self.tree.insert("", "end", iid=str(idx), values=(
                r.get("title",""),
                r.get("uploader",""),
                human_views(r.get("view_count",0)),
                r.get("duration_h",""),
                r.get("id",""),
                r.get("url",""),
            ))
        self._sync_dl_btn()

    def selected_items(self) -> List[Dict[str,Any]]:
        out=[]
        for iid in self.tree.selection():
            try:
                out.append(self.results[int(iid)])
            except Exception:
                pass
        return out

class MainWindow:
    def __init__(self, root: tk.Tk, cfg: Defaults) -> None:
        self.root = root
        self.cfg = cfg
        self.root.title("QQ音乐歌单转B站音频工具（优化版）")
        self.root.geometry("1100x740")
        self.root.minsize(980, 640)

        # logging
        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self._setup_logging()

        self.is_running = False
        self.cancel_event = threading.Event()

        # vars
        self.playlist_url = tk.StringVar(value=cfg.playlist_url)
        self.keep_collab = tk.BooleanVar(value=cfg.keep_collab)
        self.playlist_best_by_views = tk.BooleanVar(value=cfg.playlist_best_by_views)
        self.start = tk.StringVar(value=str(cfg.start))
        self.limit = tk.StringVar(value=str(cfg.limit))
        self.outdir = tk.StringVar(value=os.path.abspath(cfg.outdir))
        self.audio_dir = tk.StringVar(value=os.path.abspath(cfg.audio_dir))
        self.audio_format = tk.StringVar(value=cfg.audio_format)
        self.audio_quality = tk.StringVar(value=str(cfg.audio_quality))
        self.no_download = tk.BooleanVar(value=cfg.no_download)

        self.single_query = tk.StringVar(value="")
        self.single_max = tk.StringVar(value=str(cfg.single_max_results))

        self.nav = tk.StringVar(value="playlist")

        self._build()
        self.root.after(100, self._drain_logs)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _setup_logging(self) -> None:
        logger = logging.getLogger()
        logger.setLevel(logging.INFO)
        for h in list(logger.handlers):
            logger.removeHandler(h)
        fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        logger.addHandler(sh)
        th = TkTextHandler(self.log_queue)
        th.setFormatter(fmt)
        logger.addHandler(th)

    def _build(self) -> None:
        self.root.columnconfigure(0, weight=0)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=0)
        self.root.rowconfigure(2, weight=1)

        sidebar = ttk.Frame(self.root)
        sidebar.grid(row=0, column=0, rowspan=3, sticky="ns", padx=(10,6), pady=10)
        ttk.Label(sidebar, text="功能", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w", padx=8, pady=(0,10))
        ttk.Radiobutton(sidebar, text="歌单批量处理", value="playlist", variable=self.nav, command=self._switch).grid(row=1, column=0, sticky="ew", padx=6, pady=4)
        ttk.Radiobutton(sidebar, text="单曲精准搜索", value="single", variable=self.nav, command=self._switch).grid(row=2, column=0, sticky="ew", padx=6, pady=4)
        ttk.Separator(sidebar).grid(row=3, column=0, sticky="ew", padx=6, pady=10)
        ttk.Button(sidebar, text="打开下载目录", command=self.open_audio_dir).grid(row=4, column=0, sticky="ew", padx=6, pady=4)
        self.btn_cancel = ttk.Button(sidebar, text="取消任务", command=self.cancel_task, state="disabled")
        self.btn_cancel.grid(row=5, column=0, sticky="ew", padx=6, pady=4)

        self.content = ttk.Frame(self.root)
        self.content.grid(row=0, column=1, sticky="nsew", padx=(6,10), pady=10)
        self.content.columnconfigure(0, weight=1)
        self.content.rowconfigure(0, weight=1)

        self.playlist_panel = PlaylistPanel(self.content, self)
        self.single_panel = SinglePanel(self.content, self)
        self.playlist_panel.grid(row=0, column=0, sticky="nsew")
        self.single_panel.grid(row=0, column=0, sticky="nsew")
        self.single_panel.grid_remove()

        status = ttk.Frame(self.root)
        status.grid(row=1, column=1, sticky="ew", padx=(6,10), pady=(0,6))
        status.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(status, mode="determinate")
        self.progress.grid(row=0, column=0, sticky="ew", padx=(0,10))
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(status, textvariable=self.status_var).grid(row=0, column=1, sticky="e")

        logf = ttk.LabelFrame(self.root, text="实时日志")
        logf.grid(row=2, column=1, sticky="nsew", padx=(6,10), pady=(0,10))
        logf.columnconfigure(0, weight=1)
        logf.rowconfigure(0, weight=1)
        self.log_text = tk.Text(logf, wrap=tk.WORD)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(logf, command=self.log_text.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=sb.set)

        btns = ttk.Frame(logf)
        btns.grid(row=1, column=0, columnspan=2, sticky="ew", pady=6)
        ttk.Button(btns, text="清空日志", command=lambda: self.log_text.delete("1.0", tk.END)).pack(side="left", padx=6)
        ttk.Button(btns, text="复制日志", command=self.copy_log).pack(side="left", padx=6)

    def _switch(self) -> None:
        if self.is_running:
            messagebox.showinfo("提示", "任务运行中，暂不能切换。")
            self.nav.set("playlist" if self.playlist_panel.winfo_ismapped() else "single")
            return
        if self.nav.get() == "playlist":
            self.single_panel.grid_remove()
            self.playlist_panel.grid()
        else:
            self.playlist_panel.grid_remove()
            self.single_panel.grid()

    def _drain_logs(self) -> None:
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.log_text.insert(tk.END, msg + "\n")
                self.log_text.see(tk.END)
        except queue.Empty:
            pass
        self.root.after(100, self._drain_logs)

    def set_progress(self, done: int, total: int) -> None:
        def _do():
            self.progress["maximum"] = max(1, total)
            self.progress["value"] = done
        self.root.after(0, _do)

    def set_status(self, text: str) -> None:
        self.root.after(0, lambda: self.status_var.set(text))

    def _set_running(self, running: bool) -> None:
        self.is_running = running
        self.btn_cancel.configure(state="normal" if running else "disabled")

    def cancel_task(self) -> None:
        self.cancel_event.set()
        logging.info("用户请求取消任务...")

    def pick_outdir(self) -> None:
        p = filedialog.askdirectory(title="选择输出目录")
        if p:
            self.outdir.set(p)

    def pick_audio_dir(self) -> None:
        p = filedialog.askdirectory(title="选择音频目录")
        if p:
            self.audio_dir.set(p)

    def open_audio_dir(self) -> None:
        p = self.audio_dir.get().strip()
        if not p:
            messagebox.showinfo("提示", "请先设置音频下载目录")
            return
        os.makedirs(p, exist_ok=True)
        try:
            os.startfile(p)  # Windows
        except Exception as e:
            messagebox.showerror("错误", f"无法打开目录：{e}")

    def copy_log(self) -> None:
        t = self.log_text.get("1.0", tk.END)
        self.root.clipboard_clear()
        self.root.clipboard_append(t)
        messagebox.showinfo("提示", "日志已复制到剪贴板")

    def _cfg_from_ui(self) -> Defaults:
        # 基础校验与落盘路径
        outdir = ensure_writable_dir(self.outdir.get())
        audio_dir = ensure_writable_dir(self.audio_dir.get())
        playlist_url = self.playlist_url.get().strip()
        if playlist_url and not validate_url(playlist_url):
            raise ValueError("歌单URL格式不合法")

        return Defaults(
            user_agent=self.cfg.user_agent,
            timeout=self.cfg.timeout,
            playlist_url=playlist_url or self.cfg.playlist_url,
            start=int(self.start.get() or 0),
            limit=int(self.limit.get() or 0),
            keep_collab=bool(self.keep_collab.get()),
            checkpoint=self.cfg.checkpoint,
            rate=self.cfg.rate,
            min_sleep=self.cfg.min_sleep,
            max_sleep=self.cfg.max_sleep,
            retry_search=self.cfg.retry_search,
            retry_download=self.cfg.retry_download,
            backoff_base=self.cfg.backoff_base,
            outdir=outdir,
            audio_dir=audio_dir,
            no_download=bool(self.no_download.get()),
            audio_format=self.audio_format.get(),
            audio_quality=self.audio_quality.get(),
            single_max_results=int(self.single_max.get() or 20),
            enrich_detail=self.cfg.enrich_detail,
            playlist_best_by_views=bool(self.playlist_best_by_views.get()),
            playlist_search_max_results=self.cfg.playlist_search_max_results,
            playlist_candidate_limit=self.cfg.playlist_candidate_limit,
            playlist_detail_top_k=self.cfg.playlist_detail_top_k,
            playlist_score_min=self.cfg.playlist_score_min,
            playlist_allow_cover=self.cfg.playlist_allow_cover,
            hard_filter_keywords=self.cfg.hard_filter_keywords,
            soft_penalty_keywords=self.cfg.soft_penalty_keywords,
            official_boost_keywords=self.cfg.official_boost_keywords,
            score_weights=self.cfg.score_weights,
            duration_min_s=self.cfg.duration_min_s,
            duration_max_s=self.cfg.duration_max_s,
            duration_strong_bonus_diff_s=self.cfg.duration_strong_bonus_diff_s,
            duration_strong_penalty_diff_s=self.cfg.duration_strong_penalty_diff_s,
            aux_sort_publish_time=self.cfg.aux_sort_publish_time,
            aux_sort_like_count=self.cfg.aux_sort_like_count,
        )

    def start_playlist(self) -> None:
        if self.is_running:
            return
        try:
            cfg = self._cfg_from_ui()
        except Exception as e:
            messagebox.showerror("参数错误", str(e))
            return

        self.cancel_event.clear()
        self._set_running(True)
        self.set_status("处理中(歌单)...")
        logging.info("开始歌单处理 | format=%s | quality=%s", cfg.audio_format, describe_audio_quality(cfg.audio_format, cfg.audio_quality))

        def worker():
            try:
                res = process_playlist(
                    cfg,
                    progress_cb=lambda d,t,stage: (self.set_progress(d,t), self.set_status(stage)),
                    cancel_event=self.cancel_event,
                )
                logging.info("完成：excel=%s | 下载成功=%d | 失败=%d", res.excel_resource, res.downloaded, len(res.failed_downloads))
                self.root.after(0, lambda: messagebox.showinfo("完成", "歌单处理完成"))
            except Exception as e:
                logging.exception("歌单处理失败")
                err_msg = str(e)
                self.root.after(0, lambda msg=err_msg: messagebox.showerror("错误", msg))
            finally:
                self._set_running(False)
                self.set_status("就绪")

        threading.Thread(target=worker, daemon=True).start()

    def start_single_search(self) -> None:
        if self.is_running:
            return
        q = self.single_query.get().strip()
        if not q:
            messagebox.showinfo("提示", "请输入关键词")
            return
        try:
            cfg = self._cfg_from_ui()
        except Exception as e:
            messagebox.showerror("参数错误", str(e))
            return

        self.cancel_event.clear()
        self._set_running(True)
        self.set_status("处理中(搜索)...")
        max_results = int(self.single_max.get() or 20)
        logging.info("开始单曲搜索：%s | max_results=%d", q, max_results)

        def worker():
            try:
                results = search_single(
                    cfg,
                    query=q,
                    max_results=max_results,
                    enrich_detail=cfg.enrich_detail,
                    progress_cb=lambda d,t,stage: (self.set_progress(d,t), self.set_status(stage)),
                    cancel_event=self.cancel_event,
                )
                self.root.after(0, lambda: self.single_panel.set_results(results))
                self.root.after(0, lambda: messagebox.showinfo("完成", f"搜索完成：{len(results)} 条"))
            except Exception as e:
                logging.exception("单曲搜索失败")
                err_msg = str(e)
                self.root.after(0, lambda msg=err_msg: messagebox.showerror("错误", msg))
            finally:
                self._set_running(False)
                self.set_status("就绪")
        threading.Thread(target=worker, daemon=True).start()

    def start_single_download(self) -> None:
        if self.is_running:
            return
        selected = self.single_panel.selected_items()
        if not selected:
            messagebox.showinfo("提示", "请先选择列表项")
            return
        try:
            cfg = self._cfg_from_ui()
        except Exception as e:
            messagebox.showerror("参数错误", str(e))
            return

        self.cancel_event.clear()
        self._set_running(True)
        self.set_status("处理中(下载)...")
        logging.info("开始下载选中项：%d 条 | format=%s | quality=%s", len(selected), cfg.audio_format, describe_audio_quality(cfg.audio_format, cfg.audio_quality))

        def worker():
            try:
                ok, failed = download_selected(
                    cfg,
                    items=selected,
                    progress_cb=lambda d,t,stage: (self.set_progress(d,t), self.set_status(stage)),
                    cancel_event=self.cancel_event,
                )
                logging.info("选中下载完成：成功=%d 失败=%d", ok, len(failed))
                self.root.after(0, lambda: messagebox.showinfo("完成", f"下载完成：成功 {ok}，失败 {len(failed)}"))
            except Exception as e:
                logging.exception("选中下载失败")
                err_msg = str(e)
                self.root.after(0, lambda msg=err_msg: messagebox.showerror("错误", msg))
            finally:
                self._set_running(False)
                self.set_status("就绪")
        threading.Thread(target=worker, daemon=True).start()

    def _on_close(self) -> None:
        try:
            # 保存配置（路径/格式等）
            cfg = self._cfg_from_ui()
            save_user_config(cfg)
        except Exception:
            pass
        self.root.destroy()

def run_gui(cfg: Defaults) -> None:
    root = ThemedTk(theme="arc")
    MainWindow(root, cfg)
    root.mainloop()
