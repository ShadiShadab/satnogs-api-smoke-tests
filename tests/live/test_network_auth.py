"""Unauthenticated write attempts must be rejected.

These send DELETE/PATCH/POST with no credentials and an empty body; the server must
answer 401 with a Token challenge (or 400 for a malformed POST body).

They are disabled by default and never run against public SatNOGS services. They
run only with SATNOGS_ALLOW_WRITE_PROBES=1 and a loopback or explicitly listed
non-production SATNOGS_NETWORK_URL (see satnogs_smoke/write_guard.py).
"""
import pytest

from satnogs_smoke.client import NETWORK_URL

pytestmark = [pytest.mark.live, pytest.mark.negative]


def test_delete_observation_without_token_is_401(api, recent_good_observation):
    r = api.request("DELETE", f"{NETWORK_URL}/api/observations/{recent_good_observation['id']}/")
    assert r.status == 401
    assert r.headers.get("WWW-Authenticate") == "Token"


def test_patch_station_without_token_is_401(api, recent_good_observation):
    r = api.request("PATCH", f"{NETWORK_URL}/api/stations/{recent_good_observation['ground_station']}/", json={})
    assert r.status == 401
    assert r.headers.get("WWW-Authenticate") == "Token"


def test_post_observation_without_token_is_rejected(api):
    r = api.request("POST", f"{NETWORK_URL}/api/observations/", json=[])
    assert r.status in (400, 401, 403), f"unauthenticated POST returned HTTP {r.status}"
