"""로컬 정적 서버 + 에이전트 실행 API.

엔드포인트:
    GET  /*               정적 파일 (ui/, logs/)
    POST /api/run         에이전트 실행 시작 → {"run_id": "..."}
    POST /api/hitl        HITL 응답 → {"ok": true}

실행:
    cd gtm_ai
    python serve_ui.py

열기:
    http://localhost:8766/ui/
    http://localhost:8766/ui/?run=20260418_092214
"""

from __future__ import annotations

import asyncio
import http.server
import json
import os
import socketserver
import sys
import threading
from datetime import datetime
from pathlib import Path

PORT = 8766
ROOT = Path(__file__).resolve().parent


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        if self.path == "/api/run":
            try:
                config = json.loads(body)
            except json.JSONDecodeError:
                self._json(400, {"error": "invalid json"})
                return

            run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
            config["run_id"] = run_id
            config["hitl_mode"] = "file"

            def run_thread():
                sys.path.insert(0, str(ROOT))
                from dotenv import load_dotenv
                load_dotenv()
                # 기본은 창 표시(headed). 숨김은 .env에 GTM_AI_HEADLESS=1
                # (Windows에서 UI 스레드+Chromium 조합은 환경에 따라 간헐적 불안정 가능)
                os.environ.setdefault("GTM_AI_HEADLESS", "0")
                from agent.runner import run_agent
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(run_agent(config))
                except Exception as e:
                    print(f"[serve_ui] Agent error: {e}", flush=True)
                    try:
                        from utils import logger as _run_log

                        _run_log.error(
                            f"[serve_ui] agent thread run_id={config.get('run_id')!r}: {e}"
                        )
                    except RuntimeError:
                        pass
                finally:
                    loop.close()

            t = threading.Thread(target=run_thread, daemon=True, name=f"agent-{run_id}")
            t.start()
            self._json(200, {"run_id": run_id})

        elif self.path == "/api/hitl":
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                self._json(400, {"error": "invalid json"})
                return

            run_id = data.get("run_id", "")
            if not run_id:
                self._json(400, {"error": "run_id required"})
                return

            response_file = ROOT / "logs" / run_id / "hitl_response.json"
            try:
                response_file.write_text(
                    json.dumps({
                        "approved": bool(data.get("approved", True)),
                        "feedback": data.get("feedback", ""),
                    }),
                    encoding="utf-8",
                )
                self._json(200, {"ok": True})
            except Exception as e:
                self._json(500, {"error": str(e)})

        else:
            self._json(404, {"error": "not found"})

    def _json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        if args and str(args[1]).startswith(("4", "5")):
            super().log_message(format, *args)


def main() -> int:
    os.chdir(ROOT)
    if not (ROOT / "ui" / "index.html").exists():
        print(f"[Error] ui/index.html not found under {ROOT}")
        return 1
    if not (ROOT / "logs").exists():
        (ROOT / "logs").mkdir()

    print(f"  Serving {ROOT}")
    print(f"  → http://localhost:{PORT}/ui/")
    print(f"  → http://localhost:{PORT}/ui/?run=<run_id>")
    print(f"  Ctrl+C to stop.\n")

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[serve_ui] stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
