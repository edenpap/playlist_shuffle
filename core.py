# -*- coding: utf-8 -*-
"""
노래 분할기 핵심 로직 (GUI 앱과 명령줄 playlist.py 가 함께 사용)

- CSV(start,title,first) 타임라인대로 긴 오디오를 곡별 mp3로 분할
- first 열 1, 2, 3 ... 곡은 그 순서대로 맨 앞에 고정, 나머지는 섞음
- 섞을 때 같은 가수는 연속으로 나오지 않고 최대한 멀리 떨어지게 배치
- 섞인 순서대로 01_제목.mp3 ... 와 tracklist.txt 생성
"""
import csv
import os
import random
import re
import shutil
import subprocess
import sys

OUTPUT_EXT = "mp3"
AUDIO_EXTS = (".m4a", ".mp3", ".wav", ".flac", ".aac", ".ogg", ".opus", ".webm", ".mp4", ".mkv")


class SplitError(Exception):
    """사용자에게 그대로 보여줄 수 있는 오류"""


class Cancelled(Exception):
    pass


# ---------------------------------------------------------
# ffmpeg 찾기 / 실행
# ---------------------------------------------------------

_POPEN_FLAGS = {}
if sys.platform == "win32":
    # 창 없는 앱에서 ffmpeg 를 부를 때 검은 콘솔 창이 깜빡이지 않게
    _POPEN_FLAGS["creationflags"] = 0x08000000  # CREATE_NO_WINDOW


def find_ffmpeg() -> str:
    """프로그램에 들어 있는 ffmpeg 를 우선 사용하고, 없으면 시스템 ffmpeg 를 사용"""
    exe = None
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        exe = None
    if not exe or not os.path.isfile(exe):
        exe = shutil.which("ffmpeg")
    if not exe:
        raise SplitError("ffmpeg 를 찾을 수 없습니다. 프로그램을 다시 내려받아 주세요.")
    if os.name != "nt" and not os.access(exe, os.X_OK):
        try:
            os.chmod(exe, 0o755)
        except OSError:
            pass
    return exe


def _run(cmd, cancel=None):
    """ffmpeg 실행. 취소되면 프로세스를 종료하고 Cancelled 를 던짐"""
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **_POPEN_FLAGS)
    while True:
        try:
            _, err = proc.communicate(timeout=0.3)
            return proc.returncode, err.decode("utf-8", errors="ignore")
        except subprocess.TimeoutExpired:
            if cancel is not None and cancel.is_set():
                proc.kill()
                proc.communicate()
                raise Cancelled()


def check_mp3_encoder(ffmpeg: str):
    r = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True, **_POPEN_FLAGS)
    if b"libmp3lame" not in r.stdout:
        raise SplitError("이 ffmpeg 에는 mp3 인코더(libmp3lame)가 없습니다.")


def get_duration(ffmpeg: str, path: str):
    """파일 길이(초). 알 수 없으면 None"""
    r = subprocess.run([ffmpeg, "-hide_banner", "-i", path], capture_output=True, **_POPEN_FLAGS)
    m = re.search(rb"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr)
    if not m:
        return None
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


# ---------------------------------------------------------
# 시간 / 이름 유틸
# ---------------------------------------------------------

def parse_time_to_seconds(t: str) -> float:
    parts = t.strip().split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        raise SplitError(f"시간 형식을 인식할 수 없습니다: {t}")
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    if len(nums) == 3:
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    raise SplitError(f"시간 형식을 인식할 수 없습니다: {t}")


def format_hms(seconds: float) -> str:
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]', "", name).strip().rstrip(".")
    return name or "untitled"


def parse_artist_song(title: str):
    """
    title 에서 (가수, 곡명) 추출.
      '가수_곡명', '01_가수_곡명', '가수 - 곡명', '01. 가수 - 곡명' 지원.
    구분자를 못 찾으면 (None, title).
    """
    t = title.strip()
    # 맨 앞 트랙 번호 제거 ("01_", "01.", "01) ", "01 - ")
    # 구분자가 있을 때만 제거해서 '10cm', '2am' 같은 가수명이 잘리지 않게 함
    t = re.sub(r"^\d+(?:\s*[._)]\s*|\s+-\s+|\s+)", "", t, count=1)
    if "_" in t:
        artist, song = t.split("_", 1)
        if artist.strip() and song.strip():
            return artist.strip(), song.strip()
    m = re.search(r"\s[-\u2013\u2014]\s", t)
    if m:
        artist, song = t[: m.start()].strip(), t[m.end():].strip()
        if artist and song:
            return artist, song
    return None, t


def artists_of(title: str):
    """가수 집합. 듀엣 'a&b', 'a, b' 는 a, b 각각으로 취급"""
    artist, _ = parse_artist_song(title)
    if not artist:
        return frozenset()
    parts = re.split(r"\s*(?:&|,|×)\s*", artist.lower())
    return frozenset(p.strip() for p in parts if p.strip())


# ---------------------------------------------------------
# CSV 읽기
# ---------------------------------------------------------

def load_tracks(csv_path: str):
    """
    반환: (tracks, fixed_titles, warnings)
      tracks: [{"start": 초, "start_text": 원문, "title": 제목}, ...]
      fixed_titles: first 번호 순서대로 정렬된 title 리스트
    """
    if not os.path.isfile(csv_path):
        raise SplitError(f"CSV 파일을 찾을 수 없습니다: {csv_path}")

    warnings = []
    tracks, flagged = [], []
    raw = open(csv_path, "rb").read()
    for enc in ("utf-8-sig", "cp949"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise SplitError("CSV 인코딩을 읽을 수 없습니다. UTF-8 로 저장해 주세요.")

    reader = csv.DictReader(text.splitlines())
    fields = [f.strip().lower() for f in (reader.fieldnames or [])]
    if "start" not in fields or "title" not in fields:
        raise SplitError("CSV 첫 줄(헤더)이 'start,title,first' 형식이어야 합니다.")
    reader.fieldnames = fields

    for row_num, row in enumerate(reader, start=2):
        start = (row.get("start") or "").strip()
        title = (row.get("title") or "").strip()
        if not start and not title:
            continue
        if not start or not title:
            warnings.append(f"{row_num}번째 줄은 시간이나 제목이 비어 있어 건너뜁니다.")
            continue
        sec = parse_time_to_seconds(start)
        tracks.append({"start": sec, "start_text": start, "title": title})
        mark = (row.get("first") or "").strip().lower()
        if not mark:
            continue
        if mark in ("true", "y", "yes", "o"):
            mark = "1"
        try:
            flagged.append((int(float(mark)), title))
        except ValueError:
            raise SplitError(f"{row_num}번째 줄의 first 값 '{mark}' 을 이해할 수 없습니다. 1, 2, 3 ... 숫자로 적어 주세요.")

    if not tracks:
        raise SplitError("CSV 에서 곡을 하나도 읽지 못했습니다.")

    for a, b in zip(tracks, tracks[1:]):
        if b["start"] <= a["start"]:
            raise SplitError(f"시간 순서가 맞지 않습니다: {a['start_text']} {a['title']} → {b['start_text']} {b['title']}")

    flagged.sort(key=lambda x: x[0])
    nums = [n for n, _ in flagged]
    if nums != list(range(1, len(nums) + 1)):
        detail = ", ".join(f"{n}:{t}" for n, t in flagged)
        raise SplitError(f"first 열 번호는 1부터 빠짐없이, 겹치지 않게 적어야 합니다. (현재 {detail})")

    # 파일 이름 (같은 제목이 두 번 있으면 뒤에 (2) 를 붙여 덮어쓰기 방지)
    used = {}
    for t in tracks:
        base = sanitize_filename(t["title"])
        k = used.get(base.lower(), 0) + 1
        used[base.lower()] = k
        t["fname"] = base if k == 1 else f"{base} ({k})"
        if k > 1:
            warnings.append(f"같은 제목이 여러 번 있습니다: {t['title']}")

    return tracks, [t for _, t in flagged], warnings


# ---------------------------------------------------------
# 섞기 (고정 곡 + 같은 가수 띄우기)
# ---------------------------------------------------------

def arrange_spread(fixed, pool, seed=None, trials=2000):
    """fixed 는 순서대로 맨 앞, pool 은 같은 가수가 최대한 멀리 떨어지게 섞음"""
    items = list(fixed) + list(pool)
    n = len(items)
    arts = [artists_of(it["title"]) for it in items]
    key_of = {id(it): a for it, a in zip(items, arts)}
    counts = {}
    for a_set in arts:
        for a in a_set:
            counts[a] = counts.get(a, 0) + 1
    ideal = {a: n / c for a, c in counts.items()}

    def build(rng):
        seq = list(fixed)
        last = {}
        for i, it in enumerate(seq):
            for a in key_of[id(it)]:
                last[a] = i
        remaining = {}
        for it in pool:
            for a in key_of[id(it)]:
                remaining[a] = remaining.get(a, 0) + 1
        rest = list(pool)
        rng.shuffle(rest)
        while rest:
            pos = len(seq)

            def key(it):
                a_set = key_of[id(it)]
                if not a_set:
                    return (1.0, 0, rng.random())
                spread = min(min(pos - last[a], ideal[a]) / ideal[a] if a in last else 1.0 for a in a_set)
                return (spread, max(remaining[a] for a in a_set), rng.random())

            pick = max(rest, key=key)
            rest.remove(pick)
            seq.append(pick)
            for a in key_of[id(pick)]:
                last[a] = pos
                remaining[a] -= 1
        return seq

    def score(seq):
        positions = {}
        for i, it in enumerate(seq):
            for a in key_of[id(it)]:
                positions.setdefault(a, []).append(i)
        adjacent, min_gap, spread = 0, None, 0.0
        for a, ps in positions.items():
            for x, y in zip(ps, ps[1:]):
                g = y - x
                adjacent += g == 1
                min_gap = g if min_gap is None else min(min_gap, g)
                spread += min(g, ideal[a]) / ideal[a]
        return (-adjacent, min_gap if min_gap is not None else n, spread), min_gap, adjacent

    rng = random.Random(seed)
    best = None
    for _ in range(trials if pool else 1):
        seq = build(rng)
        sc, mg, adj = score(seq)
        if best is None or sc > best[0]:
            best = (sc, seq, mg, adj)
    return best[1], best[2], best[3]


# ---------------------------------------------------------
# 전체 실행
# ---------------------------------------------------------

def run(input_file, csv_path, out_dir, shuffle=True, seed=None,
        log=print, progress=None, cancel=None):
    """
    분할(+섞기) 실행. 결과 정보 dict 반환.
    log(str): 진행 메시지, progress(done, total): 진행률, cancel: threading.Event
    """
    def prog(done, total):
        if progress:
            progress(done, total)

    def check_cancel():
        if cancel is not None and cancel.is_set():
            raise Cancelled()

    if not os.path.isfile(input_file):
        raise SplitError(f"원본 오디오 파일을 찾을 수 없습니다: {input_file}")

    tracks, fixed_titles, warnings = load_tracks(csv_path)
    for w in warnings:
        log(f"[경고] {w}")

    ffmpeg = find_ffmpeg()
    check_mp3_encoder(ffmpeg)

    total = get_duration(ffmpeg, input_file)
    if total is not None:
        bad = [t for t in tracks if t["start"] >= total]
        if bad:
            raise SplitError(
                f"CSV 의 시간이 원본 길이({format_hms(total)})보다 깁니다: "
                f"{bad[0]['start_text']} {bad[0]['title']}. 원본 파일이나 CSV 가 맞는지 확인해 주세요.")

    n = len(tracks)
    steps = n * 2 if shuffle else n
    os.makedirs(out_dir, exist_ok=True)
    log(f"원본: {os.path.basename(input_file)}" + (f" ({format_hms(total)})" if total else ""))
    log(f"총 {n}곡 분할을 시작합니다.\n")

    failed = []
    for i, t in enumerate(tracks):
        check_cancel()
        start = t["start"]
        end = tracks[i + 1]["start"] if i + 1 < n else total
        out_path = os.path.join(out_dir, f"{t['fname']}.{OUTPUT_EXT}")
        cmd = [ffmpeg, "-hide_banner", "-y", "-ss", f"{start:.3f}", "-i", input_file]
        if end is not None:
            cmd += ["-t", f"{end - start:.3f}"]
        cmd += ["-vn", "-map_metadata", "-1", "-acodec", "libmp3lame", "-q:a", "2", out_path]
        code, err = _run(cmd, cancel)
        if code != 0:
            failed.append(t["title"])
            log(f"[{i + 1}/{n}] 실패: {t['title']}\n    {err.strip().splitlines()[-1] if err.strip() else ''}")
        else:
            log(f"[{i + 1}/{n}] {format_hms(start)}  {t['title']}")
        t["path"] = out_path if code == 0 else None
        prog(i + 1, steps)

    result = {"split_dir": out_dir, "failed": failed, "shuffled_dir": None, "tracklist": None}
    if not shuffle:
        log("\n분할 완료.")
        return result

    check_cancel()
    items = [t for t in tracks if t.get("path")]
    fixed = []
    for ft in fixed_titles:
        it = next((x for x in items if x["title"] == ft and x not in fixed), None)
        if it is None:
            log(f"[경고] 고정 곡을 찾지 못해 건너뜁니다: {ft}")
            continue
        fixed.append(it)
    pool = [x for x in items if x not in fixed]

    log("\n곡 순서를 섞는 중...")
    order, min_gap, adjacent = arrange_spread(fixed, pool, seed=seed)
    if fixed:
        log(f"앞 {len(fixed)}곡 고정")
    if min_gap is not None:
        log(f"같은 가수 연속: {adjacent}회, 같은 가수 사이 최소 간격: {min_gap}곡")
    log("")

    shuffle_dir = os.path.join(out_dir, "shuffled")
    if os.path.isdir(shuffle_dir):
        shutil.rmtree(shuffle_dir)
    os.makedirs(shuffle_dir)

    width = max(2, len(str(len(order))))
    lines, cursor = [], 0.0
    for i, t in enumerate(order, start=1):
        check_cancel()
        num = str(i).zfill(width)
        shutil.copyfile(t["path"], os.path.join(shuffle_dir, f"{num}_{t['fname']}.{OUTPUT_EXT}"))
        artist, song = parse_artist_song(t["title"])
        label = f"{song} - {artist}" if artist and song else t["title"]
        lines.append(f"{num}. {format_hms(cursor)} {label}")
        log(lines[-1])
        cursor += get_duration(ffmpeg, t["path"]) or 0.0
        prog(n + i, steps)

    txt = os.path.join(shuffle_dir, "tracklist.txt")
    with open(txt, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")

    log(f"\n완료! 총 재생 시간 {format_hms(cursor)}")
    result.update(shuffled_dir=shuffle_dir, tracklist=txt)
    return result
