# -*- coding: utf-8 -*-
"""
노래 분할기 (Windows / macOS)
원본 오디오 + tracks.csv → 곡별 mp3 분할, 섞기, tracklist.txt
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
APP_VERSION = "1.0.0"


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
        self.minsize(640, 560)
        self.geometry("720x620")

        self.audio_var = tk.StringVar()
        self.csv_var = tk.StringVar()
        self.out_var = tk.StringVar()
        self.shuffle_var = tk.BooleanVar(value=True)
        self.seed_var = tk.StringVar()
        self.csv_info = tk.StringVar(value="CSV를 선택하면 곡 수와 고정 곡이 표시됩니다.")
        self.status_var = tk.StringVar(value="대기 중")

        self.msgs = queue.Queue()
        self.worker = None
        self.cancel = threading.Event()
        self.result_dir = None
        self._out_auto = True

        self._build()
        self.after(100, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- 화면 ----------
    def _build(self):
        pad = {"padx": 12, "pady": 6}
        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True, padx=8, pady=8)
        frm.columnconfigure(1, weight=1)

        ttk.Label(frm, text="원본 오디오").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.audio_var).grid(row=0, column=1, sticky="ew", pady=6)
        ttk.Button(frm, text="찾아보기", command=self._pick_audio).grid(row=0, column=2, **pad)

        ttk.Label(frm, text="트랙 CSV").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.csv_var).grid(row=1, column=1, sticky="ew", pady=6)
        ttk.Button(frm, text="찾아보기", command=self._pick_csv).grid(row=1, column=2, **pad)

        ttk.Label(frm, textvariable=self.csv_info, foreground="gray").grid(
            row=2, column=1, columnspan=2, sticky="w", pady=(0, 6))

        ttk.Label(frm, text="저장 폴더").grid(row=3, column=0, sticky="w", **pad)
        out_entry = ttk.Entry(frm, textvariable=self.out_var)
        out_entry.grid(row=3, column=1, sticky="ew", pady=6)
        out_entry.bind("<Key>", lambda e: setattr(self, "_out_auto", False))
        ttk.Button(frm, text="찾아보기", command=self._pick_out).grid(row=3, column=2, **pad)

        opt = ttk.Frame(frm)
        opt.grid(row=4, column=0, columnspan=3, sticky="w", padx=12, pady=6)
        ttk.Checkbutton(opt, text="섞기 (고정 곡은 맨 앞, 같은 가수는 멀리 떨어지게)",
                        variable=self.shuffle_var).pack(side="left")
        ttk.Label(opt, text="   시드").pack(side="left")
        ttk.Entry(opt, textvariable=self.seed_var, width=8).pack(side="left", padx=4)
        ttk.Label(opt, text="(비우면 매번 다른 순서)", foreground="gray").pack(side="left")

        btns = ttk.Frame(frm)
        btns.grid(row=5, column=0, columnspan=3, sticky="ew", padx=12, pady=(10, 4))
        self.start_btn = ttk.Button(btns, text="시작", command=self._start)
        self.start_btn.pack(side="left")
        self.cancel_btn = ttk.Button(btns, text="취소", command=self._cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=6)
        self.open_btn = ttk.Button(btns, text="결과 폴더 열기", command=self._open_result, state="disabled")
        self.open_btn.pack(side="left")
        self.copy_btn = ttk.Button(btns, text="tracklist 복사", command=self._copy_tracklist, state="disabled")
        self.copy_btn.pack(side="left", padx=6)

        self.bar = ttk.Progressbar(frm, mode="determinate", maximum=100)
        self.bar.grid(row=6, column=0, columnspan=3, sticky="ew", padx=12, pady=(8, 2))
        ttk.Label(frm, textvariable=self.status_var).grid(row=7, column=0, columnspan=3, sticky="w", padx=12)

        self.log = ScrolledText(frm, height=14, wrap="word", state="disabled")
        self.log.grid(row=8, column=0, columnspan=3, sticky="nsew", padx=12, pady=(6, 4))
        frm.rowconfigure(8, weight=1)

    # ---------- 파일 선택 ----------
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
        if not self.csv_var.get():
            guess = os.path.join(folder, "tracks.csv")
            if os.path.isfile(guess):
                self._set_csv(guess)

    def _pick_csv(self):
        path = filedialog.askopenfilename(title="트랙 CSV 선택", filetypes=[("CSV", "*.csv"), ("모든 파일", "*.*")])
        if path:
            self._set_csv(path)

    def _set_csv(self, path):
        self.csv_var.set(path)
        try:
            tracks, fixed, warns = core.load_tracks(path)
            info = f"{len(tracks)}곡"
            if fixed:
                info += " / 고정: " + ", ".join(f"{i}. {t}" for i, t in enumerate(fixed, 1))
            if warns:
                info += f" / 경고 {len(warns)}건"
            self.csv_info.set(info)
        except core.SplitError as e:
            self.csv_info.set(f"⚠ {e}")

    def _pick_out(self):
        path = filedialog.askdirectory(title="저장 폴더 선택")
        if path:
            self.out_var.set(path)
            self._out_auto = False

    # ---------- 실행 ----------
    def _start(self):
        audio, csv_path, out = self.audio_var.get().strip(), self.csv_var.get().strip(), self.out_var.get().strip()
        if not audio or not csv_path:
            messagebox.showwarning(APP_NAME, "원본 오디오와 트랙 CSV를 선택해 주세요.")
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
                    audio, csv_path, out, shuffle=self.shuffle_var.get(), seed=seed,
                    log=lambda s: self.msgs.put(("log", s)),
                    progress=lambda d, t: self.msgs.put(("prog", (d, t))),
                    cancel=self.cancel)
                self.msgs.put(("done", res))
            except core.Cancelled:
                self.msgs.put(("cancelled", None))
            except core.SplitError as e:
                self.msgs.put(("error", str(e)))
            except Exception as e:  # 예상 못 한 오류도 창에 표시
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

    # ---------- 로그 ----------
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
    """빌드 검증용: 내장 ffmpeg 로 짧은 소리를 만들어 2곡으로 분할/섞기"""
    import tempfile
    d = tempfile.mkdtemp()
    ff = core.find_ffmpeg()
    core.check_mp3_encoder(ff)
    src = os.path.join(d, "테스트 원본.m4a")
    subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440",
                    "-t", "12", "-c:a", "aac", src], check=True, **core._POPEN_FLAGS)
    csv_path = os.path.join(d, "tracks.csv")
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write("start,title,first\n00:00:00,가수a_첫 곡,\n00:00:05,가수b_둘째 곡,1\n")
    res = core.run(src, csv_path, os.path.join(d, "output"), seed=1, log=lambda s: None)
    lines = open(res["tracklist"], encoding="utf-8").read().splitlines()
    assert lines[0] == "01. 00:00:00 둘째 곡 - 가수b", lines
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
