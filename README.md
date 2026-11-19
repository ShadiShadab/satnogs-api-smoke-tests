# SatNOGS API Smoke Tests

[![smoke](https://github.com/ShadiShadab/satnogs-api-smoke-tests/actions/workflows/smoke.yml/badge.svg)](https://github.com/ShadiShadab/satnogs-api-smoke-tests/actions/workflows/smoke.yml)

A small pytest suite that checks the public [SatNOGS](https://satnogs.org) Network and DB APIs still behave the way a ground station and its operator depend on.

It is the first automation step from my [SatNOGS ground-station QA work](https://github.com/ShadiShadab): API checks that I had been running by hand with `curl`, turned into repeatable tests.

## What it checks

| Area | Test | Why it matters |
|---|---|---|
| Network API | API root lists `jobs`, `observations`, `stations` | Basic availability and discoverability |
| | Observation list is JSON and responds within a time budget | Clients and dashboards poll it |
| | Observation detail has the fields stations and reviewers rely on, a valid status, and `start < end` | Schema drift breaks tools silently |
| | Unknown observation → `404` with a JSON `detail` | Clear errors for clients |
| | Filters respected: `norad_cat_id`, `ground_station`, `start`/`end` window | A filter that is silently ignored returns wrong data with HTTP 200 |
| | Cursor pagination: `Link: rel="next"` returns a distinct next page | No duplicates or gaps when paging |
| | Station detail schema and status values | Station dashboards and scheduling |
| | Waterfall and audio artifacts of a recent good observation are reachable (`HEAD 200`, non-empty) | Uploaded data can actually be retrieved |
| | `/api/jobs/` for a station with a future observation returns that station's jobs with TLEs | This is what the client polls to know what to record |
| Auth (negative, off by default) | Unauthenticated `DELETE`/`PATCH` → `401` with `WWW-Authenticate: Token`; unauthenticated `POST` rejected. Runs only against a local or explicitly listed non-production instance | Write paths are protected |
| DB API | Satellite lookup by NORAD ID | Scheduling depends on it |
| | Transmitter filter by `satellite__norad_cat_id` respected; valid `status` and `alive` values | Wrong transmitter data means wrong frequencies |
| | TLE lines are well formed: length, line numbers, modulo-10 checksums, matching catalogue number | A corrupt TLE means a wrong pass prediction |
| | (slow, opt-in) Unsupported `?satellite=` filter is ignored: documents current behaviour, so a change is noticed | A filter that is silently ignored returns misleading data |

Test data is discovered at run time (for example "the most recent observation vetted good"), so the suite does not depend on any one station, and it does not hard-code anyone's station.

## Design choices

- **GET/HEAD against public services.** Every other method passes through a guard (`satnogs_smoke/write_guard.py`) that refuses it unless `SATNOGS_ALLOW_WRITE_PROBES=1` is set and the target host is loopback or listed in `SATNOGS_WRITE_PROBE_HOSTS`. Any `satnogs.org` host, including the production Network, is always refused, and unclear URLs are refused. CI sets `SATNOGS_ALLOW_WRITE_PROBES=0`.
- **Polite.** One shared session, a descriptive `User-Agent`, a timeout on every call, and no scheduled polling.
- **One retry for gateway errors only** (`502`/`503`/`504`), so a transient CDN error is not reported as a product failure. Any other status fails immediately.
- **Offline unit tests** for the helpers (TLE checksum, `Link` header parsing), so CI has a deterministic part that does not depend on the internet.
- **Configurable target** through environment variables, so the same suite can run against a staging instance.

## Running

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python -m pytest                    # unit + live, excluding slow
python -m pytest -m "not live"      # offline unit tests only
python -m pytest -m slow            # the large-response behaviour check
```

| Variable | Default |
|---|---|
| `SATNOGS_NETWORK_URL` | `https://network.satnogs.org` |
| `SATNOGS_DB_URL` | `https://db.satnogs.org` |
| `SATNOGS_TIMEOUT_S` | `60` |
| `SATNOGS_SLOW_RESPONSE_S` | `10` (budget for the list response) |
| `SATNOGS_ALLOW_WRITE_PROBES` | unset (write-method probes disabled; only the exact value `1` enables them) |
| `SATNOGS_WRITE_PROBE_HOSTS` | unset (comma-separated non-production host names that may receive write probes) |

### Write-method probes

The three auth checks send `DELETE`, `PATCH` and `POST`, so they are off by default and never run against public SatNOGS services. To run them against a disposable instance you control:

```bash
SATNOGS_ALLOW_WRITE_PROBES=1 SATNOGS_NETWORK_URL=http://127.0.0.1:8000 python -m pytest -m negative
```

The guard in [`satnogs_smoke/write_guard.py`](satnogs_smoke/write_guard.py) parses the URL and checks the normalised host name; it does not compare URL strings. Any `satnogs.org` host is refused, even if listed. Unclear or ambiguous URLs, unknown hosts and hosts that resolve to public addresses are refused. The HTTP client applies the guard to every request before sending it, and sends write requests without following redirects or using proxy settings from the environment. CI sets `SATNOGS_ALLOW_WRITE_PROBES=0` for every trigger.

A host name that passes these checks is not proof that the destination is safe. The guard cannot detect a DNS answer that changes after the check, or a local port forward, tunnel or reverse proxy that relays a loopback or private address to a production service. Enable write probes only for an instance you have confirmed is disposable.

CI ([.github/workflows/smoke.yml](.github/workflows/smoke.yml)) runs unit tests first, then the live suite on every push, pull request and manual run, and stores a JUnit report. There is no scheduled run.

## Limitations

- Smoke level only: it proves the main paths respond correctly, not that every field is correct.
- Authenticated paths (scheduling, vetting, station edits with a token) are not covered; they need a dedicated test account and secret handling.
- Results depend on live data. A check that needs data which is not on the first page (for example no future observation) is skipped, not failed.

## Status

Version 0.1, written November 2026. On 19 November 2026 the default live run passed against the public APIs (15 passed; the 3 write-method probes are skipped by default), and the offline unit tests passed.

## License

[GNU Affero General Public License v3.0](LICENSE), the same licence as the SatNOGS Client. SatNOGS is a project of Libre Space Foundation; this repository is independent and not endorsed by it.
