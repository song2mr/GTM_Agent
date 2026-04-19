"""간단한 로컬 정적 서버 — UI가 logs/ 폴더를 fetch()로 읽기 위한 최소 서버.

`file://` 프로토콜에선 CORS/fetch가 막혀서 UI가 logs/*.jsonl을 못 읽는다.
이 스크립트 하나면 해결. 별도 패키지 설치 불필요 (표준 라이브러리).

실행:
    cd gtm_ai
    python serve_ui.py

열기:
    http://localhost:8765/ui/?run=20260418_092214

주의:
- 반드시 gtm_ai/ 루트에서 실행할 것 (logs/, ui/가 동일 레벨이어야 함).
- 개발용. 프로덕션에서 쓰지 말 것.
"""

from __future__ import annotations

import http.server
import os
import socketserver
import sys
from pathlib import Path

PORT = 8765
ROOT = Path(__file__).resolve().parent


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # 개발용: 캐시 전면 차단 (events.jsonl 폴링에 필수)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def log_message(self, format, *args):
        # 200 OK 로그는 생략, 에러만 출력
        if args and str(args[1]).startswith(("4", "5")):
            super().log_message(format, *args)


def main() -> int:
    os.chdir(ROOT)
    if not (ROOT / "ui" / "index.html").exists():
        print(f"[Error] ui/index.html not found under {ROOT}")
        print("먼저 UI 파일들을 gtm_ai/ui/ 에 복사하세요 (INTEGRATION_GUIDE.md 참고).")
        return 1
    if not (ROOT / "logs").exists():
        (ROOT / "logs").mkdir()

    print(f"  Serving {ROOT}")
    print(f"  → http://localhost:{PORT}/ui/")
    print(f"  → http://localhost:{PORT}/ui/?run=<run_id>")
    print(f"  Ctrl+C to stop.\n")

    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[serve_ui] stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
