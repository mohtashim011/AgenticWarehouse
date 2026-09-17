"""
Router
======
A small path router for ``http.server``. The original app matched paths with a
ladder of ``if path == ...`` checks; at seventeen routes that was already hard
to read, and the API is about to triple.

Routes are registered with a decorator and may carry parameters:

    @router.get("/api/staff/<int:staff_id>")
    def get_staff(req, staff_id):
        ...

A handler returns either a JSON-serialisable object (sent as 200), or a
:class:`Response` when it needs to control the status, headers or body.

Standard library only.
"""

import json
import re


class Response:
    """An explicit HTTP response: status, body, content type and headers."""

    def __init__(self, body=None, status=200, content_type=None, headers=None):
        self.body = body
        self.status = status
        self.content_type = content_type
        self.headers = dict(headers or {})

    # -- convenience constructors ---------------------------------------
    @staticmethod
    def json(obj, status=200, headers=None):
        return Response(obj, status, "application/json; charset=utf-8", headers)

    @staticmethod
    def error(message, status=400, **extra):
        payload = {"ok": False, "error": message}
        payload.update(extra)
        return Response.json(payload, status)

    @staticmethod
    def text(body, status=200):
        return Response(body, status, "text/plain; charset=utf-8")

    @staticmethod
    def no_content():
        return Response(b"", 204)


class HttpError(Exception):
    """Raise from a handler to abort with a status and message."""

    def __init__(self, status, message, **extra):
        super().__init__(message)
        self.status = status
        self.message = message
        self.extra = extra


class Request:
    """Everything a handler needs about the incoming call."""

    def __init__(self, method, path, query, headers, body, client_addr):
        self.method = method
        self.path = path
        self.query = query          # dict[str, list[str]]
        self.headers = headers
        self.raw_body = body
        self.client_addr = client_addr
        self.user = None            # filled in by the auth middleware
        self.session = None
        self._json = None

    def json(self):
        """The request body parsed as JSON; ``{}`` when absent or malformed."""
        if self._json is None:
            if not self.raw_body:
                self._json = {}
            else:
                try:
                    parsed = json.loads(self.raw_body.decode("utf-8"))
                    self._json = parsed if isinstance(parsed, dict) else {"value": parsed}
                except Exception:
                    self._json = {}
        return self._json

    def arg(self, name, default=""):
        """A single query-string value."""
        return (self.query.get(name) or [default])[0]

    def int_arg(self, name, default=0):
        try:
            return int(self.arg(name, str(default)))
        except (TypeError, ValueError):
            return default

    def cookie(self, name):
        """One cookie value from the Cookie header, or None."""
        raw = self.headers.get("Cookie", "")
        for part in raw.split(";"):
            k, _, v = part.strip().partition("=")
            if k == name:
                return v
        return None

    @property
    def client_ip(self):
        return self.client_addr[0] if self.client_addr else ""

    @property
    def user_agent(self):
        return self.headers.get("User-Agent", "")

    @property
    def is_secure(self):
        """Whether this request arrived over TLS.

        Used to decide the Secure cookie flag. Marking the cookie Secure on a
        plain-HTTP localhost run would stop the browser storing it at all, so
        it follows the connection rather than being set unconditionally.
        """
        return bool(getattr(self, "_secure", False))


# ---------------------------------------------------------------------------
# Path patterns
# ---------------------------------------------------------------------------
_CONVERTERS = {
    "int": (r"[0-9]+", int),
    "str": (r"[^/]+", str),
}
_PARAM = re.compile(r"<(?:(int|str):)?([a-zA-Z_][a-zA-Z0-9_]*)>")


def _compile(pattern):
    """Turn ``/api/staff/<int:staff_id>`` into a regex plus a coercion map."""
    casts = {}
    out = ["^"]
    pos = 0
    for m in _PARAM.finditer(pattern):
        out.append(re.escape(pattern[pos:m.start()]))
        kind = m.group(1) or "str"
        name = m.group(2)
        rx, cast = _CONVERTERS[kind]
        casts[name] = cast
        out.append("(?P<%s>%s)" % (name, rx))
        pos = m.end()
    out.append(re.escape(pattern[pos:]))
    out.append("$")
    return re.compile("".join(out)), casts


class Router:
    def __init__(self):
        self._routes = []          # (method, regex, casts, handler, options)
        self._middleware = []

    # -- registration ----------------------------------------------------
    def route(self, method, pattern, **options):
        regex, casts = _compile(pattern)

        def decorator(fn):
            self._routes.append((method.upper(), regex, casts, fn, options))
            return fn

        return decorator

    def get(self, pattern, **options):
        return self.route("GET", pattern, **options)

    def post(self, pattern, **options):
        return self.route("POST", pattern, **options)

    def put(self, pattern, **options):
        return self.route("PUT", pattern, **options)

    def delete(self, pattern, **options):
        return self.route("DELETE", pattern, **options)

    def use(self, fn):
        """Register middleware: ``fn(request, options)``.

        Returning a Response short-circuits the request; returning None lets it
        continue to the handler.
        """
        self._middleware.append(fn)
        return fn

    # -- dispatch --------------------------------------------------------
    def match(self, method, path):
        """Find a handler. Returns ``(handler, params, options)`` or None.

        A path that matches a different method is reported separately so the
        caller can answer 405 rather than a misleading 404.
        """
        wrong_method = False
        for m, regex, casts, fn, options in self._routes:
            hit = regex.match(path)
            if not hit:
                continue
            if m != method:
                wrong_method = True
                continue
            params = {k: casts[k](v) for k, v in hit.groupdict().items()}
            return fn, params, options
        if wrong_method:
            raise HttpError(405, "Method not allowed for this path.")
        return None

    def dispatch(self, request):
        """Run middleware then the handler. Always returns a Response."""
        try:
            found = self.match(request.method, request.path)
            if found is None:
                return None                     # let the caller try static files
            handler, params, options = found

            for mw in self._middleware:
                early = mw(request, options)
                if early is not None:
                    return early

            result = handler(request, **params)
            if isinstance(result, Response):
                return result
            return Response.json(result)
        except HttpError as e:
            return Response.error(e.message, e.status, **e.extra)
        except Exception as e:                  # noqa: BLE001 - never 500 silently
            import traceback
            traceback.print_exc()
            return Response.error(
                "Server error: %s" % e.__class__.__name__, 500
            )
