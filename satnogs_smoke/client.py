"""Small HTTP helper shared by the live tests.

Design rules:
- read-only: only GET and HEAD are used, except the explicit "unauthenticated
  write is rejected" checks, which send no credentials and no body that could
  change anything;
- polite: one shared session, a descriptive User-Agent, a timeout on every call,
  and a single retry for gateway errors only (502/503/504), so a transient CDN
  hiccup is not reported as a product failure;
- configurable through environment variables, so the same suite can target a
  staging instance.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

import requests

NETWORK_URL = os.environ.get("SATNOGS_NETWORK_URL", "https://network.satnogs.org").rstrip("/")
DB_URL = os.environ.get("SATNOGS_DB_URL", "https://db.satnogs.org").rstrip("/")
TIMEOUT_S = float(os.environ.get("SATNOGS_TIMEOUT_S", "60"))
SLOW_RESPONSE_S = float(os.environ.get("SATNOGS_SLOW_RESPONSE_S", "10"))
USER_AGENT = "satnogs-api-smoke-tests/0.1 (+https://github.com/ShadiShadab/satnogs-api-smoke-tests)"
_RETRY_STATUS = {502, 503, 504}


@dataclass
class Response:
    status: int
    headers: requests.structures.CaseInsensitiveDict
    elapsed_s: float
    body: object  # parsed JSON, or None
    url: str


class Api:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})

    def request(self, method: str, url: str, **kw) -> Response:
        for attempt in (1, 2):
            t0 = time.monotonic()
            r = self.session.request(method, url, timeout=TIMEOUT_S, **kw)
            elapsed = time.monotonic() - t0
            if r.status_code not in _RETRY_STATUS or attempt == 2:
                break
            time.sleep(5)
        body = None
        if "json" in r.headers.get("Content-Type", ""):
            body = r.json()
        return Response(r.status_code, r.headers, elapsed, body, r.url)

    def get(self, url: str, **kw) -> Response:
        return self.request("GET", url, **kw)

    def head(self, url: str, **kw) -> Response:
        return self.request("HEAD", url, allow_redirects=True, **kw)
