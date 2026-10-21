"""Usage: .venv/Scripts/python.exe -B web/build_replay.py --video test02"""
import argparse
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))
from replay.export import export
from replay.store import selected_title

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="기존 검출 결과로 추적·BEV 재생 캐시 생성 (YOLO 실행 없음)")
    parser.add_argument("--video")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    try:
        result = export(args.video or selected_title(), overwrite=args.overwrite)
        print(f"Ready: {result['title']} ({result['frame_count']} frames). Start web/run.py")
    except Exception as exc:
        parser.exit(1, f"Replay preparation failed: {exc}\n")
