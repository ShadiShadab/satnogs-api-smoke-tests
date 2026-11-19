"""Decide whether a write-method request (anything other than GET/HEAD/OPTIONS) may be sent.

Write-method probes are disabled by default and fail closed. A write request is
allowed only when all of these hold:

1. SATNOGS_ALLOW_WRITE_PROBES is exactly "1". Any other value, including "true",
   "yes" or " 1", keeps probes disabled.
2. The URL is a clean http(s) URL: no user information, backslashes, whitespace,
   control characters, percent-encoded or zone-qualified hosts, invalid ports,
   non-canonical numeric hosts such as "127.1" or "0x7f.0.0.1", or IPv6 forms that
   embed an IPv4 address ("::ffff:127.0.0.1").
3. The normalised host (lower case, trailing dot removed, IDNA-encoded; port, path
   and trailing slashes ignored) is not satnogs.org or any of its subdomains. This
   check comes before the allowlist, so a public SatNOGS host is refused even if it
   is listed.
4. The host is "localhost", a loopback IP literal, or a host listed in
   SATNOGS_WRITE_PROBE_HOSTS (comma-separated). Malformed list entries are ignored.
5. Every address the host resolves to is non-public: loopback for loopback
   targets; loopback or RFC 1918 / IPv6 unique-local for listed hosts. If resolution fails, the
   request is refused.

The client also sends write requests with redirects disabled and without
environment proxy settings (see satnogs_smoke/client.py).

Limits: a host name, even one that passes these checks, does not prove that the
destination is a disposable test system. The guard cannot detect:
- a DNS answer that changes between this check and the connection (rebinding);
- a local port forward, tunnel or reverse proxy on a loopback or private address
  that relays to a production service;
- a private-network host that is itself a production gateway.
Before enabling write probes, the operator must confirm that the target is a
disposable instance they control.
"""
from __future__ import annotations

import ipaddress
import os
import re
import socket
from typing import Callable, Iterable, Mapping
from urllib.parse import urlsplit

ALLOW_ENV = "SATNOGS_ALLOW_WRITE_PROBES"
HOSTS_ENV = "SATNOGS_WRITE_PROBE_HOSTS"
READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
BLOCKED_DOMAINS = ("satnogs.org",)
LOOPBACK_NAMES = frozenset({"localhost"})
# Listed hosts must resolve only to loopback or to these private ranges (RFC 1918 and
# IPv6 unique-local). ipaddress.is_private is not used because it also covers
# documentation and other special-purpose ranges.
PRIVATE_NETWORKS = tuple(ipaddress.ip_network(n) for n in
                         ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7"))

Resolver = Callable[[str], Iterable[str]]


class WriteProbeBlocked(RuntimeError):
    """Raised when a write-method request is refused by the guard."""


def _default_resolver(host: str) -> list[str]:
    return sorted({info[4][0] for info in socket.getaddrinfo(host, None)})


def _looks_numeric(host: str) -> bool:
    """True for hosts that some resolvers read as an IPv4 address (e.g. 127.1, 0x7f.1)."""
    last = host.rsplit(".", 1)[-1]
    return last.isdigit() or bool(re.fullmatch(r"0x[0-9a-f]*", last))


def normalise_host(url: str) -> str | None:
    """Return the canonical host of a clean http(s) URL, or None if it is not clean."""
    if not isinstance(url, str) or not url:
        return None
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url) or "\\" in url:
        return None
    try:
        parts = urlsplit(url)
        parts.port  # raises ValueError for a non-numeric or out-of-range port
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc or "@" in parts.netloc:
        return None
    host = parts.hostname  # lower case, IPv6 brackets removed
    if not host or "%" in host:
        return None
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        # IPv6 forms that embed an IPv4 address are treated differently by different
        # Python versions and resolvers, so they are refused as ambiguous.
        if literal.version == 6 and (literal.ipv4_mapped or literal.sixtofour or literal.teredo
                                     or (literal in ipaddress.ip_network("::/96") and int(literal) > 1)):
            return None
        return literal.compressed
    if ":" in host:
        return None
    try:
        host = host.encode("idna").decode("ascii").lower()  # also maps full-width forms
    except UnicodeError:
        return None
    host = host.rstrip(".")
    if not host or ".." in host or _looks_numeric(host):
        return None
    return host


def _is_blocked(host: str) -> bool:
    return any(host == d or host.endswith("." + d) for d in BLOCKED_DOMAINS)


def _ip(value: str):
    try:
        return ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return None


def _listed_hosts(env: Mapping[str, str]) -> set[str]:
    hosts = set()
    for entry in env.get(HOSTS_ENV, "").split(","):
        entry = entry.strip()
        if entry and "/" not in entry and "@" not in entry:
            h = normalise_host(f"https://{entry}")
            if h is not None:
                hosts.add(h)
    return hosts


def write_probe_decision(url: str, environ: Mapping[str, str] | None = None,
                         resolver: Resolver | None = None) -> tuple[bool, str]:
    """Return (allowed, reason) for sending a write-method request to url."""
    env = os.environ if environ is None else environ
    if env.get(ALLOW_ENV) != "1":
        return False, f"write probes are disabled (set {ALLOW_ENV}=1 to enable them for a disposable non-production target)"
    host = normalise_host(url)
    if host is None:
        return False, f"target URL is not a clean http(s) URL: {url!r}"
    if _is_blocked(host):
        return False, f"write probes never run against public SatNOGS services ({host})"

    literal = _ip(host)
    if host in LOOPBACK_NAMES or (literal is not None and literal.is_loopback):
        kind, ok = "loopback", (lambda a: a.is_loopback)
    elif host in _listed_hosts(env):
        kind, ok = "listed", (lambda a: a.is_loopback or any(a in n for n in PRIVATE_NETWORKS if a.version == n.version))
    else:
        return False, f"target {host} is not loopback and not listed in {HOSTS_ENV}"

    try:
        addresses = list((resolver or _default_resolver)(host))
    except (OSError, UnicodeError, ValueError):
        return False, f"target {host} could not be resolved"
    parsed = [_ip(a) for a in addresses]
    if not parsed or any(a is None or not ok(a) for a in parsed):
        return False, f"{kind} target {host} resolves to {addresses}, which includes a non-{'loopback' if kind == 'loopback' else 'private'} address"
    return True, f"{kind} target {host} resolves only to {addresses}"


def check_request(method: str, url: str, environ: Mapping[str, str] | None = None,
                  resolver: Resolver | None = None) -> None:
    """Raise WriteProbeBlocked unless the request is read-only or explicitly allowed."""
    if method.upper() in READ_METHODS:
        return
    allowed, reason = write_probe_decision(url, environ, resolver)
    if not allowed:
        raise WriteProbeBlocked(f"{method.upper()} {url} refused: {reason}")
