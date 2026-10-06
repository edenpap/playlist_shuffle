#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
노래 분할기 라이선스 키 발급 도구 (배포자 전용 - 사용자에게 주지 마세요)

    python3 owner_tools/keygen.py

처음 실행하면 발급용 비밀키를 만들고, 그다음부터는
기기 코드 / 이름 / 기간을 넣으면 라이선스 키를 만들어 줍니다.
비밀키 위치: 홈 폴더의 PlaylistSplitter-keys/private_key.txt
"""
import csv
import datetime as dt
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

import ed25519_min  # noqa: E402
import licensing    # noqa: E402

KEY_DIR = os.path.join(os.path.expanduser("~"), "PlaylistSplitter-keys")
PRIV = os.path.join(KEY_DIR, "private_key.txt")
LOG = os.path.join(KEY_DIR, "issued_keys.csv")
CODE_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}$")


def copy_to_clipboard(text):
    try:
        if sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True,
                           env={**os.environ, "LANG": "en_US.UTF-8"})
        elif sys.platform == "win32":
            subprocess.run(["clip"], input=text.encode("utf-16-le"), check=True)
        else:
            subprocess.run(["xclip", "-selection", "clipboard"], input=text.encode("utf-8"), check=True)
        return True
    except Exception:
        return False


def pubkey_file_text(pub_hex):
    return ("# 라이선스 확인용 공개키 (owner_tools/keygen.py 가 만든 파일)\n"
            "# 공개키는 GitHub에 올려도 안전합니다. 비밀키(private_key.txt)는 절대 올리지 마세요.\n"
            f'PUBLIC_KEY_HEX = "{pub_hex}"\n')


def setup():
    print("=" * 60)
    print("처음 실행입니다. 라이선스 키를 서명할 '비밀키'를 만듭니다.")
    print(f"저장 위치: {PRIV}")
    print("=" * 60)
    if input("만들까요? (y/n): ").strip().lower() != "y":
        sys.exit("취소했습니다.")
    os.makedirs(KEY_DIR, exist_ok=True)
    secret = os.urandom(32)
    with open(PRIV, "w") as f:
        f.write(secret.hex() + "\n")
    try:
        os.chmod(PRIV, 0o600)
    except OSError:
        pass
    pub_hex = ed25519_min.public_key(secret).hex()
    text = pubkey_file_text(pub_hex)
    with open(os.path.join(KEY_DIR, "license_pubkey.py"), "w", encoding="utf-8") as f:
        f.write(text)
    with open(os.path.join(REPO, "license_pubkey.py"), "w", encoding="utf-8") as f:
        f.write(text)
    print()
    print("완료! 꼭 해야 할 일 2가지:")
    print(f"  1) {os.path.join(REPO, 'license_pubkey.py')}")
    print("     이 파일을 GitHub 저장소에 올리고 새 릴리스를 만드세요.")
    print("     (이 파일이 들어간 버전부터 라이선스 키로 열립니다)")
    print(f"  2) {PRIV}")
    print("     이 비밀키 파일을 USB나 비밀번호 관리자 등에 따로 백업하세요.")
    print("     잃어버리면 기존 사용자에게 새 키를 줄 수 없고, 누가 가져가면 키를 마음대로 만들 수 있습니다.")
    print("     GitHub, 메일, 메신저로 절대 보내지 마세요.")
    print()


def load_secret():
    with open(PRIV) as f:
        return bytes.fromhex(f.read().strip())


def ask_expiry():
    while True:
        v = input("사용 기간 (Enter=30일, 숫자=일수, 또는 2026-12-31 형식 날짜): ").strip()
        if not v:
            return dt.date.today() + dt.timedelta(days=30)
        if v.isdigit():
            return dt.date.today() + dt.timedelta(days=int(v))
        try:
            return dt.date.fromisoformat(v)
        except ValueError:
            print("  날짜 형식이 맞지 않습니다. 다시 입력해 주세요.")


def issue_loop(secret):
    pub_hex = ed25519_min.public_key(secret).hex()
    print("라이선스 키 발급 (기기 코드에서 그냥 Enter를 누르면 종료)\n")
    while True:
        code = licensing.normalize_code(input("기기 코드 (예: K7F2-9QXA): "))
        if code in ("", "-"):
            break
        if not CODE_RE.match(code):
            print("  기기 코드 형식이 아닙니다. 사용자가 보낸 8자리 코드를 확인해 주세요.\n")
            continue
        name = input("이름: ").strip()
        email = input("이메일 (기록용, 생략 가능): ").strip()
        expires = ask_expiry()

        key = licensing.make_key(secret, code, expires, name)
        info = licensing.parse_key(key, pub_hex)   # 만든 키를 바로 검증
        assert info["code"] == code and info["expires"] == expires

        mail = (f"{name}님, 안녕하세요.\n\n"
                f"노래 분할기 라이선스 키를 보내 드립니다.\n"
                f"사용 기한: {expires.isoformat()}까지\n\n"
                f"프로그램을 열고 '라이선스 키' 칸에 아래 키를 그대로 붙여 넣은 뒤 등록을 눌러 주세요.\n\n"
                f"{key}\n")
        print("\n" + "-" * 60)
        print(mail)
        print("-" * 60)
        if copy_to_clipboard(mail):
            print("위 메일 내용을 클립보드에 복사했습니다. 메일에 붙여 넣어 보내세요.\n")

        new = not os.path.isfile(LOG)
        with open(LOG, "a", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["발급일", "이름", "이메일", "기기코드", "만료일", "키"])
            w.writerow([dt.date.today().isoformat(), name, email, code, expires.isoformat(), key])


def main():
    if not os.path.isfile(PRIV):
        setup()
    issue_loop(load_secret())
    print(f"발급 기록: {LOG}")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\n종료합니다.")
