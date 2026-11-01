"""Live, read-only checks against the SatNOGS Network API (network.satnogs.org/api/)."""
from datetime import datetime, timezone

import pytest

from satnogs_smoke.client import NETWORK_URL, SLOW_RESPONSE_S
from satnogs_smoke.links import parse_link_header

pytestmark = pytest.mark.live

OBSERVATION_FIELDS = {
    "id", "start", "end", "ground_station", "transmitter", "norad_cat_id", "payload",
    "waterfall", "demoddata", "station_name", "status", "vetted_user", "waterfall_status",
    "client_version", "client_metadata", "observer", "tle0", "tle1", "tle2",
}
OBSERVATION_STATUSES = {"future", "good", "bad", "unknown", "failed"}
STATION_FIELDS = {"id", "name", "status", "observations", "client_version", "antenna", "last_seen"}
STATION_STATUSES = {"Online", "Offline", "Testing"}


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_api_root_lists_resources(api):
    r = api.get(f"{NETWORK_URL}/api/")
    assert r.status == 200
    assert {"jobs", "observations", "stations"} <= set(r.body)


def test_observation_list_is_json_and_fast(api):
    r = api.get(f"{NETWORK_URL}/api/observations/")
    assert r.status == 200
    assert r.headers["Content-Type"].startswith("application/json")
    assert isinstance(r.body, list) and r.body, "empty observation list"
    assert r.elapsed_s < SLOW_RESPONSE_S, f"list took {r.elapsed_s:.1f} s"


def test_observation_detail_schema(api, recent_good_observation):
    obs_id = recent_good_observation["id"]
    r = api.get(f"{NETWORK_URL}/api/observations/{obs_id}/")
    assert r.status == 200
    missing = OBSERVATION_FIELDS - set(r.body)
    assert not missing, f"fields missing from observation {obs_id}: {sorted(missing)}"
    assert r.body["status"] in OBSERVATION_STATUSES
    assert _ts(r.body["start"]) < _ts(r.body["end"])
    assert isinstance(r.body["demoddata"], list)


def test_unknown_observation_returns_404_json(api):
    r = api.get(f"{NETWORK_URL}/api/observations/999999999/")
    assert r.status == 404
    assert "detail" in r.body


def test_filter_by_norad_cat_id_is_respected(api):
    r = api.get(f"{NETWORK_URL}/api/observations/", params={"norad_cat_id": 25544})
    assert r.status == 200
    assert r.body, "no ISS observations returned"
    assert {o["norad_cat_id"] for o in r.body} == {25544}


def test_filter_by_ground_station_is_respected(api, recent_good_observation):
    gs = recent_good_observation["ground_station"]
    r = api.get(f"{NETWORK_URL}/api/observations/", params={"ground_station": gs})
    assert r.status == 200
    assert {o["ground_station"] for o in r.body} == {gs}


def test_filter_by_time_window_is_respected(api):
    start, end = "2026-10-01T00:00:00Z", "2026-10-01T01:00:00Z"
    r = api.get(f"{NETWORK_URL}/api/observations/", params={"start": start, "end": end})
    assert r.status == 200
    assert r.body, "no observations in a one-hour window"
    for o in r.body:
        assert _ts(o["start"]) >= _ts(start), o["id"]
        assert _ts(o["end"]) <= _ts(end), o["id"]


def test_cursor_pagination_returns_a_distinct_next_page(api):
    first = api.get(f"{NETWORK_URL}/api/observations/", params={"norad_cat_id": 25544})
    links = parse_link_header(first.headers.get("Link"))
    assert "next" in links, "no rel=next Link header"
    second = api.get(links["next"])
    assert second.status == 200
    ids1, ids2 = {o["id"] for o in first.body}, {o["id"] for o in second.body}
    assert ids2 and not ids1 & ids2, "pages overlap"


def test_station_detail_schema(api, recent_good_observation):
    gs = recent_good_observation["ground_station"]
    r = api.get(f"{NETWORK_URL}/api/stations/{gs}/")
    assert r.status == 200
    missing = STATION_FIELDS - set(r.body)
    assert not missing, f"fields missing from station {gs}: {sorted(missing)}"
    assert r.body["status"] in STATION_STATUSES
    assert isinstance(r.body["observations"], int) and r.body["observations"] > 0


@pytest.mark.parametrize("artifact", ["waterfall", "payload"])
def test_artifacts_of_a_good_observation_are_reachable(api, recent_good_observation, artifact):
    url = recent_good_observation[artifact]
    r = api.head(url)
    assert r.status == 200, f"{artifact} HEAD returned HTTP {r.status}: {url}"
    assert int(r.headers.get("Content-Length", "0")) > 0, f"{artifact} is empty"


def test_jobs_endpoint_lists_future_work_with_tle(api):
    """A station with a future observation must see it as a job carrying a TLE."""
    future = api.get(f"{NETWORK_URL}/api/observations/", params={"status": "future"})
    assert future.status == 200
    candidates = [o for o in future.body if o["status"] == "future"]
    if not candidates:
        pytest.skip("no future observation on the first page")
    gs = candidates[0]["ground_station"]
    r = api.get(f"{NETWORK_URL}/api/jobs/", params={"ground_station": gs})
    assert r.status == 200
    assert r.body, f"station {gs} has a future observation but no jobs"
    assert {j["ground_station"] for j in r.body} == {gs}
    for job in r.body:
        assert {"id", "start", "end", "tle1", "tle2", "frequency", "mode"} <= set(job)
