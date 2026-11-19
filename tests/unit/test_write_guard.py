"""Offline tests for the write-probe guard.

No test here contacts anything except servers started on 127.0.0.1 by the test itself.
Any attempt to connect to a non-loopback address fails the test.
"""
import http.server
import re
import socket
import threading
from pathlib import Path

import pytest
import requests

from satnogs_smoke import write_guard as wg
from satnogs_smoke.client import Api

ON = {wg.ALLOW_ENV: "1"}
WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "smoke.yml"


def resolver(table):
    def resolve(host):
        if host not in table:
            raise OSError(f"unknown host {host}")
        return table[host]
    return resolve


LOCAL = resolver({"localhost": ["127.0.0.1", "::1"], "127.0.0.1": ["127.0.0.1"], "127.0.0.2": ["127.0.0.2"],
                  "::1": ["::1"], "staging.example.org": ["10.0.0.5"], "other.test": ["192.168.1.20"]})


@pytest.fixture(autouse=True)
def no_external_connections(monkeypatch):
    """Fail if anything tries to connect to a non-loopback address."""
    real = socket.socket.connect
    attempts = []

    def guarded(self, address):
        host = address[0] if isinstance(address, tuple) else address
        attempts.append(host)
        if host not in ("127.0.0.1", "::1"):
            raise AssertionError(f"test attempted a non-loopback connection to {address}")
        return real(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)
    return attempts


# ---------------------------------------------------------------- production hosts

PRODUCTION_VARIANTS = [
    "https://network.satnogs.org",
    "https://network.satnogs.org/",
    "https://network.satnogs.org//",
    "https://network.satnogs.org/api/observations/",
    "https://network.satnogs.org/api/../api/observations/1/",
    "https://network.satnogs.org?x=1",
    "https://network.satnogs.org#frag",
    "https://NETWORK.SATNOGS.ORG",
    "https://Network.SatNOGS.org/",
    "HTTPS://network.satnogs.org",
    "https://network.satnogs.org.",
    "https://network.satnogs.org./api/",
    "https://network.satnogs.org:443",
    "https://network.satnogs.org:443/",
    "https://network.satnogs.org:0443/api/",
    "https://network.satnogs.org:8443",
    "http://network.satnogs.org",
    "http://network.satnogs.org:80/",
    "http://NETWORK.satnogs.org.:80/api/",
    "https://ｎｅｔｗｏｒｋ.satnogs.org",       # full-width letters (IDNA maps to ASCII)
    "https://network。satnogs。org",          # ideographic full stops (IDNA separators)
    "https://satnogs.org",
    "https://www.satnogs.org",
    "https://db.satnogs.org",
    "https://network-dev.satnogs.org",
    "https://dev.network.satnogs.org",
    "https://a.b.c.satnogs.org",
]


@pytest.mark.parametrize("url", PRODUCTION_VARIANTS)
def test_production_variants_refused_when_enabled(url):
    allowed, reason = wg.write_probe_decision(url, ON, LOCAL)
    assert allowed is False
    assert "public SatNOGS" in reason or "not a clean" in reason


@pytest.mark.parametrize("url", PRODUCTION_VARIANTS)
def test_production_refused_even_if_allowlisted(url):
    env = {**ON, wg.HOSTS_ENV: "network.satnogs.org, NETWORK.SATNOGS.ORG., db.satnogs.org,satnogs.org,*.satnogs.org"}
    always_private = lambda host: ["127.0.0.1"]  # even a resolver that answers loopback must not help
    assert wg.write_probe_decision(url, env, always_private)[0] is False


@pytest.mark.parametrize("url", ["https://network.satnogs.org", "https://network.satnogs.org/"])
def test_normalised_production_host(url):
    assert wg.normalise_host(url) == "network.satnogs.org"


def test_trailing_dot_case_and_port_normalise_to_same_host():
    hosts = {wg.normalise_host(u) for u in
             ["https://network.satnogs.org", "https://NETWORK.satnogs.org.", "http://network.satnogs.org:443/x/"]}
    assert hosts == {"network.satnogs.org"}


def test_lookalike_hosts_are_not_treated_as_satnogs_but_still_fail_closed():
    for url in ["https://satnogs.org.example.test", "https://notsatnogs.org", "https://network.satnogs.org-x.test"]:
        allowed, reason = wg.write_probe_decision(url, ON, LOCAL)
        assert allowed is False and "not loopback and not listed" in reason


# ---------------------------------------------------------------- malformed and ambiguous

MALFORMED = [
    "", "   ", "network.satnogs.org", "//network.satnogs.org", "localhost:8000", "ftp://localhost",
    "file:///etc/passwd", "https://", "https:///api/", "https://:8000",
    "https://user@localhost", "https://user:pw@localhost:8000", "https://@localhost",
    "https://network.satnogs.org@localhost", "https://localhost@network.satnogs.org",
    "https://localhost%40network.satnogs.org", "https://network.satnogs.org\\@localhost",
    "https://localhost\\.network.satnogs.org", " https://localhost", "https://localhost ",
    "https://local host", "https://localhost\t", "https://localhost\n.evil", "https://local\x00host",
    "https://localhost:99999", "https://localhost:-1", "https://localhost:abc", "https://localhost:80:80",
    "https://network%2esatnogs%2eorg", "https://[::1", "https://[fe80::1%25eth0]",
    "https://127.1", "https://127.0.1", "https://2130706433", "https://0x7f.0.0.1", "https://0x7f000001",
    "https://017700000001", "https://localhost..", "https://..", "https://a..b",
    "https://[::ffff:127.0.0.1]", "https://[::ffff:7f00:1]", "https://[::127.0.0.1]", "https://[2002:7f00:1::1]",
]


@pytest.mark.parametrize("url", MALFORMED)
def test_malformed_or_ambiguous_targets_fail_closed(url):
    env = {**ON, wg.HOSTS_ENV: "localhost,127.1,2130706433,0x7f.0.0.1"}
    allowed, reason = wg.write_probe_decision(url, env, LOCAL)
    assert allowed is False, reason


def test_non_string_target_fails_closed():
    assert wg.write_probe_decision(None, ON, LOCAL)[0] is False  # type: ignore[arg-type]


# ---------------------------------------------------------------- unknown hosts

@pytest.mark.parametrize("url", [
    "https://staging.example.org", "https://example.org", "https://10.0.0.5", "https://192.168.1.20",
    "https://203.0.113.7", "https://[2001:db8::1]", "https://localhost.example.org",
])
def test_unknown_hosts_fail_closed(url):
    allowed, reason = wg.write_probe_decision(url, ON, LOCAL)
    assert allowed is False, reason


# ---------------------------------------------------------------- configuration values

@pytest.mark.parametrize("value", [None, "", "0", "1 ", " 1", "01", "true", "TRUE", "yes", "on", "enable", "2", "-1"])
def test_only_exact_opt_in_value_enables(value):
    env = {} if value is None else {wg.ALLOW_ENV: value}
    for url in ("http://127.0.0.1:8000", "https://network.satnogs.org"):
        allowed, reason = wg.write_probe_decision(url, env, LOCAL)
        assert allowed is False and "disabled" in reason


def test_malformed_allowlist_entries_are_ignored():
    env = {**ON, wg.HOSTS_ENV: "https://staging.example.org/, user@staging.example.org, staging.example.org/x, ,"}
    assert wg.write_probe_decision("https://staging.example.org", env, LOCAL)[0] is False


# ---------------------------------------------------------------- loopback and listed hosts

@pytest.mark.parametrize("url", [
    "http://localhost:8000", "http://LOCALHOST:8000/", "http://localhost.:8000",
    "http://127.0.0.1:8000", "http://127.0.0.2", "http://[::1]:8000/api/",
])
def test_loopback_allowed_only_when_enabled(url):
    assert wg.write_probe_decision(url, ON, LOCAL)[0] is True
    assert wg.write_probe_decision(url, {}, LOCAL)[0] is False


def test_listed_non_production_hosts_allowed_when_private():
    env = {**ON, wg.HOSTS_ENV: " Staging.Example.org. , other.test"}
    assert wg.write_probe_decision("https://staging.example.org/api/", env, LOCAL)[0] is True
    assert wg.write_probe_decision("https://other.test:8443", env, LOCAL)[0] is True
    assert wg.write_probe_decision("https://sub.staging.example.org/", env, LOCAL)[0] is False


@pytest.mark.parametrize("answer", [["8.8.8.8"], ["203.0.113.7"], ["10.0.0.5", "8.8.8.8"], ["2001:4860:4860::8888"],
                                    ["2001:db8::1"], ["100.64.0.1"], ["169.254.1.1"], [], ["not-an-ip"]])
def test_listed_host_resolving_to_public_or_unknown_address_is_refused(answer):
    """DNS alias protection: a listed name that points at a public address is refused."""
    env = {**ON, wg.HOSTS_ENV: "staging.example.org"}
    assert wg.write_probe_decision("https://staging.example.org", env, lambda h: answer)[0] is False


def test_localhost_alias_to_non_loopback_is_refused():
    """A hosts-file entry pointing 'localhost' elsewhere must not enable a write."""
    assert wg.write_probe_decision("http://localhost:8000", ON, lambda h: ["127.0.0.1", "10.0.0.5"])[0] is False
    assert wg.write_probe_decision("http://localhost:8000", ON, lambda h: ["203.0.113.7"])[0] is False


def test_resolution_failure_is_refused():
    def fail(host):
        raise OSError("no such host")
    env = {**ON, wg.HOSTS_ENV: "staging.example.org"}
    assert wg.write_probe_decision("https://staging.example.org", env, fail)[0] is False
    assert wg.write_probe_decision("http://localhost:8000", ON, fail)[0] is False


# ---------------------------------------------------------------- check_request

@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS", "get", "head"])
def test_read_methods_are_never_blocked(method):
    wg.check_request(method, "https://network.satnogs.org/api/", {})


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "delete", "TRACE", "CONNECT", "PROPFIND"])
def test_write_methods_to_production_raise(method):
    with pytest.raises(wg.WriteProbeBlocked):
        wg.check_request(method, "https://network.satnogs.org/api/observations/1/", ON, LOCAL)


# ---------------------------------------------------------------- client-level protection

def test_client_refuses_before_any_transmission(monkeypatch, no_external_connections):
    monkeypatch.setenv(wg.ALLOW_ENV, "1")
    monkeypatch.setenv(wg.HOSTS_ENV, "network.satnogs.org")

    def boom(*a, **kw):
        raise AssertionError("a request reached the HTTP session")

    monkeypatch.setattr(requests.Session, "request", boom)
    monkeypatch.setattr(requests.Session, "send", boom)
    api = Api()
    for url in PRODUCTION_VARIANTS[:12]:
        for method in ("DELETE", "PATCH", "POST", "PUT"):
            with pytest.raises(wg.WriteProbeBlocked):
                api.request(method, url)
    assert no_external_connections == []


def test_client_refuses_by_default_even_for_loopback(monkeypatch, no_external_connections):
    monkeypatch.delenv(wg.ALLOW_ENV, raising=False)
    monkeypatch.setattr(requests.Session, "request", lambda *a, **k: (_ for _ in ()).throw(AssertionError("sent")))
    with pytest.raises(wg.WriteProbeBlocked):
        Api().request("POST", "http://127.0.0.1:9/api/observations/")
    assert no_external_connections == []


class _Recorder(http.server.BaseHTTPRequestHandler):
    """Local fake server. Writes are answered with a redirect to production."""
    hits: list = []

    def _reply(self, code, headers=()):
        type(self).hits.append((self.command, self.path))
        self.send_response(code)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        self._reply(200, [("Content-Type", "application/json")])

    def _redirect(self):
        self._reply(307, [("Location", "https://network.satnogs.org/api/observations/")])

    do_POST = do_PATCH = do_DELETE = do_PUT = _redirect

    def log_message(self, *a):
        pass


@pytest.fixture
def local_server():
    _Recorder.hits = []
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Recorder)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_port}", _Recorder.hits
    srv.shutdown()
    srv.server_close()


@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE", "PUT"])
def test_redirect_towards_production_is_not_followed(monkeypatch, local_server, no_external_connections, method):
    base, hits = local_server
    monkeypatch.setenv(wg.ALLOW_ENV, "1")
    r = Api().request(method, f"{base}/api/observations/1/", json={})
    assert r.status == 307
    assert r.headers["Location"].startswith("https://network.satnogs.org")
    assert hits == [(method, "/api/observations/1/")]
    assert all(h == "127.0.0.1" for h in no_external_connections)


def test_caller_cannot_re_enable_redirects(monkeypatch, local_server, no_external_connections):
    base, _ = local_server
    monkeypatch.setenv(wg.ALLOW_ENV, "1")
    r = Api().request("POST", f"{base}/api/observations/", allow_redirects=True, json=[])
    assert r.status == 307
    assert all(h == "127.0.0.1" for h in no_external_connections)


def test_write_requests_ignore_environment_proxies(monkeypatch, local_server):
    """Read requests honour HTTP_PROXY; write requests must not be relayed by it."""
    target, target_hits = local_server
    proxy_hits = []

    class Proxy(http.server.BaseHTTPRequestHandler):
        def _any(self):
            proxy_hits.append((self.command, self.path))
            self.send_response(502)
            self.send_header("Content-Length", "0")
            self.end_headers()

        do_GET = do_POST = do_PATCH = do_DELETE = do_PUT = do_CONNECT = _any

        def log_message(self, *a):
            pass

    proxy = http.server.HTTPServer(("127.0.0.1", 0), Proxy)
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    try:
        for var in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
            monkeypatch.setenv(var, f"http://127.0.0.1:{proxy.server_port}")
        for var in ("NO_PROXY", "no_proxy"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv(wg.ALLOW_ENV, "1")
        api = Api()
        api.session.request("GET", f"{target}/", timeout=5)
        assert proxy_hits, "control: the read session should use the environment proxy"
        proxy_hits.clear()
        r = api.request("POST", f"{target}/api/observations/", json=[], proxies={"http": f"http://127.0.0.1:{proxy.server_port}"})
        assert r.status == 307
        assert proxy_hits == []
        assert ("POST", "/api/observations/") in target_hits
    finally:
        proxy.shutdown()
        proxy.server_close()


# ---------------------------------------------------------------- GitHub Actions configuration

def _workflow():
    return WORKFLOW.read_text(encoding="utf-8")


def _triggers(text):
    block = re.search(r"^on:\n((?:[ \t]+.*\n|\n)+)", text, re.M)
    assert block, "workflow must use a block-style 'on:' section"
    return re.findall(r"^  ([a-z_]+):", block.group(1), re.M)


def _workflow_env(text):
    block = re.search(r"^env:\n((?:[ \t]+.*\n)+)", text, re.M)
    assert block, "workflow must define a top-level env block"
    return dict(re.findall(r'^\s+([A-Z_]+):\s*"([^"]*)"', block.group(1), re.M))


def test_workflow_pins_write_probes_off_for_every_job():
    text = _workflow()
    assert _workflow_env(text).get(wg.ALLOW_ENV) == "0"
    assert text.count(wg.ALLOW_ENV) == 1, "the variable must not be overridden at job or step level"
    assert wg.HOSTS_ENV not in text
    assert "SATNOGS_NETWORK_URL" not in text


def test_workflow_has_no_inputs_or_expressions_that_could_enable_probes():
    text = _workflow()
    assert "inputs:" not in text
    for expr in re.findall(r"\$\{\{(.*?)\}\}", text):
        assert not re.search(r"vars\.|secrets\.|inputs\.|github\.event", expr), expr


@pytest.mark.parametrize("event", ["push", "pull_request", "workflow_dispatch", "schedule"])
def test_each_trigger_runs_with_write_probes_disabled(event):
    """Every trigger present in the workflow gets the same pinned environment."""
    text = _workflow()
    triggers = _triggers(text)
    if event not in triggers:
        pytest.skip(f"workflow has no {event} trigger")
    env = _workflow_env(text)
    for url in ("https://network.satnogs.org", "http://127.0.0.1:8000"):
        allowed, reason = wg.write_probe_decision(url, env, LOCAL)
        assert allowed is False and "disabled" in reason
