#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
명령줄 버전: 이 파일과 원본 오디오, tracks.csv 를 같은 폴더에 두고
    python3 playlist.py
결과는 output/ (분할) 과 output/shuffled/ (섞인 순서 + tracklist.txt).

옵션: --input 파일  --csv 파일  --out 폴더  --no-shuffle  --seed N
"""
import argparse
import os
import sys

import core


def find_input_file():
    if os.path.isfile("input.m4a"):
        return "input.m4a"
    found = [f for f in os.listdir(".") if os.path.isfile(f) and f.lower().endswith(core.AUDIO_EXTS)]
    if not found:
        sys.exit("[오류] 이 폴더에서 원본 오디오 파일을 찾지 못했습니다.")
    found.sort(key=os.path.getsize, reverse=True)
    if len(found) > 1:
        print(f"[안내] 오디오 파일이 여러 개라 가장 큰 파일을 사용합니다: {found[0]}")
    return found[0]


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    ap = argparse.ArgumentParser(description="CSV 타임라인 기준 오디오 분할 + 섞기")
    ap.add_argument("--input")
    ap.add_argument("--csv", default="tracks.csv")
    ap.add_argument("--out", default="output")
    ap.add_argument("--no-shuffle", dest="shuffle", action="store_false")
    ap.add_argument("--seed", type=int)
    args = ap.parse_args()
    try:
        res = core.run(args.input or find_input_file(), args.csv, args.out,
                       shuffle=args.shuffle, seed=args.seed)
    except core.SplitError as e:
        sys.exit(f"[오류] {e}")
    except KeyboardInterrupt:
        sys.exit("\n중단했습니다.")
    if res["tracklist"]:
        print(f"결과: {res['shuffled_dir']}")


if __name__ == "__main__":
    main()
