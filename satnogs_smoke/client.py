"""Small HTTP helper shared by the live tests.

Design rules:
- GET and HEAD by default: every other method goes through write_guard before
  anything is sent. The guard refuses it unless write probes are explicitly
  enabled for a loopback or listed non-production host, and always refuses public
  SatNOGS services. Write-method requests never follow redirects and ignore
  environment proxy settings (separate session with trust_env=False);
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

from satnogs_smoke.write_guard import READ_METHODS, check_request

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
        # Write requests use their own session that ignores HTTP(S)_PROXY, ALL_PROXY
        # and .netrc, so an environment proxy cannot relay them to another host.
        self.write_session = requests.Session()
        self.write_session.trust_env = False
        self.write_session.headers.update(self.session.headers)

    def request(self, method: str, url: str, **kw) -> Response:
        check_request(method, url)
        session = self.session
        if method.upper() not in READ_METHODS:
            kw["allow_redirects"] = False
            kw["proxies"] = {"http": None, "https": None, "all": None}
            session = self.write_session
        for attempt in (1, 2):
            t0 = time.monotonic()
            r = session.request(method, url, timeout=TIMEOUT_S, **kw)
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
