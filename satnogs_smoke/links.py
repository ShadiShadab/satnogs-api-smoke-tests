"""Parse RFC 8288 Link headers, as used by the Network API's cursor pagination."""
from __future__ import annotations

import re

_LINK = re.compile(r'<([^>]+)>\s*;\s*rel="?([^";]+)"?')


def parse_link_header(value: str | None) -> dict[str, str]:
    return {rel: url for url, rel in _LINK.findall(value or "")}
