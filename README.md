# YOUR-REPO

This repository holds unit tests for the **Address Geocoder** atomic protocol used in my final project, *Fitting Physical Activities into Family Schedules*. The geocoder turns a family's U.S. street address into latitude and longitude, which later steps use to find nearby parks and playgrounds and estimate travel times. The protocol is the public [OpenStreetMap Nominatim Search API](https://nominatim.org/release-docs/latest/api/Search/) (version 5.3.3 manual), which is the citable source. The tests call it exactly the way the workflow's glue code does.

## Contract

| | Type | Description |
|---|---|---|
| **Input** | `str` | One U.S. street address, e.g. `"55 W 125th St, New York, NY 10027"` |
| **Output** | `list` of `dict` (JSON, HTTP 200) | Top match with `lat` and `lon` as decimal strings; an empty list `[]` means no match |

Request configuration: `GET https://nominatim.openstreetmap.org/search` with `q=<address>`, `format=jsonv2`, `limit=1`, `countrycodes=us`, `addressdetails=1`, an identifying `User-Agent`, a 20-second timeout, and spacing between requests to respect the usage policy. No API key is needed.

## Tested versions

- requests 2.32.5
- pytest 8.4.2

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Running the tests

```bash
pytest -v
```

Expected result: **13 passed**. The tests wait 15 seconds between requests, so the run takes a few minutes.

## What the tests cover

- **Typical inputs:** well-known addresses (White House, Empire State Building, Ferry Building) return coordinates within 0.01 degrees of reference values, valid coordinate ranges, and a U.S. country code.
- **Edge cases:** address without a ZIP code, ambiguous street names respect `limit=1`, non-U.S. addresses are excluded, a very long query does not cause a server error, and an invented address returns an empty list.
- **Invalid inputs:** empty, whitespace-only, and `None` queries return an HTTP 400 error or an empty list, never nonsense.

## Known limitations

- The tests call the live public Nominatim server, which is shared by many users. They can fail from rate limiting or temporary outages, not just from real bugs.
- Reference coordinates are approximate.
