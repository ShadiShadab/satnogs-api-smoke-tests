"""Live, read-only checks against the SatNOGS DB API (db.satnogs.org/api/)."""
import pytest

from satnogs_smoke.client import DB_URL
from satnogs_smoke.tle import validate

pytestmark = pytest.mark.live

ISS = 25544


def test_satellite_lookup_by_norad_id(api):
    r = api.get(f"{DB_URL}/api/satellites/", params={"norad_cat_id": ISS})
    assert r.status == 200
    assert len(r.body) == 1
    sat = r.body[0]
    assert sat["norad_cat_id"] == ISS
    assert {"sat_id", "name", "status"} <= set(sat)


def test_transmitter_filter_by_satellite_norad_id(api):
    r = api.get(f"{DB_URL}/api/transmitters/", params={"satellite__norad_cat_id": ISS})
    assert r.status == 200
    assert r.body, "ISS has no transmitters"
    assert {t["norad_cat_id"] for t in r.body} == {ISS}
    for t in r.body:
        assert isinstance(t["alive"], bool)
        assert t["status"] in {"active", "inactive", "invalid"}


def test_tle_is_well_formed(api):
    r = api.get(f"{DB_URL}/api/tle/", params={"norad_cat_id": ISS})
    assert r.status == 200
    assert len(r.body) == 1
    tle = r.body[0]
    assert validate(tle["tle1"], tle["tle2"], ISS) == []


@pytest.mark.slow
def test_unknown_filter_parameter_is_ignored_current_behaviour(api):
    """Documents current behaviour: an unsupported filter is silently ignored.

    `?satellite=<anything>` returns the full transmitter list instead of an error or an
    empty list. This was recorded as a defect candidate during station QA; the test
    fails if the behaviour changes, so the change is noticed. Slow (about 4 MB).
    """
    r = api.get(f"{DB_URL}/api/transmitters/", params={"satellite": "no-such-satellite"})
    assert r.status == 200
    assert len(r.body) > 1000
