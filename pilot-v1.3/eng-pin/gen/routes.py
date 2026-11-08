"""Frozen model routes (PREREG v1.1 §3.1 and §0.1a). Stdlib only, no network.

Since v1.1 (C1, approved by Aditya 22 Oct 13:59 IST), semi-real (INTERNAL) text may go to the
**frozen §3.1 model routes only**, via the local OpenAI-compatible proxy. Every real adapter calls
``check_route`` before any request, for every register. Anything else is refused: another host,
port, scheme or path, a trailing variant of the URL, or a model that is not frozen for the role.

J1 (gpt-6.1-sol) is reached through the native Codex binary, not through these chat routes, so it
is not listed here (M3).
"""
from __future__ import annotations

PROXY_BASE_URL = "http://127.0.0.1:10100/v1"
ANSWERER = "xai/grok-4.7"
RENDERER = "google-antigravity/gemini-3.8-flash"
J3 = "google-antigravity/gemini-3.8-flash"

# role -> frozen model id (all on PROXY_BASE_URL, chat completions)
FROZEN_ROUTES = {
    "answerer": ANSWERER,
    "writer": ANSWERER,            # A3 extractor, A4/A5 extraction
    "adjudicator": ANSWERER,       # A4/A5 review-card adjudication (a writer-side call)
    "renderer": RENDERER,          # synthetic session renderer
    "judge_j3": J3,                # committee judge (M3)
    "tiebreak": J3,                # M3; same route as J3 unless the prereg says otherwise
}


class RouteRefused(RuntimeError):
    """A call targeted an endpoint or model outside the frozen §3.1 routes."""


def check_route(role: str, base_url: str, model: str) -> str:
    """Return the canonical chat-completions URL, or raise RouteRefused."""
    if role not in FROZEN_ROUTES:
        raise RouteRefused(f"unknown role {role!r}: not a frozen §3.1 route")
    if base_url != PROXY_BASE_URL:
        raise RouteRefused(f"endpoint {base_url!r} is not the frozen local proxy {PROXY_BASE_URL}")
    if model != FROZEN_ROUTES[role]:
        raise RouteRefused(f"model {model!r} is not frozen for role {role!r} (expected {FROZEN_ROUTES[role]!r})")
    return f"{PROXY_BASE_URL}/chat/completions"


# --------------------------------------------------------------------------- transport (Codex M2.1 #4)
# Checking the URL is not enough: urllib's default opener honours http_proxy/https_proxy/all_proxy from the
# environment and follows redirects, either of which could carry INTERNAL text to another endpoint. Every
# real call therefore goes through ``post_frozen``: environment proxies disabled, redirects refused.

def _opener():
    import urllib.request  # deferred: nothing imports the network stack unless a real call is made

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise RouteRefused(f"redirect {code} to {newurl!r} refused: frozen route only (C1)")

    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def _transport(req, timeout):
    return _opener().open(req, timeout=timeout)


def post_frozen(url: str, body: bytes, headers: dict, timeout: float):
    """POST to the frozen proxy and return the response object (a context manager)."""
    if url != f"{PROXY_BASE_URL}/chat/completions":
        raise RouteRefused(f"{url!r} is not the frozen chat-completions URL")
    import urllib.request
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    return _transport(req, timeout)


class guarded_urlopen:
    """Context manager for third-party code that calls ``urllib.request.urlopen`` itself (p3-mech's
    document door, Codex M2.1 second pass): while active, every urlopen must target the frozen
    chat-completions URL and goes through the no-proxy / no-redirect transport; anything else raises
    RouteRefused. The original function is restored on exit."""

    def __enter__(self):
        import urllib.request
        self._mod, self._orig = urllib.request, urllib.request.urlopen

        def _guarded(url, data=None, timeout=60, **_kw):
            req = url if isinstance(url, urllib.request.Request) else urllib.request.Request(url, data=data)
            if data is not None and req.data is None:
                req.data = data
            if req.full_url != f"{PROXY_BASE_URL}/chat/completions":
                raise RouteRefused(f"urlopen({req.full_url!r}) refused: frozen route only (C1)")
            return _transport(req, timeout)

        urllib.request.urlopen = _guarded
        return self

    def __exit__(self, *exc):
        self._mod.urlopen = self._orig
        return False
