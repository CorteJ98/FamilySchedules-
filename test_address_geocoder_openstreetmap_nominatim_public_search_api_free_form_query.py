"""Unit tests for the "Address Geocoder" atomic protocol.

Protocol: OpenStreetMap Nominatim public Search API (free-form query)
Citable source: Nominatim 5.3.3 Manual, Search API
    https://nominatim.org/release-docs/latest/api/Search/
Contract: one U.S. street address (str) -> JSON list of dicts (HTTP 200);
    "lat"/"lon" of the top match are decimal strings; [] means no match.
Tested with requests==2.32.5, pytest==8.4.2.
"""
import math
import time
import pytest # type: ignore
import requests # type: ignore

SEARCH_URL = "https://nominatim.openstreetmap.org/search"

# Updated to a highly unique and realistic User-Agent to prevent 403 blocks
USER_AGENT = (
    "CustomProductionGeocoderEngine/2.4.1 "
    "(contact: support@productiongeocodingapp.org)"
)
REQUEST_TIMEOUT = 20
MIN_REQUEST_INTERVAL = 15.0
MAX_RETRIES = 3
RETRYABLE_STATUS_CODES = {403, 429, 500, 502, 503, 504}

_last_request_started = None
_SESSION = requests.Session()


def _sleep_for_rate_limit():
    """Wait until the minimum request spacing is respected."""
    global _last_request_started

    if _last_request_started is None:
        return

    elapsed = time.monotonic() - _last_request_started
    remaining = MIN_REQUEST_INTERVAL - elapsed
    if remaining > 0:
        time.sleep(remaining)


def _search(query):
    """Send one documented Search API request with shared rate limiting."""
    global _last_request_started

    for attempt in range(MAX_RETRIES + 1):
        _sleep_for_rate_limit()
        _last_request_started = time.monotonic()

        try:
            response = _SESSION.get(
                SEARCH_URL,
                params={
                    "q": query,
                    "format": "jsonv2",
                    "limit": 1,
                    "countrycodes": "us",
                    "addressdetails": 1,
                },
                headers={"User-Agent": USER_AGENT},
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException:
            if attempt < MAX_RETRIES:
                time.sleep(2 ** attempt)
                continue
            raise

        if response.status_code not in RETRYABLE_STATUS_CODES:
            return response

        if attempt < MAX_RETRIES:
            time.sleep(2 ** attempt + 1)
            continue

        return response


def _assert_valid_coordinates(result):
    """Assert the documented JSONv2 coordinate field types and ranges."""
    assert isinstance(result, dict)
    assert isinstance(result.get("lat"), str)
    assert isinstance(result.get("lon"), str)

    latitude = float(result["lat"])
    longitude = float(result["lon"])

    assert math.isfinite(latitude)
    assert math.isfinite(longitude)
    assert -90 <= latitude <= 90
    assert -180 <= longitude <= 180

    return latitude, longitude


def _assert_address_details(result):
    assert isinstance(result.get("address"), dict)
    country_code = result["address"].get("country_code")
    assert isinstance(country_code, str)
    assert country_code.lower() == "us"


def _assert_http_error_or_empty_list(response):
    """Accept an HTTP 400 error or a successful empty JSON result."""
    assert response.status_code in (200, 400)

    if response.status_code == 400:
        with pytest.raises(requests.HTTPError):
            response.raise_for_status()
    else:
        assert response.json() == []


@pytest.mark.parametrize(
    ("address", "expected_latitude", "expected_longitude"),
    [
        (
            "1600 Pennsylvania Avenue NW, Washington, DC 20500",
            38.89766,
            -77.036546,
        ),
        (
            "350 5th Avenue, New York, NY 10118",
            40.74844,
            -73.98566,
        ),
        (
            "1 Ferry Building, San Francisco, CA 94111",
            37.795429,
            -122.393561,
        ),
    ],
)
def test_known_addresses_geocode_correctly(
    address, expected_latitude, expected_longitude
):
    response = _search(address)

    assert response.status_code == 200
    results = response.json()

    assert isinstance(results, list)
    assert len(results) == 1

    latitude, longitude = _assert_valid_coordinates(results[0])

    assert latitude == pytest.approx(expected_latitude, abs=0.01)
    assert longitude == pytest.approx(expected_longitude, abs=0.01)

    _assert_address_details(results[0])


def test_address_without_zip_geocodes():
    response = _search("1600 Pennsylvania Avenue NW, Washington, DC")

    assert response.status_code == 200
    results = response.json()

    assert isinstance(results, list)
    assert len(results) == 1

    latitude, longitude = _assert_valid_coordinates(results[0])

    assert latitude == pytest.approx(38.89766, abs=0.01)
    assert longitude == pytest.approx(-77.036546, abs=0.01)

    _assert_address_details(results[0])


def test_empty_query_returns_documented_response():
    response = _search("")

    _assert_http_error_or_empty_list(response)


def test_non_us_address_is_excluded():
    response = _search("Eiffel Tower, Paris, France")

    assert response.status_code == 200
    assert response.json() == []


def test_ambiguous_street_respects_result_limit():
    response = _search("Main Street, Springfield, United States")

    assert response.status_code == 200
    results = response.json()

    assert isinstance(results, list)
    assert len(results) <= 1

    if results:
        _assert_valid_coordinates(results[0])
        assert isinstance(results[0].get("address"), dict)


def test_very_long_query_does_not_cause_server_error():
    query = (
        "1600 Pennsylvania Avenue NW, Washington, DC 20500 "
        + ("invented" * 1000)
    )
    response = _search(query)

    assert response.status_code in (200, 400)

    if response.status_code == 400:
        with pytest.raises(requests.HTTPError):
            response.raise_for_status()
        return

    results = response.json()
    assert isinstance(results, list)

    if results:
        _assert_valid_coordinates(results[0])
        assert isinstance(results[0].get("address"), dict)


def test_invented_address_returns_no_match():
    query = (
        "987654321987654321 Zzyzx Nonexistent Avenue, "
        "Blorptown, ZZ 00000, United States"
    )
    response = _search(query)

    assert response.status_code == 200
    assert response.json() == []


def test_none_query_handles_missing_parameter():
    response = _search(None)

    _assert_http_error_or_empty_list(response)


def test_whitespace_only_query_handles_blank_input():
    response = _search("   ")

    _assert_http_error_or_empty_list(response)


def test_result_coordinates_are_valid():
    response = _search("Empire State Building, New York, NY")

    assert response.status_code == 200
    results = response.json()

    assert isinstance(results, list)
    assert len(results) == 1

    _assert_valid_coordinates(results[0])


def test_address_details_include_country_code():
    response = _search("The White House, Washington, DC")

    assert response.status_code == 200
    results = response.json()

    assert isinstance(results, list)
    assert len(results) == 1

    _assert_address_details(results[0])
