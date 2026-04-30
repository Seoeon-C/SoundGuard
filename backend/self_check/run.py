from __future__ import annotations

import argparse
import sys
from pathlib import Path


if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(project_root))

from backend.self_check import run_self_check


def main() -> int:
    parser = argparse.ArgumentParser(description="SoundGuard self check")
    parser.add_argument("--quick", action="store_true", help="BEATs 모델 로딩 생략")
    parser.add_argument("--no-audio-check", action="store_true", help="스피커-마이크 루프백 테스트 생략")
    args = parser.parse_args()

    report = run_self_check(load_model=not args.quick, audio_loopback=not args.no_audio_check)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
