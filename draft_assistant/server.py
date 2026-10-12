"""Local web server: serves the page and a small JSON API. Listens on 127.0.0.1 only."""
from __future__ import annotations

import argparse
import errno
import json
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .app import App
from .config import load_config
from .espn import EspnError

STATIC = Path(__file__).resolve().parent / "static"
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml"}


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # keep the terminal quiet
            pass

        def _json(self, payload, status=HTTPStatus.OK):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _static(self, name: str):
            path = (STATIC / name).resolve()
            if STATIC not in path.parents or not path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            body = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", CONTENT_TYPES.get(path.suffix, "application/octet-stream"))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urlparse(self.path)
            query = parse_qs(url.query)
            if url.path in ("/", "/index.html"):
                return self._static("index.html")
            if url.path.startswith("/static/"):
                return self._static(url.path[len("/static/"):])
            if url.path == "/api/state":
                since = query.get("v", [None])[0]
                if since is not None and since.isdigit() and int(since) == app.version:
                    return self._json({"unchanged": True, "version": app.version, "last_poll": app.last_poll,
                                       "poll_error": app.poll_error})
                return self._json(app.snapshot())
            if url.path == "/api/search":
                return self._json(app.search(query.get("q", [""])[0]))
            if url.path == "/api/player":
                pid = query.get("id", [""])[0]
                try:
                    return self._json(app.player_detail(int(pid)))
                except ValueError as exc:
                    return self._json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self):
            # Only accept requests from our own page, so other websites can't drive the app.
            origin = self.headers.get("Origin")
            if origin and urlparse(origin).hostname not in ("127.0.0.1", "localhost"):
                return self._json({"error": "Forbidden origin."}, HTTPStatus.FORBIDDEN)
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self._json({"error": "Expected JSON."}, HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
            length = int(self.headers.get("Content-Length") or 0)
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return self._json({"error": "Bad JSON."}, HTTPStatus.BAD_REQUEST)
            actions = {
                "/api/config": lambda: app.update_config(data),
                "/api/settings": lambda: app.update_settings(data),
                "/api/reload": lambda: app.load_espn(refresh=bool(data.get("refresh"))),
                "/api/demo": lambda: app.load_demo(points=bool(data.get("points")), slot=int(data.get("slot") or 4)),
                "/api/pick": lambda: app.record_pick(int(data["player_id"]), bool(data.get("mine"))),
                "/api/undo": app.undo,
                "/api/auto": app.autodraft,
                "/api/reset": app.reset_manual,
            }
            action = actions.get(urlparse(self.path).path)
            if not action:
                return self._json({"error": "Not found."}, HTTPStatus.NOT_FOUND)
            try:
                action()
            except (EspnError, ValueError, KeyError) as exc:
                with app.lock:
                    if self.path.startswith(("/api/config", "/api/reload")):
                        app.error = str(exc)
                        app.version += 1
                return self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return self._json(app.snapshot())

    return Handler


def serve(app: App, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), make_handler(app))
    server.daemon_threads = True
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="draft_assistant", description="ESPN fantasy basketball draft assistant")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true", help="Don't open the browser automatically")
    parser.add_argument("--demo", action="store_true", help="Start with a made-up practice league")
    args = parser.parse_args(argv)

    app = App(load_config())
    url = f"http://127.0.0.1:{args.port}/"
    try:
        server = serve(app, port=args.port)
    except OSError as exc:
        if exc.errno != errno.EADDRINUSE:
            raise
        print(f"The draft assistant is already running. Opening {url}")
        if not args.no_browser:
            webbrowser.open(url)
        return 0
    if args.demo:
        app.load_demo()
    else:
        print("Loading your league from ESPN...")
        app.try_load()
    stop = threading.Event()
    threading.Thread(target=app.run_poller, args=(stop,), daemon=True).start()
    print(f"Draft assistant running at {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
    return 0
