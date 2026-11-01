"""Loopback-only static UI and ephemeral snapshot collection endpoint.

No credential/config/state files, request logging, cookies or browser persistence.
Run from the source checkout: python -m oci_admin.web_server
"""

import argparse
import importlib.util
import json
import os
import secrets
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .snapshot_worker import validate_request

ASSETS = Path(__file__).resolve().parents[1] / "web" / "dist"
MAX_BODY = 65536


def run_worker(body, timeout=600):
    # Never put credentials in argv, the environment, a file, or diagnostic output.
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    for name in ("OCI_PYTHON_SDK_DEBUG", "OCI_PYTHON_SDK_LOG_LEVEL"):
        env.pop(name, None)
    process = subprocess.Popen([sys.executable, "-m", "oci_admin.snapshot_worker"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        cwd=Path(__file__).resolve().parents[1], env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        output, _ = process.communicate(body, timeout=timeout)
        result = json.loads(output)
        if not isinstance(result, dict) or not ("snapshot" in result or "error" in result):
            raise ValueError("Invalid worker response")
        return result
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        return {"error": "Collection exceeded 10 minutes and its signing process was terminated. Choose fewer regions or services."}
    except (ValueError, OSError):
        return {"error": "Collection process failed. Credentials were not retained; check the local SDK installation."}
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port=8765, worker=run_worker):
        super().__init__(("127.0.0.1", port), Handler)
        self.origin = f"http://127.0.0.1:{self.server_port}"
        self.csrf = secrets.token_urlsafe(32)
        self.worker = worker
        self.busy = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    server_version = "OCIExplorer"

    def log_message(self, *args):
        pass  # No access log, request bodies, credentials, or exception text.

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'; object-src 'none'")
        super().end_headers()

    def valid_host(self):
        # Exact Host validation also prevents DNS-rebinding access to loopback.
        return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

    def respond(self, status, value):
        payload = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def do_GET(self):
        if not self.valid_host():
            return self.respond(403, {"error": "Use the exact loopback URL printed by the server."})
        if self.path == "/api/session":
            return self.respond(200, {"token": self.server.csrf, "sdk_available": importlib.util.find_spec("oci") is not None})
        allowed = {"/": ("index.html", "text/html"), "/index.html": ("index.html", "text/html"),
                   "/style.css": ("style.css", "text/css"), "/core.js": ("core.js", "text/javascript"),
                   "/demo.js": ("demo.js", "text/javascript"), "/app.js": ("app.js", "text/javascript")}
        asset = allowed.get(urlsplit(self.path).path)
        if not asset:
            return self.respond(404, {"error": "Not found"})
        body = (ASSETS / asset[0]).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", asset[1] + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if not self.valid_host() or self.headers.get("Origin") != self.server.origin or not secrets.compare_digest(self.headers.get("X-OCI-Session", "").encode("utf-8"), self.server.csrf.encode("ascii")):
            return self.respond(403, {"error": "Rejected: collection must originate from this local page."})
        if self.path != "/api/snapshot":
            return self.respond(404, {"error": "Not found"})
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json" or self.headers.get("Transfer-Encoding"):
            return self.respond(415, {"error": "Expected a JSON request"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= MAX_BODY:
                return self.respond(413, {"error": "Request is too large or empty"})
        except ValueError:
            return self.respond(400, {"error": "Invalid request length"})
        if not self.server.busy.acquire(blocking=False):
            return self.respond(409, {"error": "A snapshot is already being collected. Wait for it to finish."})
        body = None
        try:
            self.connection.settimeout(15)
            body = self.rfile.read(size)
            if len(body) != size:
                return self.respond(400, {"error": "Incomplete request"})
            parsed = json.loads(body)
            try:
                validate_request(parsed)
            finally:
                if isinstance(parsed, dict):
                    parsed.clear()
            self.connection.settimeout(650)
            result = self.server.worker(body)
            body = None
            self.respond(200 if "snapshot" in result else 502, result)
        except (ValueError, TypeError):
            self.respond(400, {"error": "Invalid collection fields. Check the OCIDs, fingerprint, PEM key, regions and services."})
        except Exception:
            self.respond(500, {"error": "Local collection failed. No credentials were saved."})
        finally:
            body = None
            self.server.busy.release()


def main():
    parser = argparse.ArgumentParser(description="Local-only OCI explorer with in-memory signing credentials")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    with LocalServer(args.port) as server:
        print(f"OCI Explorer: {server.origin}/", flush=True)
        print("Credentials are used in memory by a one-shot worker. Press Ctrl+C to stop.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
