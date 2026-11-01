from satnogs_smoke.links import parse_link_header


def test_next_link_is_parsed():
    v = '<https://network.satnogs.org/api/observations/?cursor=abc&norad_cat_id=25544>; rel="next"'
    assert parse_link_header(v) == {"next": "https://network.satnogs.org/api/observations/?cursor=abc&norad_cat_id=25544"}


def test_multiple_and_missing():
    v = '<https://x/?c=1>; rel="prev", <https://x/?c=2>; rel="next"'
    assert parse_link_header(v) == {"prev": "https://x/?c=1", "next": "https://x/?c=2"}
    assert parse_link_header(None) == {}
