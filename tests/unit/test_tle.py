from satnogs_smoke.tle import checksum, validate

# ISS element set as returned by db.satnogs.org on 2026-11-01.
L1 = "1 25544U 98067A   26305.20860139  .00006903  00000-0  13267-3 0  9995"
L2 = "2 25544  51.6332 342.0408 0007056 334.5041  25.5599 15.49138562592994"


def test_valid_pair_has_no_problems():
    assert validate(L1, L2, 25544) == []


def test_checksum_counts_minus_as_one():
    assert checksum("-" * 68) == 68 % 10


def test_corrupted_digit_is_detected():
    bad = L1[:20] + ("1" if L1[20] != "1" else "2") + L1[21:]
    assert "line 1: checksum mismatch" in validate(bad, L2)


def test_wrong_length_and_line_number():
    assert validate(L1[:-1], L2)[0].startswith("line 1: length")
    assert any("expected '2'" in p for p in validate(L1, "3" + L2[1:]))


def test_catalogue_number_mismatch():
    assert validate(L1, L2, 99999) == ["catalogue number 25544 does not match requested 99999"]
