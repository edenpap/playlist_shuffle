# -*- coding: utf-8 -*-
"""두 앱(노래 분할기, 키 발급기)이 같이 쓰는 Tk 보조 기능"""
import sys
import tkinter as tk

# ---------- 복사/붙여넣기 보완 ----------
# 맥에서 한글 입력 상태일 때 Cmd+V 가 'Cmd+ㅍ' 로 들어와 붙여넣기가 안 되는 Tk 문제 보완
_HANGUL_SHORTCUTS = {"ㅍ": "<<Paste>>", "ㅊ": "<<Copy>>", "ㅌ": "<<Cut>>", "ㅁ": "<<SelectAll>>", "ㅋ": "<<Undo>>"}


def _shortcut_fix(event):
    ev = _HANGUL_SHORTCUTS.get(event.char) or _HANGUL_SHORTCUTS.get(event.keysym)
    if ev:
        event.widget.event_generate(ev)
        return "break"
    return None


def install_edit_helpers(root):
    if sys.platform == "darwin":
        for cls in ("Text", "Entry", "TEntry"):
            root.bind_class(cls, "<Command-KeyPress>", _shortcut_fix, add="+")
    menu = tk.Menu(root, tearoff=0)

    def popup(event):
        w = event.widget
        menu.delete(0, "end")
        for label, ev in (("잘라내기", "<<Cut>>"), ("복사", "<<Copy>>"), ("붙여넣기", "<<Paste>>"),
                          ("전체 선택", "<<SelectAll>>")):
            menu.add_command(label=label, command=lambda e=ev: (w.focus_set(), w.event_generate(e)))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    buttons = ("<Button-2>", "<Control-Button-1>") if sys.platform == "darwin" else ("<Button-3>",)
    for cls in ("Text", "Entry", "TEntry"):
        for b in buttons:
            root.bind_class(cls, b, popup, add="+")


def paste_into(widget):
    """클립보드 내용을 위젯에 붙여 넣기 (버튼용)"""
    try:
        text = widget.clipboard_get()
    except tk.TclError:
        return False
    widget.focus_set()
    if isinstance(widget, tk.Text):
        try:
            widget.delete("sel.first", "sel.last")
        except tk.TclError:
            pass
        widget.insert("insert", text)
    else:
        widget.insert("insert", text)
    return True
