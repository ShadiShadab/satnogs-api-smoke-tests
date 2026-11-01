"""Two-line element (TLE) format checks, independent of any network call."""
from __future__ import annotations


def checksum(line: str) -> int:
    """Modulo-10 checksum over the first 68 characters: digits count as their value, '-' as 1."""
    total = 0
    for ch in line[:68]:
        if ch.isdigit():
            total += int(ch)
        elif ch == "-":
            total += 1
    return total % 10


def validate(tle1: str, tle2: str, norad_cat_id: int | None = None) -> list[str]:
    """Return a list of problems; an empty list means the TLE pair is well formed."""
    problems: list[str] = []
    for n, line in ((1, tle1), (2, tle2)):
        if len(line) != 69:
            problems.append(f"line {n}: length {len(line)}, expected 69")
            continue
        if line[0] != str(n):
            problems.append(f"line {n}: starts with {line[0]!r}, expected '{n}'")
        if not line[68].isdigit() or checksum(line) != int(line[68]):
            problems.append(f"line {n}: checksum mismatch")
    if not problems:
        id1, id2 = tle1[2:7].strip(), tle2[2:7].strip()
        if id1 != id2:
            problems.append(f"catalogue numbers differ: {id1} vs {id2}")
        elif norad_cat_id is not None and id1.isdigit() and int(id1) != norad_cat_id:
            problems.append(f"catalogue number {id1} does not match requested {norad_cat_id}")
    return problems
