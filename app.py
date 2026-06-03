from __future__ import annotations

import argparse
import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from contract_radar.service import ContractRadarService


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8080"))

service = ContractRadarService()


class ContractRadarHandler(BaseHTTPRequestHandler):
    server_version = "ProjectBidBot/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_file(STATIC_DIR / "index.html")
            return
        if parsed.path == "/api/health":
            self._send_json(service.health())
            return
        if parsed.path.startswith("/static/"):
            self._send_file(STATIC_DIR / parsed.path.removeprefix("/static/"))
            return
        self._send_json({"error": "Not found"}, status=404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/scan-stream":
            self._send_scan_stream()
            return
        routes = {
            "/api/inbox": service.inbox,
            "/api/scan": service.scan,
            "/api/simulate": service.simulate,
            "/api/approve": service.approve,
            "/api/documents/acquire": service.acquire_document,
            "/api/documents/analyze": service.analyze_document,
            "/api/evidence/upload": service.upload_evidence,
            "/api/compliance/attach-evidence": service.attach_evidence_to_requirement,
            "/api/compliance/resolve": service.resolve_requirement,
        }
        handler = routes.get(parsed.path)
        if handler is None:
            self._send_json({"error": "Not found"}, status=404)
            return
        try:
            payload = self._read_json()
            self._send_json(handler(payload))
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=500)

    def log_message(self, format: str, *args: object) -> None:
        print("%s - %s" % (self.address_string(), format % args))

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8") or "{}")

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, indent=2, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_scan_stream(self) -> None:
        try:
            payload = self._read_json()
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=400)
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        stream_open = True

        def write_event(event: dict) -> None:
            nonlocal stream_open
            if not stream_open:
                raise ConnectionAbortedError("scan stream closed")
            body = json.dumps(event, default=str).encode("utf-8") + b"\n"
            try:
                self.wfile.write(body)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                stream_open = False
                raise

        try:
            result = service.scan(payload, progress_callback=write_event)
            write_event({"event": "done", "result": result})
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            return
        except Exception as exc:
            try:
                write_event({"event": "error", "error": str(exc)})
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                return

    def _send_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self._send_json({"error": "Not found"}, status=404)
            return
        body = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    _parse_args()
    server = ThreadingHTTPServer((HOST, PORT), ContractRadarHandler)
    print(f"Project Bid Bot running at http://{HOST}:{PORT}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Project Bid Bot.")
    finally:
        server.server_close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Project Bid Bot web app.")
    return parser.parse_args()


if __name__ == "__main__":
    main()
