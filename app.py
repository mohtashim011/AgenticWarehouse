"""
Agentic Warehouse -- server
===========================
One command starts everything:

    python app.py

That call initialises the database, builds the React front end if it is missing
or out of date, and serves the API and the built app from the same origin. There
is nothing to install at runtime: the server is Python standard library only.

Options
-------
    python app.py                 http://localhost:8000
    python app.py --https         https://<lan-ip>:8443, for phone cameras
    python app.py --port 8080     a different port
    python app.py --no-build      skip the front-end build entirely
    python app.py --rebuild       force a front-end rebuild

Front-end build
---------------
Node is needed to *build* the React app, never to run it. Once ``static/dist``
exists the server is self-contained, which is what keeps the zero-dependency
promise intact: a marker is only Node's problem at build time.

If Node is absent and no build exists, the server still starts and serves the
original single-page dashboard at ``/legacy`` rather than failing outright.
"""

import argparse
import json
import os
import posixpath
import shutil
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import db
from api import router
from core import dbcore
from core.router import Request, Response
from store import users, settings, cameras

BASE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(BASE, "static")
DIST = os.path.join(STATIC, "dist")
TEMPLATES = os.path.join(BASE, "templates")
WEB = os.path.join(BASE, "web")

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".map": "application/json; charset=utf-8",
}

# Files the app itself edits during development. A stale cached copy of these
# looks exactly like a bug, so the browser is told to revalidate them; hashed
# build assets and the big vendored libraries never change, so those cache hard.
NO_CACHE = {"index.html", "app.js", "styles.css"}

# How this server is actually reachable, filled in by main(). The connect page
# needs the LAN address and whether TLS is on, and neither can be recovered from
# the request: a phone asking for it has not connected yet, and a browser on
# localhost cannot see which interface the server bound to.
RUNTIME = {"lan_ip": "127.0.0.1", "port": 8000, "scheme": "http"}


class Handler(BaseHTTPRequestHandler):
    server_version = "AgenticWarehouse/2.0"
    protocol_version = "HTTP/1.1"

    # -- plumbing --------------------------------------------------------
    def log_message(self, fmt, *args):
        pass                                     # keep the console readable

    #: The largest request body that will be read into memory. Generous for a
    #: grayscale barcode band (a 1920x160 band is 307 KB) and small enough that
    #: a declared Content-Length cannot be used to exhaust the server. This was
    #: unbounded while every route took small JSON; it stopped being safe the
    #: moment one of them started accepting an image.
    MAX_BODY_BYTES = 4 * 1024 * 1024

    def _body(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return b""
        if length > self.MAX_BODY_BYTES:
            # Read and discard so the connection stays in sync, then let the
            # route see an empty body and refuse it with its own message.
            remaining = length
            while remaining > 0:
                chunk = self.rfile.read(min(65536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
            return b""
        return self.rfile.read(length)

    def _send(self, body, status=200, content_type="text/plain; charset=utf-8",
              headers=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # The API is same-origin only; there is no reason for another site to be
        # able to read it, and no reason to let this page be framed.
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_response_obj(self, response):
        body = response.body
        content_type = response.content_type or "application/octet-stream"
        if not isinstance(body, (bytes, str)):
            body = json.dumps(body)
            content_type = "application/json; charset=utf-8"
        self._send(body, response.status, content_type, response.headers)

    def _make_request(self):
        parsed = urlparse(self.path)
        request = Request(
            method=self.command,
            path=parsed.path,
            query=parse_qs(parsed.query),
            headers=self.headers,
            body=self._body(),
            client_addr=self.client_address,
        )
        # ssl wraps the socket in --https mode; that is what makes the session
        # cookie Secure.
        request._secure = hasattr(self.connection, "context")
        return request

    # -- verbs -----------------------------------------------------------
    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def do_PUT(self):
        self._handle()

    def do_DELETE(self):
        self._handle()

    def do_HEAD(self):
        self._handle()

    def _handle(self):
        request = self._make_request()
        response = router.dispatch(request)
        if response is not None:
            return self._send_response_obj(response)
        # Not an API route: serve a file, or the single-page app.
        return self._serve_static(request.path)

    # -- static files ----------------------------------------------------
    def _serve_static(self, path):
        if path.startswith("/api/"):
            return self._send(json.dumps({"ok": False, "error": "Unknown endpoint."}),
                              404, "application/json; charset=utf-8")

        # The original dashboard, kept as a fallback demonstration.
        if path in ("/legacy", "/legacy/"):
            return self._send_file(os.path.join(TEMPLATES, "index.html"))

        # Deliberately public and deliberately outside /api: this is the page
        # someone opens when the phone will not connect, so it must not need a
        # session, a working API, or anything fetched over the network.
        if path in ("/connect", "/connect/"):
            return self._send(_render_connect(), 200, CONTENT_TYPES[".html"])

        if path.startswith("/static/"):
            return self._send_file(self._safe_join(STATIC, path[len("/static/"):]))

        if path.startswith("/assets/"):
            return self._send_file(self._safe_join(DIST, path.lstrip("/")))

        # Anything else is a route inside the React app. Serving index.html for
        # unknown paths is what lets the browser's back button and a pasted deep
        # link both work in a single-page app.
        index = os.path.join(DIST, "index.html")
        if os.path.isfile(index):
            direct = self._safe_join(DIST, path.lstrip("/"))
            if direct and os.path.isfile(direct):
                return self._send_file(direct)
            return self._send_file(index)

        return self._send_file(os.path.join(TEMPLATES, "index.html"))

    @staticmethod
    def _safe_join(root, relative):
        """Join a request path to a directory without escaping it."""
        safe = posixpath.normpath("/" + relative).lstrip("/")
        full = os.path.abspath(os.path.join(root, safe))
        if os.path.commonpath([full, os.path.abspath(root)]) != os.path.abspath(root):
            return None
        return full

    def _send_file(self, path):
        if not path or not os.path.isfile(path):
            return self._send("Not found", 404)
        ext = os.path.splitext(path)[1].lower()
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError:
            return self._send("Not found", 404)
        name = os.path.basename(path).lower()
        if name in NO_CACHE:
            cache = {"Cache-Control": "no-cache, no-store, must-revalidate",
                     "Pragma": "no-cache", "Expires": "0"}
        else:
            cache = {"Cache-Control": "public, max-age=604800"}
        self._send(body, 200, CONTENT_TYPES.get(ext, "application/octet-stream"), cache)


# ---------------------------------------------------------------------------
# Front-end build
# ---------------------------------------------------------------------------
def _npm():
    """The npm executable, or None. On Windows it is npm.cmd, not npm."""
    for candidate in ("npm.cmd", "npm") if os.name == "nt" else ("npm",):
        found = shutil.which(candidate)
        if found:
            return found
    return None


def _newest_mtime(directory, skip=("node_modules", "dist", ".vite")):
    newest = 0.0
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in skip]
        for f in files:
            try:
                newest = max(newest, os.path.getmtime(os.path.join(root, f)))
            except OSError:
                pass
    return newest


def build_frontend(force=False, quiet=False):
    """Build the React app if it is missing or out of date.

    Returns ``(built, message)``. A failure is never fatal: the server still
    starts and falls back to the legacy dashboard, because a broken build should
    not take the warehouse offline.
    """
    src = os.path.join(WEB, "src")
    if not os.path.isdir(src):
        return False, "No front-end source in web/; serving the legacy dashboard."

    index = os.path.join(DIST, "index.html")
    if not force and os.path.isfile(index):
        if os.path.getmtime(index) >= _newest_mtime(WEB):
            return True, "Front end is up to date."

    npm = _npm()
    if npm is None:
        if os.path.isfile(index):
            return True, "Node is not installed; serving the existing build."
        return False, ("Node is not installed, so the React app cannot be built. "
                       "Serving the legacy dashboard at / instead.")

    if not quiet:
        print("  Building the front end (this happens only when it changes)...")

    if not os.path.isdir(os.path.join(WEB, "node_modules")):
        if not quiet:
            print("    installing packages...")
        result = subprocess.run([npm, "install", "--no-audit", "--no-fund"],
                                cwd=WEB, capture_output=True, text=True)
        if result.returncode != 0:
            return False, "npm install failed:\n%s" % (result.stderr or "")[-1500:]

    if not quiet:
        print("    compiling...")
    result = subprocess.run([npm, "run", "build"], cwd=WEB,
                            capture_output=True, text=True)
    if result.returncode != 0:
        return False, "The front-end build failed:\n%s" % (
            (result.stdout or "") + (result.stderr or ""))[-2000:]
    return True, "Front end built."


# ---------------------------------------------------------------------------
# HTTPS, for phone cameras
# ---------------------------------------------------------------------------
def _render_connect():
    """The phone-pairing page, with this server's real address filled in.

    The QR is rendered here, into the HTML, by the project's own encoder. A page
    that told someone to check their network while itself failing to load an
    image over that network would be a poor joke, so nothing on it is fetched.
    """
    url = "%s://%s:%d" % (RUNTIME["scheme"], RUNTIME["lan_ip"], RUNTIME["port"])
    secure = RUNTIME["scheme"] == "https"

    try:
        from core import qrcode
        qr = qrcode.to_svg(url, level="M", module=4)
    except Exception:                        # noqa: BLE001 - never fail the page
        qr = ('<p style="padding:24px;color:#111;text-align:center">'
              'Type the address below.</p>')

    if secure:
        banner = (
            '<div class="banner ok"><span class="dot"></span><div>'
            '<strong>Ready for phone cameras.</strong>'
            'This server is running over HTTPS, which is what browsers require '
            'before they will grant camera access on a network address.'
            '</div></div>')
        cert_step = ("The phone will warn once that the certificate is not trusted. "
                     "Choose <em>Advanced</em> and continue — it is self-signed by "
                     "this machine, which is the machine you are reading this on.")
    else:
        banner = (
            '<div class="banner warn"><span class="dot"></span><div>'
            '<strong>The phone will load this, but its camera will not start.</strong>'
            'Browsers only allow camera access on a secure page, and on a network '
            'address that means HTTPS. Stop the server and start it again with '
            '<code>python app.py --https</code>, then reopen this page. Typing codes '
            'in by hand works either way.'
            '</div></div>')
        cert_step = ("Sign in. Note that the camera will refuse to start until the "
                     "server is restarted with <code>--https</code>.")

    try:
        with open(os.path.join(TEMPLATES, "connect.html"), encoding="utf-8") as f:
            page = f.read()
    except OSError:
        return "<h1>Connect a phone</h1><p>Open %s on the phone.</p>" % url

    # The first three octets, which is what "the same network" means on the
    # 255.255.255.0 mask every home and small-office router hands out. Stated as
    # a prefix rather than a rule, because "compare the first three numbers" is
    # something anybody can do standing at the bench.
    parts = RUNTIME["lan_ip"].split(".")
    prefix = ".".join(parts[:3]) + "." if len(parts) == 4 else RUNTIME["lan_ip"]

    for token, value in (("{{URL}}", url), ("{{QR_SVG}}", qr),
                         ("{{BANNER}}", banner), ("{{CERT_STEP}}", cert_step),
                         ("{{PREFIX}}", prefix),
                         ("{{LAN_IP}}", RUNTIME["lan_ip"])):
        page = page.replace(token, value)
    return page


def _lan_ip():
    """This machine's address on the local network."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # No packet is actually sent; this just asks the OS which interface
        # would be used to reach the outside world.
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def _find_openssl():
    """Locate an openssl binary.

    On Windows it is rarely on PATH, but a copy ships inside Git for Windows,
    which is installed on most development machines. Looking there first saves
    asking anyone to install something they already have.
    """
    found = shutil.which("openssl")
    if found:
        return found
    candidates = [
        r"C:\Program Files\Git\usr\bin\openssl.exe",
        r"C:\Program Files (x86)\Git\usr\bin\openssl.exe",
        r"C:\Program Files\OpenSSL-Win64\bin\openssl.exe",
        "/usr/bin/openssl",
        "/usr/local/bin/openssl",
        "/opt/homebrew/bin/openssl",
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _ensure_certificate():
    """Create a self-signed certificate once, into data/.

    Browsers refuse camera access over plain http:// from anything but
    localhost, so a phone cannot scan without this. The certificate is
    self-signed, so the phone warns once and then remembers.
    """
    cert = os.path.join(BASE, "data", "cert.pem")
    key = os.path.join(BASE, "data", "key.pem")
    # The address this certificate was issued for. A router hands out a new
    # address after a restart, and a certificate naming the old one gives the
    # phone a *name mismatch* rather than the ordinary self-signed warning --
    # which several Android versions refuse to let you click past at all. So the
    # address is recorded beside the certificate and checked, rather than
    # assuming a certificate that exists is a certificate that still fits.
    stamp = os.path.join(BASE, "data", "cert.host")
    ip = _lan_ip()
    if os.path.isfile(cert) and os.path.isfile(key):
        try:
            with open(stamp, encoding="utf-8") as f:
                issued_for = f.read().strip()
        except OSError:
            issued_for = ""
        if issued_for == ip:
            return cert, key
        print("  Certificate : reissuing, this machine is now %s (was %s)"
              % (ip, issued_for or "an unrecorded address"))
        for path in (cert, key):
            try:
                os.remove(path)
            except OSError:
                pass

    openssl = _find_openssl()
    if openssl is None:
        return None, None
    os.makedirs(os.path.dirname(cert), exist_ok=True)
    result = subprocess.run([
        openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes",
        "-keyout", key, "-out", cert, "-days", "825",
        "-subj", "/CN=%s" % ip,
        "-addext", "subjectAltName=IP:%s,IP:127.0.0.1,DNS:localhost" % ip,
    ], capture_output=True, text=True)
    if result.returncode != 0:
        return None, None
    # Record the address it was issued for, so the next start can tell whether
    # it still fits rather than assuming that a certificate which exists is one
    # that matches. If this write fails the only cost is reissuing next time.
    try:
        with open(stamp, "w", encoding="utf-8") as f:
            f.write(ip)
    except OSError:
        pass
    return cert, key


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def initialise():
    """Bring the database and every subsystem up. Safe to call repeatedly."""
    db.init_db()
    settings.init_settings()
    cameras.init_cameras()
    seeded = users.init_auth()
    # Importing the package registers every agent.
    import agents                                # noqa: F401
    return seeded


def _print_connect_qr(url):
    """Print a QR of the server address, so a phone can open it by scanning.

    Typing an IP address and port on a phone keyboard is the kind of small
    friction that stops a feature being used at all.
    """
    try:
        from core import qrcode
    except Exception:                        # noqa: BLE001 - never block startup
        return

    # Windows consoles frequently cannot encode block characters, and an
    # unencodable one raises rather than degrading. Test before committing to it.
    encoding = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        "█▀▄".encode(encoding)
        ascii_only = False
    except (UnicodeEncodeError, LookupError):
        ascii_only = True

    try:
        art = qrcode.to_terminal(url, level="M", ascii_only=ascii_only)
    except Exception:                        # noqa: BLE001
        return

    print()
    print("  Scan this with a phone camera to open the scanner:")
    print()
    for line in art.splitlines():
        print("   " + line)


def _train_in_background():
    """Train the models without holding up the first request.

    Training takes a couple of seconds. Doing it on the first scan would make
    that scan feel broken, so it happens while the server is starting.
    """
    def worker():
        try:
            from ml import registry as ml_registry
            ml_registry.train_all()
        except Exception as e:                   # noqa: BLE001
            print("  (model training deferred: %s)" % e.__class__.__name__)
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return thread


def main(argv=None):
    parser = argparse.ArgumentParser(description="Agentic Warehouse server")
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("PORT", "8000")))
    parser.add_argument("--https", action="store_true",
                        help="serve over HTTPS so phone cameras work")
    parser.add_argument("--no-build", action="store_true",
                        help="do not build the front end")
    parser.add_argument("--rebuild", action="store_true",
                        help="force a front-end rebuild")
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args(argv)

    print("=" * 68)
    print("  Agentic Warehouse")
    print("=" * 68)

    seeded = initialise()
    print("  Database    : %s" % dbcore.db_path())

    if args.no_build:
        built, message = os.path.isfile(os.path.join(DIST, "index.html")), "Build skipped."
    else:
        built, message = build_frontend(force=args.rebuild)
    print("  Front end   : %s" % message.splitlines()[0])
    if not built and message.count("\n"):
        print(message)

    _train_in_background()

    port = args.port
    if args.https and port == 8000:
        port = 8443

    httpd = ThreadingHTTPServer((args.host, port), Handler)
    scheme = "http"

    if args.https:
        cert, key = _ensure_certificate()
        if cert:
            import ssl
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cert, key)
            httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
            scheme = "https"
            print("  Certificate : %s (self-signed)" % cert)
        else:
            print("  Certificate : could not be created (openssl not found);"
                  " falling back to http")

    ip = _lan_ip()
    RUNTIME.update({"lan_ip": ip, "port": port, "scheme": scheme})
    # So a "network camera" pointed at this server is refused with an
    # explanation rather than saved as a camera that can never work.
    cameras.SERVER_ORIGINS.update({ip, "localhost", "127.0.0.1", "::1"})
    lan_url = "%s://%s:%d" % (scheme, ip, port)
    print("-" * 68)
    print("  Dashboard   : %s://localhost:%d" % (scheme, port))
    if scheme == "https":
        print("  Phone       : %s   (accept the certificate warning once)" % lan_url)
    else:
        print("  On this LAN : %s" % lan_url)
        print("                phone cameras need --https (browsers require it)")
    print("  Legacy UI   : %s://localhost:%d/legacy" % (scheme, port))
    print("  Connect phone: %s://localhost:%d/connect" % (scheme, port))

    # A QR of the LAN address, so a phone can open the scanner without anyone
    # typing an IP address on a touchscreen.
    if scheme == "https":
        _print_connect_qr(lan_url)
    if seeded:
        print("-" * 68)
        print("  FIRST RUN. Sign in with:")
        print("      username: %s" % seeded["username"])
        print("      password: %s" % seeded["password"])
        print("  You will be asked to change it immediately.")
    print("=" * 68)
    print("  Ctrl+C to stop.")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping...")
        httpd.shutdown()


if __name__ == "__main__":
    main()
