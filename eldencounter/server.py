"""Local server: serves the overlay and pushes updates over Server-Sent
Events. Standard library only, to keep the PyInstaller binary small.
"""

from __future__ import annotations

import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

OVERLAY_DIR = Path(__file__).parent / "overlay"

_MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".woff2": "font/woff2",
    ".png": "image/png",
}


def make_handler(log):
    clients: set[queue.Queue] = set()
    clients_lock = threading.Lock()

    def broadcast(snapshot: dict) -> None:
        payload = json.dumps(snapshot, ensure_ascii=False)
        with clients_lock:
            for q in list(clients):
                q.put(payload)

    log.subscribe(broadcast)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass  # keep the streamer's console quiet

        def _send(self, body: bytes, content_type: str, status: int = 200):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0]

            if path == "/events":
                return self._stream()

            if path == "/state":
                body = json.dumps(log.snapshot(), ensure_ascii=False).encode()
                return self._send(body, "application/json; charset=utf-8")

            if path == "/history":
                body = json.dumps(log.history, ensure_ascii=False).encode()
                return self._send(body, "application/json; charset=utf-8")

            rel = "index.html" if path == "/" else path.lstrip("/")
            target = (OVERLAY_DIR / rel).resolve()
            if not str(target).startswith(str(OVERLAY_DIR.resolve())) or not target.is_file():
                return self._send(b"Not found.", "text/plain; charset=utf-8", 404)
            mime = _MIME.get(target.suffix, "application/octet-stream")
            return self._send(target.read_bytes(), mime)

        def _stream(self):
            q: queue.Queue = queue.Queue()
            with clients_lock:
                clients.add(q)
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "keep-alive")
                self.end_headers()

                first = json.dumps(log.snapshot(), ensure_ascii=False)
                self.wfile.write(f"data: {first}\n\n".encode())
                self.wfile.flush()

                while True:
                    try:
                        payload = q.get(timeout=15)
                        self.wfile.write(f"data: {payload}\n\n".encode())
                    except queue.Empty:
                        self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                with clients_lock:
                    clients.discard(q)

    return Handler


class QuietServer(ThreadingHTTPServer):
    """A browser closing an SSE stream is not an error worth printing."""

    def handle_error(self, request, client_address):
        import sys
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionAbortedError, ConnectionResetError,
                            BrokenPipeError, TimeoutError)):
            return
        super().handle_error(request, client_address)


def serve(log, host: str = "127.0.0.1", port: int = 4747) -> QuietServer:
    """Start the server in a daemon thread and return it."""
    httpd = QuietServer((host, port), make_handler(log))
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd
