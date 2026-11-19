# SatNOGS API Smoke Tests

[![smoke](https://github.com/ShadiShadab/satnogs-api-smoke-tests/actions/workflows/smoke.yml/badge.svg)](https://github.com/ShadiShadab/satnogs-api-smoke-tests/actions/workflows/smoke.yml)

A small, **read-only** pytest suite that checks the public [SatNOGS](https://satnogs.org) Network and DB APIs still behave the way a ground station and its operator depend on.

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
| Auth (negative) | Unauthenticated `DELETE`/`PATCH` → `401` with `WWW-Authenticate: Token`; unauthenticated `POST` rejected | Write paths are protected |
| DB API | Satellite lookup by NORAD ID | Scheduling depends on it |
| | Transmitter filter by `satellite__norad_cat_id` respected; valid `status` and `alive` values | Wrong transmitter data means wrong frequencies |
| | TLE lines are well formed: length, line numbers, modulo-10 checksums, matching catalogue number | A corrupt TLE means a wrong pass prediction |
| | (slow, opt-in) Unsupported `?satellite=` filter is ignored: documents current behaviour, so a change is noticed | Recorded as a defect candidate during station QA |

Test data is discovered at run time (for example "the most recent observation vetted good"), so the suite does not depend on any one station, and it does not hard-code anyone's station.

## Design choices

- **Read-only and polite.** Only `GET`/`HEAD`, except the negative auth checks, which send no credentials and cannot change anything. One shared session, a descriptive `User-Agent`, a timeout on every call, and no scheduled polling.
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

CI ([.github/workflows/smoke.yml](.github/workflows/smoke.yml)) runs unit tests first, then the live suite on every push, pull request and manual run, and stores a JUnit report. There is no scheduled run.

## Limitations

- Smoke level only: it proves the main paths respond correctly, not that every field is correct.
- Authenticated paths (scheduling, vetting, station edits with a token) are not covered; they need a dedicated test account and secret handling.
- Results depend on live data. A check that needs data which is not on the first page (for example no future observation) is skipped, not failed.

## Status

Version 0.1, written November 2026. All 25 default tests and the slow check pass against the live APIs at the time of writing.

## License

[GNU Affero General Public License v3.0](LICENSE), the same licence as the SatNOGS Client. SatNOGS is a project of Libre Space Foundation; this repository is independent and not endorsed by it.
