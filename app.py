# -*- coding: utf-8 -*-
"""
노래 분할기 (Windows / macOS)
원본 오디오 + 타임라인 텍스트(또는 tracks.csv) → 곡별 mp3 분할, 섞기, tracklist.txt
"""
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import core

APP_NAME = "노래 분할기"
APP_VERSION = "1.1.0"

PLACEHOLDER = (
    "여기에 타임라인을 붙여 넣으세요. 예)\n"
    "[00:00](https://youtube.com/...) 버즈 - 가시\n"
    "03:56 씨야 - 사랑의 인사\n"
    "1:02:34 검정치마_기다린 만큼, 더\n\n"
    "링크, 빈 줄, 같은 줄 반복은 자동으로 정리됩니다."
)


def open_folder(path):
    try:
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as e:
        messagebox.showerror(APP_NAME, f"폴더를 열 수 없습니다.\n{e}")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} {APP_VERSION}")
        self.minsize(900, 760)
        self.geometry("1000x820")

        self.audio_var = tk.StringVar()
        self.out_var = tk.StringVar()
        self.order_var = tk.StringVar(value="artist_first")
        self.default_artist_var = tk.StringVar()
        self.fixed_var = tk.StringVar()
        self.shuffle_var = tk.BooleanVar(value=True)
        self.seed_var = tk.StringVar()
        self.info_var = tk.StringVar(value="타임라인을 붙여 넣으면 오른쪽 표에 정리된 목록이 나옵니다.")
        self.status_var = tk.StringVar(value="대기 중")

        self.rows = []          # 정리된 곡 목록
        self.fixed_keys = []    # 고정 곡 (시작 초 기준, 순서대로)
        self._placeholder_on = False
        self._parse_job = None

        self.msgs = queue.Queue()
        self.worker = None
        self.cancel = threading.Event()
        self.result_dir = None
        self.tracklist_path = None
        self._out_auto = True

        self._build()
        self._show_placeholder()
        self.after(100, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ================= 화면 =================
    def _build(self):
        root = ttk.Frame(self)
        root.pack(fill="both", expand=True, padx=10, pady=8)
        root.columnconfigure(0, weight=1)

        # --- 원본 오디오 ---
        top = ttk.Frame(root)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)
        ttk.Label(top, text="원본 오디오").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(top, textvariable=self.audio_var).grid(row=0, column=1, sticky="ew")
        ttk.Button(top, text="찾아보기", command=self._pick_audio).grid(row=0, column=2, padx=(8, 0))

        # --- 붙여넣기 / 미리보기 ---
        pane = ttk.PanedWindow(root, orient="horizontal")
        pane.grid(row=1, column=0, sticky="nsew", pady=(10, 4))
        root.rowconfigure(1, weight=3)

        left = ttk.Frame(pane)
        lhead = ttk.Frame(left)
        lhead.pack(fill="x")
        ttk.Label(lhead, text="타임라인 붙여넣기").pack(side="left")
        ttk.Button(lhead, text="지우기", command=self._clear_text).pack(side="right")
        ttk.Button(lhead, text="CSV 불러오기", command=self._load_csv).pack(side="right", padx=4)
        self.text = tk.Text(left, wrap="none", undo=True, height=16, width=42)
        self.text.pack(fill="both", expand=True, pady=(4, 0))
        self._text_fg = self.text.cget("foreground")
        self.text.bind("<<Modified>>", self._on_text_modified)
        self.text.bind("<FocusIn>", lambda e: self._hide_placeholder())
        self.text.bind("<FocusOut>", lambda e: self._show_placeholder())
        pane.add(left, weight=1)

        right = ttk.Frame(pane)
        rhead = ttk.Frame(right)
        rhead.pack(fill="x")
        ttk.Label(rhead, text="정리된 목록  ·  곡을 클릭하면 클릭한 순서대로 1, 2, 3 고정").pack(side="left")
        cols = ("fixed", "start", "artist", "song", "note")
        tv_frame = ttk.Frame(right)
        tv_frame.pack(fill="both", expand=True, pady=(4, 0))
        self.tree = ttk.Treeview(tv_frame, columns=cols, show="headings", selectmode="none")
        for c, label, w, anchor in (("fixed", "고정", 44, "center"), ("start", "시간", 76, "center"),
                                    ("artist", "가수", 140, "w"), ("song", "제목", 200, "w"),
                                    ("note", "확인", 90, "w")):
            self.tree.heading(c, text=label)
            self.tree.column(c, width=w, anchor=anchor, stretch=(c in ("artist", "song")))
        ysb = ttk.Scrollbar(tv_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        self.tree.tag_configure("fixed", background="#ffe9b3", foreground="#000000")
        self.tree.tag_configure("problem", foreground="#c62828")
        self.tree.bind("<ButtonRelease-1>", self._on_tree_click)
        pane.add(right, weight=1)

        ttk.Label(root, textvariable=self.info_var, foreground="gray").grid(row=2, column=0, sticky="w")

        # --- 목록 옵션 ---
        opt = ttk.Frame(root)
        opt.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        opt.columnconfigure(5, weight=1)
        ttk.Label(opt, text="줄 형식").grid(row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Radiobutton(opt, text="가수 - 제목", value="artist_first", variable=self.order_var,
                        command=self._reparse).grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(opt, text="제목 - 가수", value="title_first", variable=self.order_var,
                        command=self._reparse).grid(row=0, column=2, sticky="w", padx=(6, 18))
        ttk.Label(opt, text="가수 없는 곡에 넣을 가수").grid(row=0, column=3, sticky="w", padx=(0, 6))
        da = ttk.Entry(opt, textvariable=self.default_artist_var, width=16)
        da.grid(row=0, column=4, sticky="w")
        da.bind("<KeyRelease>", lambda e: self._schedule_parse())

        fx = ttk.Frame(root)
        fx.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        fx.columnconfigure(1, weight=1)
        ttk.Label(fx, text="고정 곡").grid(row=0, column=0, sticky="w", padx=(0, 8))
        fe = ttk.Entry(fx, textvariable=self.fixed_var)
        fe.grid(row=0, column=1, sticky="ew")
        fe.bind("<Return>", lambda e: self._apply_fixed_text())
        ttk.Button(fx, text="적용", command=self._apply_fixed_text).grid(row=0, column=2, padx=(6, 0))
        ttk.Button(fx, text="고정 해제", command=self._clear_fixed).grid(row=0, column=3, padx=(6, 0))
        ttk.Label(fx, text="제목을 쉼표로 적고 적용 (예: 가시, 사랑의 인사, 그 여자)",
                  foreground="gray").grid(row=1, column=1, sticky="w")

        # --- 저장 / 섞기 ---
        sv = ttk.Frame(root)
        sv.grid(row=5, column=0, sticky="ew", pady=(6, 0))
        sv.columnconfigure(1, weight=1)
        ttk.Label(sv, text="저장 폴더").grid(row=0, column=0, sticky="w", padx=(0, 8))
        oe = ttk.Entry(sv, textvariable=self.out_var)
        oe.grid(row=0, column=1, sticky="ew")
        oe.bind("<Key>", lambda e: setattr(self, "_out_auto", False))
        ttk.Button(sv, text="찾아보기", command=self._pick_out).grid(row=0, column=2, padx=(8, 0))

        sh = ttk.Frame(root)
        sh.grid(row=6, column=0, sticky="w", pady=(6, 0))
        ttk.Checkbutton(sh, text="섞기 (고정 곡은 맨 앞, 같은 가수는 멀리 떨어지게)",
                        variable=self.shuffle_var).pack(side="left")
        ttk.Label(sh, text="   시드").pack(side="left")
        ttk.Entry(sh, textvariable=self.seed_var, width=8).pack(side="left", padx=4)
        ttk.Label(sh, text="(비우면 매번 다른 순서)", foreground="gray").pack(side="left")

        # --- 실행 ---
        btns = ttk.Frame(root)
        btns.grid(row=7, column=0, sticky="ew", pady=(10, 4))
        self.start_btn = ttk.Button(btns, text="시작", command=self._start)
        self.start_btn.pack(side="left")
        self.cancel_btn = ttk.Button(btns, text="취소", command=self._cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=6)
        self.open_btn = ttk.Button(btns, text="결과 폴더 열기", command=self._open_result, state="disabled")
        self.open_btn.pack(side="left")
        self.copy_btn = ttk.Button(btns, text="tracklist 복사", command=self._copy_tracklist, state="disabled")
        self.copy_btn.pack(side="left", padx=6)
        ttk.Button(btns, text="CSV로 저장", command=self._save_csv).pack(side="right")

        self.bar = ttk.Progressbar(root, mode="determinate", maximum=100)
        self.bar.grid(row=8, column=0, sticky="ew", pady=(4, 2))
        ttk.Label(root, textvariable=self.status_var).grid(row=9, column=0, sticky="w")
        self.log = ScrolledText(root, height=7, wrap="word", state="disabled")
        self.log.grid(row=10, column=0, sticky="nsew", pady=(4, 0))
        root.rowconfigure(10, weight=1)

    # ================= 붙여넣기 칸 =================
    def _show_placeholder(self):
        if not self.text.get("1.0", "end").strip():
            self._placeholder_on = True
            self.text.insert("1.0", PLACEHOLDER)
            self.text.configure(foreground="gray")
            self.text.edit_modified(False)

    def _hide_placeholder(self):
        if self._placeholder_on:
            self._placeholder_on = False
            self.text.delete("1.0", "end")
            self.text.configure(foreground=self._text_fg)
            self.text.edit_modified(False)

    def _get_text(self):
        return "" if self._placeholder_on else self.text.get("1.0", "end")

    def _set_text(self, value):
        self._hide_placeholder()
        self.text.delete("1.0", "end")
        self.text.insert("1.0", value)
        self.text.configure(foreground=self._text_fg)
        self._reparse()

    def _clear_text(self):
        self.text.delete("1.0", "end")
        self._placeholder_on = False
        self.fixed_keys = []
        self.fixed_var.set("")
        self._reparse()
        self._show_placeholder()

    def _on_text_modified(self, _e=None):
        if self.text.edit_modified():
            self.text.edit_modified(False)
            if not self._placeholder_on:
                self._schedule_parse()

    def _schedule_parse(self):
        if self._parse_job:
            self.after_cancel(self._parse_job)
        self._parse_job = self.after(300, self._reparse)

    # ================= 목록 정리 / 표 =================
    def _reparse(self):
        self._parse_job = None
        try:
            self.rows, notes = core.parse_timeline_text(
                self._get_text(), self.order_var.get() == "artist_first", self.default_artist_var.get())
        except core.SplitError as e:
            self.rows, notes = [], [str(e)]
        keys = {r["start"] for r in self.rows}
        self.fixed_keys = [k for k in self.fixed_keys if k in keys]
        self._notes = notes
        self._refresh_tree()
        self._update_info()

    def _update_info(self):
        notes = getattr(self, "_notes", [])
        if not self.rows:
            self.info_var.set("타임라인을 붙여 넣으면 오른쪽 표에 정리된 목록이 나옵니다.")
            return
        problems = [r for r in self.rows if r["problem"]]
        info = f"{len(self.rows)}곡"
        if self.fixed_keys:
            info += f" · 고정 {len(self.fixed_keys)}곡"
        if problems:
            info += f" · 확인 필요 {len(problems)}줄 (빨간 줄)"
        if notes:
            info += " · " + " · ".join(notes)
        self.info_var.set(info)

    def _refresh_tree(self):
        top = self.tree.yview()[0]
        self.tree.delete(*self.tree.get_children())
        order = {k: n for n, k in enumerate(self.fixed_keys, start=1)}
        for i, r in enumerate(self.rows):
            tags = []
            if r["start"] in order:
                tags.append("fixed")
            if r["problem"]:
                tags.append("problem")
            self.tree.insert("", "end", iid=str(i), tags=tags, values=(
                order.get(r["start"], ""), r["start_text"], r["artist"].replace("&", " & "),
                r["song"], r["problem"]))
        self.tree.yview_moveto(top)

    def _sync_fixed_text(self):
        by_key = {r["start"]: r for r in self.rows}
        self.fixed_var.set(", ".join(by_key[k]["song"] for k in self.fixed_keys if k in by_key))

    def _on_tree_click(self, event):
        if self.tree.identify_region(event.x, event.y) in ("heading", "separator"):
            return
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        key = self.rows[int(iid)]["start"]
        if key in self.fixed_keys:
            self.fixed_keys.remove(key)
        else:
            self.fixed_keys.append(key)
        self._refresh_tree()
        self._sync_fixed_text()
        self._update_info()

    def _apply_fixed_text(self):
        if not self.rows:
            return
        idx, not_found = core.match_fixed(self.rows, self.fixed_var.get())
        self.fixed_keys = [self.rows[i]["start"] for i in idx]
        self._refresh_tree()
        self._sync_fixed_text()
        self._update_info()
        if not_found:
            messagebox.showwarning(APP_NAME, "목록에서 찾지 못한 곡이 있습니다:\n" + "\n".join(not_found))

    def _clear_fixed(self):
        self.fixed_keys = []
        self.fixed_var.set("")
        self._refresh_tree()
        self._update_info()

    # ================= 파일 =================
    def _pick_audio(self):
        path = filedialog.askopenfilename(
            title="원본 오디오 파일 선택",
            filetypes=[("오디오/영상", " ".join("*" + e for e in core.AUDIO_EXTS)), ("모든 파일", "*.*")])
        if not path:
            return
        self.audio_var.set(path)
        folder = os.path.dirname(path)
        if self._out_auto or not self.out_var.get():
            self.out_var.set(os.path.join(folder, "output"))
        guess = os.path.join(folder, "tracks.csv")
        if not self.rows and os.path.isfile(guess):
            self._load_csv(guess)

    def _load_csv(self, path=None):
        if not path:
            path = filedialog.askopenfilename(title="tracks.csv 선택", filetypes=[("CSV", "*.csv"), ("모든 파일", "*.*")])
            if not path:
                return
        try:
            tracks, fixed_idx, warns = core.load_tracks(path)
        except core.SplitError as e:
            messagebox.showerror(APP_NAME, str(e))
            return
        lines = []
        for t in tracks:
            artist, song = core.parse_artist_song(t["title"])
            lines.append(f"{core.format_hms(t['start'])} {artist} - {song}" if artist else
                         f"{core.format_hms(t['start'])} {song}")
        self.order_var.set("artist_first")
        self.fixed_keys = [tracks[i]["start"] for i in fixed_idx]
        self._set_text("\n".join(lines) + "\n")
        self._sync_fixed_text()
        if warns:
            messagebox.showwarning(APP_NAME, "\n".join(warns))

    def _save_csv(self):
        if not self.rows:
            messagebox.showinfo(APP_NAME, "저장할 목록이 없습니다.")
            return
        initial = os.path.dirname(self.audio_var.get()) if self.audio_var.get() else None
        path = filedialog.asksaveasfilename(title="CSV로 저장", defaultextension=".csv",
                                            initialfile="tracks.csv", initialdir=initial,
                                            filetypes=[("CSV", "*.csv")])
        if path:
            fixed_idx = [i for k in self.fixed_keys for i, r in enumerate(self.rows) if r["start"] == k]
            core.save_csv(self.rows, fixed_idx, path)
            self.status_var.set(f"저장했습니다: {path}")

    def _pick_out(self):
        path = filedialog.askdirectory(title="저장 폴더 선택")
        if path:
            self.out_var.set(path)
            self._out_auto = False

    # ================= 실행 =================
    def _start(self):
        if self._parse_job:
            self._reparse()
        audio, out = self.audio_var.get().strip(), self.out_var.get().strip()
        if not audio:
            messagebox.showwarning(APP_NAME, "원본 오디오 파일을 선택해 주세요.")
            return
        if not self.rows:
            messagebox.showwarning(APP_NAME, "타임라인을 붙여 넣거나 CSV를 불러와 주세요.")
            return
        problems = [r for r in self.rows if r["problem"]]
        if problems:
            detail = "\n".join(f"{r['start_text']} {r['song'] or '(제목 없음)'}: {r['problem']}" for r in problems[:10])
            messagebox.showwarning(APP_NAME, "빨간 줄을 먼저 고쳐 주세요.\n\n" + detail)
            return
        if not out:
            out = os.path.join(os.path.dirname(audio), "output")
            self.out_var.set(out)
        seed = None
        if self.seed_var.get().strip():
            try:
                seed = int(self.seed_var.get().strip())
            except ValueError:
                messagebox.showwarning(APP_NAME, "시드는 숫자로 입력해 주세요.")
                return

        tracks = [dict(r) for r in self.rows]
        fixed_idx = [i for k in self.fixed_keys for i, r in enumerate(self.rows) if r["start"] == k]

        self._clear_log()
        self.cancel.clear()
        self.result_dir = None
        self.tracklist_path = None
        self.bar["value"] = 0
        self.status_var.set("작업 중...")
        self._set_running(True)

        def work():
            try:
                res = core.run(
                    audio, tracks, fixed_idx, out, shuffle=self.shuffle_var.get(), seed=seed,
                    log=lambda s: self.msgs.put(("log", s)),
                    progress=lambda d, t: self.msgs.put(("prog", (d, t))),
                    cancel=self.cancel)
                self.msgs.put(("done", res))
            except core.Cancelled:
                self.msgs.put(("cancelled", None))
            except core.SplitError as e:
                self.msgs.put(("error", str(e)))
            except Exception as e:
                self.msgs.put(("error", f"예상하지 못한 오류: {e!r}"))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def _cancel(self):
        self.cancel.set()
        self.status_var.set("취소하는 중...")

    def _set_running(self, running):
        self.start_btn.config(state="disabled" if running else "normal")
        self.cancel_btn.config(state="normal" if running else "disabled")
        if running:
            self.open_btn.config(state="disabled")
            self.copy_btn.config(state="disabled")

    def _poll(self):
        try:
            while True:
                kind, val = self.msgs.get_nowait()
                if kind == "log":
                    self._append(val)
                elif kind == "prog":
                    d, t = val
                    self.bar["value"] = d * 100 / max(t, 1)
                    self.status_var.set(f"작업 중... {d}/{t}")
                elif kind == "done":
                    self._set_running(False)
                    self.bar["value"] = 100
                    self.result_dir = val["shuffled_dir"] or val["split_dir"]
                    self.tracklist_path = val["tracklist"]
                    self.open_btn.config(state="normal")
                    if self.tracklist_path:
                        self.copy_btn.config(state="normal")
                    msg = "완료되었습니다."
                    if val["failed"]:
                        msg += f" (실패 {len(val['failed'])}곡: 로그 확인)"
                    self.status_var.set(msg)
                elif kind == "cancelled":
                    self._set_running(False)
                    self.status_var.set("취소되었습니다.")
                    self._append("\n취소되었습니다.")
                elif kind == "error":
                    self._set_running(False)
                    self.status_var.set("오류")
                    self._append(f"\n[오류] {val}")
                    messagebox.showerror(APP_NAME, val)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _open_result(self):
        if self.result_dir and os.path.isdir(self.result_dir):
            open_folder(self.result_dir)

    def _copy_tracklist(self):
        if self.tracklist_path and os.path.isfile(self.tracklist_path):
            with open(self.tracklist_path, encoding="utf-8") as f:
                text = f.read()
            self.clipboard_clear()
            self.clipboard_append(text)
            self.status_var.set("tracklist 내용을 클립보드에 복사했습니다.")

    # ================= 로그 =================
    def _append(self, text):
        self.log.config(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def _clear_log(self):
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")

    def _on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(APP_NAME, "작업 중입니다. 취소하고 종료할까요?"):
                return
            self.cancel.set()
            self.worker.join(timeout=3)
        self.destroy()


def selftest():
    """빌드 검증용: 내장 ffmpeg 로 짧은 소리를 만들어 붙여넣기 텍스트 방식으로 분할/섞기"""
    import tempfile
    d = tempfile.mkdtemp()
    ff = core.find_ffmpeg()
    core.check_mp3_encoder(ff)
    src = os.path.join(d, "테스트 원본.m4a")
    subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440",
                    "-t", "12", "-c:a", "aac", src], check=True, **core._POPEN_FLAGS)
    text = ("[00:01](https://www.youtube.com/watch?v=x) 가수a - 첫 곡\n"
            "[00:01](https://www.youtube.com/watch?v=x) 가수a - 첫 곡\n"
            "[00:05](https://www.youtube.com/watch?v=x&t=5s) 가수b - 둘째 곡 (Feat. 가수c)\n")
    rows, _ = core.parse_timeline_text(text, artist_first=True)
    idx, missing = core.match_fixed(rows, "둘째 곡")
    assert len(rows) == 2 and idx == [1] and not missing, (rows, idx, missing)
    res = core.run(src, rows, idx, os.path.join(d, "output"), seed=1, log=lambda s: None)
    lines = open(res["tracklist"], encoding="utf-8").read().splitlines()
    assert lines[0] == "01. 00:00:00 둘째 곡 - 가수b & 가수c", lines
    assert lines[1] == "02. 00:00:07 첫 곡 - 가수a", lines
    print("SELFTEST OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        try:
            selftest()
            sys.exit(0)
        except Exception as e:
            print(f"SELFTEST FAILED: {e!r}")
            sys.exit(1)
    App().mainloop()
