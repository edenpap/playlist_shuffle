# -*- coding: utf-8 -*-
"""
노래 분할기 라이선스 키 발급기 (배포자 전용 - 사용자에게 주지 마세요)

- 비밀키 위치: 홈 폴더/PlaylistSplitter-keys/private_key.txt (keygen.py 와 같은 위치, 서로 호환)
- 발급 기록: 같은 폴더의 issued_keys.csv
"""
import csv
import datetime as dt
import os
import re
import shutil
import subprocess
import sys
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import ed25519_min  # noqa: E402
import licensing    # noqa: E402
from tkhelpers import install_edit_helpers, paste_into  # noqa: E402

APP_NAME = "라이선스 키 발급기"
KEY_DIR = os.environ.get("KEYMAKER_DIR") or os.path.join(os.path.expanduser("~"), "PlaylistSplitter-keys")
PRIV = os.path.join(KEY_DIR, "private_key.txt")
LOG = os.path.join(KEY_DIR, "issued_keys.csv")
CODE_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}$")
LOG_HEADER = ["발급일", "이름", "이메일", "기기코드", "만료일", "키"]
PERIODS = [("30일", 30), ("90일", 90), ("180일", 180), ("1년", 365), ("날짜 지정", None)]


def pubkey_file_text(pub_hex):
    return ("# 라이선스 확인용 공개키 (키 발급기가 만든 파일)\n"
            "# 공개키는 GitHub에 올려도 안전합니다. 비밀키(private_key.txt)는 절대 올리지 마세요.\n"
            f'PUBLIC_KEY_HEX = "{pub_hex}"\n')


def create_secret():
    os.makedirs(KEY_DIR, exist_ok=True)
    secret = os.urandom(32)
    with open(PRIV, "w") as f:
        f.write(secret.hex() + "\n")
    try:
        os.chmod(PRIV, 0o600)
    except OSError:
        pass
    with open(os.path.join(KEY_DIR, "license_pubkey.py"), "w", encoding="utf-8") as f:
        f.write(pubkey_file_text(ed25519_min.public_key(secret).hex()))
    return secret


def load_secret():
    with open(PRIV) as f:
        v = f.read().strip()
    secret = bytes.fromhex(v)
    if len(secret) != 32:
        raise ValueError("비밀키 형식이 올바르지 않습니다.")
    return secret


def read_log():
    if not os.path.isfile(LOG):
        return []
    with open(LOG, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def append_log(row):
    new = not os.path.isfile(LOG)
    with open(LOG, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(LOG_HEADER)
        w.writerow([row[h] for h in LOG_HEADER])


def open_folder(path):
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


class SetupDialog(tk.Toplevel):
    """비밀키가 없을 때: 새로 만들기 / 백업에서 불러오기"""

    def __init__(self, master):
        super().__init__(master)
        self.title(APP_NAME)
        self.resizable(False, False)
        self.result = None
        f = ttk.Frame(self, padding=20)
        f.pack()
        ttk.Label(f, text="처음 사용합니다", font=("", 15, "bold")).pack(anchor="w")
        ttk.Label(f, justify="left", wraplength=420, text=(
            "라이선스 키에 서명할 비밀키가 이 컴퓨터에 없습니다.\n\n"
            "• 처음이라면 '새로 만들기'를 누르세요.\n"
            "• 다른 컴퓨터에서 쓰던 비밀키를 백업해 두었다면 '백업에서 불러오기'로 "
            "private_key.txt 를 고르세요. (새로 만들면 기존 사용자 키와 맞지 않게 됩니다)"
        )).pack(anchor="w", pady=(8, 14))
        b = ttk.Frame(f)
        b.pack(anchor="w")
        ttk.Button(b, text="새로 만들기", command=self._new).pack(side="left")
        ttk.Button(b, text="백업에서 불러오기...", command=self._restore).pack(side="left", padx=6)
        ttk.Button(b, text="취소", command=self.destroy).pack(side="left")
        self.lift()
        self.focus_force()
        self.grab_set()

    def _new(self):
        self.result = create_secret()
        self.destroy()

    def _restore(self):
        path = filedialog.askopenfilename(title="백업한 private_key.txt 선택", parent=self)
        if not path:
            return
        try:
            secret = bytes.fromhex(open(path).read().strip())
            assert len(secret) == 32
        except Exception:
            messagebox.showerror(APP_NAME, "비밀키 파일이 아닙니다.", parent=self)
            return
        os.makedirs(KEY_DIR, exist_ok=True)
        shutil.copyfile(path, PRIV)
        try:
            os.chmod(PRIV, 0o600)
        except OSError:
            pass
        with open(os.path.join(KEY_DIR, "license_pubkey.py"), "w", encoding="utf-8") as f:
            f.write(pubkey_file_text(ed25519_min.public_key(secret).hex()))
        self.result = secret
        self.destroy()


class KeyMaker(tk.Tk):
    def __init__(self, secret):
        super().__init__()
        self.secret = secret
        self.pub_hex = ed25519_min.public_key(secret).hex()
        self.title(APP_NAME)
        self.minsize(760, 640)
        self.geometry("820x700")
        install_edit_helpers(self)

        self.code_var = tk.StringVar()
        self.name_var = tk.StringVar()
        self.email_var = tk.StringVar()
        self.period_var = tk.StringVar(value="30일")
        self.date_var = tk.StringVar()
        self.until_var = tk.StringVar()
        self.status_var = tk.StringVar()
        self.last = None

        self._build()
        self._update_until()
        self._load_log()
        self._check_pubkey()

    # ---------- 화면 ----------
    def _build(self):
        root = ttk.Frame(self, padding=14)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)

        form = ttk.LabelFrame(root, text="신청 정보 (구글 폼 응답에서 옮겨 적기)", padding=10)
        form.grid(row=0, column=0, sticky="ew")
        form.columnconfigure(1, weight=1)
        rows = (("기기 코드", self.code_var), ("이름", self.name_var), ("이메일", self.email_var))
        for i, (label, var) in enumerate(rows):
            ttk.Label(form, text=label).grid(row=i, column=0, sticky="w", pady=3, padx=(0, 8))
            e = ttk.Entry(form, textvariable=var)
            e.grid(row=i, column=1, sticky="ew", pady=3)
            ttk.Button(form, text="붙여넣기", command=lambda w=e: self._paste(w)).grid(row=i, column=2, padx=(6, 0))
            if i == 0:
                self.code_entry = e
                e.bind("<FocusOut>", lambda ev: self.code_var.set(licensing.normalize_code(self.code_var.get())))

        ttk.Label(form, text="사용 기간").grid(row=3, column=0, sticky="w", pady=(8, 3))
        pr = ttk.Frame(form)
        pr.grid(row=3, column=1, columnspan=2, sticky="w", pady=(8, 3))
        for label, _ in PERIODS:
            ttk.Radiobutton(pr, text=label, value=label, variable=self.period_var,
                            command=self._update_until).pack(side="left", padx=(0, 8))
        de = ttk.Entry(pr, textvariable=self.date_var, width=12)
        de.pack(side="left")
        de.bind("<KeyRelease>", lambda e: (self.period_var.set("날짜 지정"), self._update_until()))
        ttk.Label(form, textvariable=self.until_var, foreground="gray").grid(row=4, column=1, sticky="w")

        ttk.Button(form, text="키 만들기", command=self._make).grid(row=5, column=1, sticky="w", pady=(10, 0))

        out = ttk.LabelFrame(root, text="만든 키", padding=10)
        out.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self.key_text = tk.Text(out, height=3, wrap="char", state="disabled")
        self.key_text.pack(fill="x")
        ob = ttk.Frame(out)
        ob.pack(anchor="w", pady=(8, 0))
        ttk.Button(ob, text="키 복사", command=self._copy_key).pack(side="left")
        ttk.Button(ob, text="메일 내용 복사", command=self._copy_mail).pack(side="left", padx=6)
        ttk.Button(ob, text="메일 앱으로 보내기", command=self._send_mail).pack(side="left")

        logf = ttk.LabelFrame(root, text="발급 기록  ·  더블클릭하면 같은 사람으로 연장 발급", padding=10)
        logf.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        root.rowconfigure(2, weight=1)
        cols = ("issued", "name", "email", "code", "expires")
        self.tree = ttk.Treeview(logf, columns=cols, show="headings", height=8)
        for c, label, w in (("issued", "발급일", 90), ("name", "이름", 110), ("email", "이메일", 200),
                            ("code", "기기 코드", 100), ("expires", "만료일", 100)):
            self.tree.heading(c, text=label)
            self.tree.column(c, width=w, anchor="w")
        sb = ttk.Scrollbar(logf, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.tag_configure("expired", foreground="gray")
        self.tree.bind("<Double-1>", self._renew)

        bottom = ttk.Frame(root)
        bottom.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(bottom, textvariable=self.status_var, wraplength=520, justify="left").pack(side="left")
        ttk.Button(bottom, text="공개키 파일 저장...", command=self._save_pubkey).pack(side="right")
        ttk.Button(bottom, text="키 폴더 열기", command=lambda: open_folder(KEY_DIR)).pack(side="right", padx=6)

    # ---------- 동작 ----------
    def _paste(self, entry):
        entry.delete(0, "end")
        paste_into(entry)
        if entry is self.code_entry:
            self.code_var.set(licensing.normalize_code(self.code_var.get()))

    def _expiry(self):
        label = self.period_var.get()
        days = dict(PERIODS).get(label)
        if days:
            return dt.date.today() + dt.timedelta(days=days)
        try:
            return dt.date.fromisoformat(self.date_var.get().strip())
        except ValueError:
            return None

    def _update_until(self):
        d = self._expiry()
        self.until_var.set(f"→ {d.isoformat()}까지 사용" if d else "→ 날짜를 2026-12-31 형식으로 입력하세요")

    def _make(self):
        code = licensing.normalize_code(self.code_var.get())
        self.code_var.set(code)
        name = self.name_var.get().strip()
        email = self.email_var.get().strip()
        expires = self._expiry()
        if not CODE_RE.match(code):
            messagebox.showwarning(APP_NAME, "기기 코드 형식이 아닙니다.\n신청서의 8자리 코드(예: K7F2-9QXA)를 확인해 주세요.")
            return
        if not name:
            messagebox.showwarning(APP_NAME, "이름을 입력해 주세요.")
            return
        if not expires:
            messagebox.showwarning(APP_NAME, "사용 기한 날짜를 2026-12-31 형식으로 입력해 주세요.")
            return
        if expires < dt.date.today():
            messagebox.showwarning(APP_NAME, "사용 기한이 오늘보다 이전입니다.")
            return

        key = licensing.make_key(self.secret, code, expires, name)
        info = licensing.parse_key(key, self.pub_hex)
        assert info["code"] == code and info["expires"] == expires

        self.last = {"발급일": dt.date.today().isoformat(), "이름": name, "이메일": email,
                     "기기코드": code, "만료일": expires.isoformat(), "키": key}
        append_log(self.last)
        self.key_text.configure(state="normal")
        self.key_text.delete("1.0", "end")
        self.key_text.insert("1.0", key)
        self.key_text.configure(state="disabled")
        self._load_log()
        self.status_var.set(f"{name}님 키를 만들었습니다 ({expires.isoformat()}까지). 메일로 보내 주세요.")

    def _mail(self):
        r = self.last
        subject = "노래 분할기 라이선스 키"
        body = (f"{r['이름']}님, 안녕하세요.\n\n"
                f"노래 분할기 라이선스 키를 보내 드립니다.\n"
                f"사용 기한: {r['만료일']}까지\n\n"
                f"프로그램을 열고 '받은 라이선스 키' 칸에 아래 키를 그대로 붙여 넣은 뒤 등록을 눌러 주세요.\n\n"
                f"{r['키']}\n")
        return subject, body

    def _need_key(self):
        if not self.last:
            messagebox.showinfo(APP_NAME, "먼저 '키 만들기'를 눌러 주세요.")
            return False
        return True

    def _clip(self, text, msg):
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status_var.set(msg)

    def _copy_key(self):
        if self._need_key():
            self._clip(self.last["키"], "키를 복사했습니다.")

    def _copy_mail(self):
        if self._need_key():
            subject, body = self._mail()
            self._clip(body, "메일 내용을 복사했습니다. 메일 본문에 붙여 넣으세요.")

    def _send_mail(self):
        if not self._need_key():
            return
        subject, body = self._mail()
        to = self.last["이메일"]
        webbrowser.open(f"mailto:{quote(to)}?subject={quote(subject)}&body={quote(body)}")
        self.status_var.set("메일 앱을 열었습니다. 내용 확인 후 보내기를 누르세요. "
                            "(메일 앱이 안 열리면 '메일 내용 복사'를 쓰세요)")

    def _load_log(self):
        self.tree.delete(*self.tree.get_children())
        today = dt.date.today().isoformat()
        self.log_rows = list(reversed(read_log()))
        for i, r in enumerate(self.log_rows):
            tags = ("expired",) if r.get("만료일", "") < today else ()
            self.tree.insert("", "end", iid=str(i), tags=tags, values=(
                r.get("발급일", ""), r.get("이름", ""), r.get("이메일", ""), r.get("기기코드", ""), r.get("만료일", "")))

    def _renew(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        r = self.log_rows[int(iid)]
        self.code_var.set(r.get("기기코드", ""))
        self.name_var.set(r.get("이름", ""))
        self.email_var.set(r.get("이메일", ""))
        self.status_var.set(f"{r.get('이름', '')}님 연장: 사용 기간을 고르고 '키 만들기'를 누르세요. "
                            f"(지금 키 만료일 {r.get('만료일', '')})")

    def _check_pubkey(self):
        built_in = licensing.PUBLIC_KEY_HEX
        if built_in and built_in != self.pub_hex:
            self.status_var.set("⚠ 이 발급기에 들어 있는 공개키와 지금 비밀키가 다릅니다. "
                                "이 비밀키로 만든 키는 현재 배포된 프로그램에서 열리지 않을 수 있습니다.")
        elif not built_in:
            self.status_var.set("공개키 파일(license_pubkey.py)을 GitHub에 올렸는지 확인하세요. "
                                "필요하면 '공개키 파일 저장...'으로 다시 저장할 수 있습니다.")
        else:
            self.status_var.set("비밀키와 배포된 공개키가 일치합니다. 키를 발급할 수 있습니다.")

    def _save_pubkey(self):
        path = filedialog.asksaveasfilename(title="공개키 파일 저장", initialfile="license_pubkey.py",
                                            defaultextension=".py", filetypes=[("Python", "*.py")])
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(pubkey_file_text(self.pub_hex))
            messagebox.showinfo(APP_NAME, "저장했습니다. 이 파일을 GitHub 저장소에 올리고 새 릴리스를 만드세요.")


def selftest():
    import tempfile
    global KEY_DIR, PRIV, LOG
    KEY_DIR = tempfile.mkdtemp()
    PRIV, LOG = os.path.join(KEY_DIR, "private_key.txt"), os.path.join(KEY_DIR, "issued_keys.csv")
    secret = create_secret()
    assert load_secret() == secret
    pub = ed25519_min.public_key(secret).hex()
    key = licensing.make_key(secret, "K7F2-9QXA", dt.date.today() + dt.timedelta(days=30), "테스트")
    info = licensing.parse_key(key, pub)
    assert info["code"] == "K7F2-9QXA" and info["name"] == "테스트"
    append_log({"발급일": "2026-01-01", "이름": "테스트", "이메일": "a@b.c", "기기코드": "K7F2-9QXA",
                "만료일": "2026-02-01", "키": key})
    assert read_log()[0]["이름"] == "테스트"
    print("SELFTEST OK")


def main():
    if "--selftest" in sys.argv:
        try:
            selftest()
            sys.exit(0)
        except Exception as e:
            print(f"SELFTEST FAILED: {e!r}")
            sys.exit(1)

    holder = tk.Tk()
    holder.withdraw()
    if os.path.isfile(PRIV):
        try:
            secret = load_secret()
        except Exception as e:
            messagebox.showerror(APP_NAME, f"비밀키를 읽을 수 없습니다.\n{PRIV}\n{e}")
            return
        holder.destroy()
    else:
        d = SetupDialog(holder)
        holder.wait_window(d)
        secret = d.result
        if not secret:
            holder.destroy()
            return
        messagebox.showinfo(APP_NAME, (
            "비밀키를 준비했습니다.\n\n"
            "1) 다음 화면 아래 '공개키 파일 저장...'으로 license_pubkey.py 를 저장해 GitHub에 올리고 새 릴리스를 만드세요.\n"
            f"2) 비밀키 파일을 USB 등에 백업하세요:\n{PRIV}\n\n"
            "비밀키는 GitHub, 메일, 메신저로 절대 보내지 마세요."), parent=holder)
        holder.destroy()
    KeyMaker(secret).mainloop()


if __name__ == "__main__":
    main()
