import pytest

from satnogs_smoke.client import Api, NETWORK_URL


@pytest.fixture(scope="session")
def api():
    return Api()


@pytest.fixture(scope="session")
def recent_good_observation(api):
    """A recent observation vetted 'good' that has both audio and waterfall artifacts.

    Discovered at run time, so the suite does not depend on any one station or observation.
    """
    r = api.get(f"{NETWORK_URL}/api/observations/", params={"status": "good"})
    assert r.status == 200, f"observation list returned HTTP {r.status}"
    for obs in r.body:
        if obs.get("status") == "good" and obs.get("payload") and obs.get("waterfall"):
            return obs
    pytest.skip("no recent 'good' observation with both artifacts on the first page")
