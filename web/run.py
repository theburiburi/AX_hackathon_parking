"""Start the local integrated web app; no Node or YOLO runtime required."""
import argparse
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="로그인·스케줄·사전 계산 영상 재생 서버")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    from waitress import serve
    from config.wsgi import application
    print(f"AX Parking: http://{args.host}:{args.port}/", flush=True)
    print("Login, schedules and cached video replay. Press Ctrl+C to stop.", flush=True)
    # WSGI streams Django's synchronous FileResponse iterator without reading
    # the full MP4 into RAM. Waitress also works on Windows.
    serve(application, host=args.host, port=args.port, threads=6)
