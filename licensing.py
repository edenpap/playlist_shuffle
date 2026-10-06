# -*- coding: utf-8 -*-
"""
라이선스 키 확인

- 기기 코드: 이 컴퓨터 고유 ID로 만든 8자리 코드 (예: K7F2-9QXA)
- 라이선스 키: 발급자 비밀키로 서명한 "기기 코드 + 사용 기한 + 이름"
  → 다른 컴퓨터에서는 안 열리고, 기한이 지나면 막힘
"""
import base64
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import uuid

import ed25519_min

try:
    from license_pubkey import PUBLIC_KEY_HEX
except Exception:
    PUBLIC_KEY_HEX = ""

APP_ID = "PlaylistSplitter"
FORM_URL = ("https://docs.google.com/forms/d/e/1FAIpQLSeSXZyeGAnCYaLUVVgtWViKhI_broOUP3ePb5oapfdr1YBvrg"
            "/viewform?usp=pp_url&entry.1646415967={code}")
KEY_PREFIX = "PS1"
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"   # 헷갈리는 I, L, O, U 제외

_POPEN = {"creationflags": 0x08000000} if sys.platform == "win32" else {}


# ---------------- 기기 코드 ----------------

def _config_dir():
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    path = os.path.join(base, APP_ID)
    os.makedirs(path, exist_ok=True)
    return path


def _raw_machine_id():
    try:
        if sys.platform == "win32":
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography",
                                0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
                return winreg.QueryValueEx(k, "MachineGuid")[0]
        if sys.platform == "darwin":
            out = subprocess.run(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                                 capture_output=True, text=True).stdout
            m = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', out)
            if m:
                return m.group(1)
        else:
            for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
                if os.path.isfile(p):
                    v = open(p).read().strip()
                    if v:
                        return v
    except Exception:
        pass
    # 위 방법이 모두 안 되면 설정 폴더에 무작위 ID 를 만들어 보관
    f = os.path.join(_config_dir(), "device.id")
    if os.path.isfile(f):
        return open(f).read().strip()
    v = uuid.uuid4().hex
    with open(f, "w") as fh:
        fh.write(v)
    return v


def _encode32(data: bytes, length: int) -> str:
    n = int.from_bytes(data, "big")
    out = []
    for _ in range(length):
        out.append(_ALPHABET[n & 31])
        n >>= 5
    return "".join(out)


def device_code() -> str:
    h = hashlib.sha256(f"{APP_ID}|{_raw_machine_id()}".encode()).digest()
    c = _encode32(h, 8)
    return f"{c[:4]}-{c[4:]}"


def normalize_code(code: str) -> str:
    """사용자가 옮겨 적은 코드 정리 (소문자, 공백, O→0, I/L→1)"""
    c = re.sub(r"[\s\-]", "", code.upper()).replace("O", "0").replace("I", "1").replace("L", "1")
    return f"{c[:4]}-{c[4:]}" if len(c) == 8 else c


# ---------------- 키 만들기 / 읽기 ----------------

def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_key(secret: bytes, code: str, expires: dt.date, name: str) -> str:
    """발급자용: 서명된 라이선스 키 문자열"""
    name = re.sub(r"[|\r\n]", " ", name).strip()
    payload = f"1|{normalize_code(code)}|{expires.isoformat()}|{dt.date.today().isoformat()}|{name}"
    data = payload.encode("utf-8")
    sig = ed25519_min.sign(secret, data)
    return f"{KEY_PREFIX}.{_b64e(data)}.{_b64e(sig)}"


class LicenseError(Exception):
    pass


def parse_key(key: str, public_hex: str = None):
    """키 검증 후 {"code", "expires", "issued", "name"} 반환. 잘못되면 LicenseError"""
    public_hex = public_hex if public_hex is not None else PUBLIC_KEY_HEX
    if not public_hex:
        raise LicenseError("이 프로그램에는 라이선스 설정이 들어 있지 않습니다. 배포자에게 문의해 주세요.")
    key = re.sub(r"\s", "", key or "")
    parts = key.split(".")
    if len(parts) != 3 or parts[0] != KEY_PREFIX:
        raise LicenseError("라이선스 키 형식이 올바르지 않습니다. 받은 키 전체를 그대로 붙여 넣어 주세요.")
    try:
        data, sig = _b64d(parts[1]), _b64d(parts[2])
    except Exception:
        raise LicenseError("라이선스 키 형식이 올바르지 않습니다.")
    if not ed25519_min.verify(bytes.fromhex(public_hex), data, sig):
        raise LicenseError("유효하지 않은 라이선스 키입니다.")
    f = data.decode("utf-8").split("|", 4)
    if len(f) != 5 or f[0] != "1":
        raise LicenseError("지원하지 않는 라이선스 키입니다.")
    return {"code": f[1], "expires": dt.date.fromisoformat(f[2]),
            "issued": dt.date.fromisoformat(f[3]), "name": f[4]}


# ---------------- 저장 / 확인 ----------------

def _store_path():
    return os.path.join(_config_dir(), "license.json")


def _load_store():
    try:
        with open(_store_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_store(d):
    with open(_store_path(), "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)


def check(key: str = None, today: dt.date = None):
    """
    키(없으면 저장된 키)를 확인.
    반환: (ok, info 또는 None, 사용자에게 보여줄 메시지)
    """
    today = today or dt.date.today()
    store = _load_store()
    key = key if key is not None else store.get("key", "")
    if not key:
        return False, None, "라이선스 키를 등록해 주세요."
    try:
        info = parse_key(key)
    except LicenseError as e:
        return False, None, str(e)
    if info["code"] != device_code():
        return False, info, "다른 컴퓨터용 라이선스 키입니다. 이 컴퓨터의 기기 코드로 다시 신청해 주세요."
    last = store.get("last_seen")
    if last and today < dt.date.fromisoformat(last):
        return False, info, ("컴퓨터 날짜가 마지막 사용일보다 이전으로 되어 있습니다. "
                             "날짜와 시간 설정을 확인해 주세요.")
    if today > info["expires"]:
        return False, info, f"사용 기간이 {info['expires'].isoformat()}에 끝났습니다. 새 라이선스 키를 받아 등록해 주세요."
    return True, info, ""


def activate(key: str):
    """키를 확인하고 맞으면 저장. 반환: check() 와 같음"""
    ok, info, msg = check(key)
    if ok:
        store = _load_store()
        store["key"] = re.sub(r"\s", "", key)
        store["last_seen"] = max(store.get("last_seen", ""), dt.date.today().isoformat())
        _save_store(store)
    return ok, info, msg


def touch():
    """정상 실행할 때마다 마지막 사용일 기록 (날짜 되돌리기 방지)"""
    store = _load_store()
    today = dt.date.today().isoformat()
    if store.get("last_seen", "") < today:
        store["last_seen"] = today
        _save_store(store)


def form_url() -> str:
    return FORM_URL.format(code=device_code())
