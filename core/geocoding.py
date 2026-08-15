"""
geocoding.py — replaceable reverse-geocoding service.

Wraps a Nominatim (OpenStreetMap) reverse-geocoder with caching, rate
limiting, retries and a graceful fallback so that GPS coordinates are always
saved even when reverse geocoding fails or is unavailable (offline demo,
network hiccup, provider outage). Only called for *confirmed* pothole
events — never per-frame — to respect Nominatim's usage policy.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional, Protocol

from geopy.exc import GeocoderServiceError, GeocoderTimedOut
from geopy.extra.rate_limiter import RateLimiter
from geopy.geocoders import Nominatim

from core.config import settings

logger = logging.getLogger("bari.geocoding")

UNKNOWN = "Unknown"


@dataclass(frozen=True)
class GeocodeResult:
    city: str
    state: str
    postcode: str
    locality: str
    formatted_address: str
    success: bool
    provider: str


def _unknown_result(provider: str) -> GeocodeResult:
    return GeocodeResult(
        city=UNKNOWN, state=UNKNOWN, postcode=UNKNOWN, locality=UNKNOWN,
        formatted_address=UNKNOWN, success=False, provider=provider,
    )


class GeocodeCache(Protocol):
    def get(self, key: str) -> Optional[GeocodeResult]: ...
    def set(self, key: str, value: GeocodeResult) -> None: ...


class InMemoryGeocodeCache:
    """Rounds coordinates to ~11m precision (4 decimals) to bucket nearby lookups."""

    def __init__(self) -> None:
        self._store: dict[str, GeocodeResult] = {}

    def get(self, key: str) -> Optional[GeocodeResult]:
        return self._store.get(key)

    def set(self, key: str, value: GeocodeResult) -> None:
        self._store[key] = value


def cache_key(lat: float, lon: float, precision: int = 4) -> str:
    return f"{round(lat, precision)},{round(lon, precision)}"


class ReverseGeocoder:
    def __init__(
        self,
        provider: str = "nominatim",
        user_agent: Optional[str] = None,
        timeout: Optional[float] = None,
        min_interval_seconds: Optional[float] = None,
        max_retries: Optional[int] = None,
        cache: Optional[GeocodeCache] = None,
    ) -> None:
        self.provider = provider
        self.max_retries = max_retries if max_retries is not None else settings.geocoder_max_retries
        self.cache = cache or InMemoryGeocodeCache()

        if provider == "nominatim":
            geolocator = Nominatim(
                user_agent=user_agent or settings.geocoder_user_agent,
                timeout=timeout or settings.geocoder_timeout_seconds,
            )
            self._reverse = RateLimiter(
                geolocator.reverse,
                min_delay_seconds=min_interval_seconds if min_interval_seconds is not None else settings.geocoder_min_interval_seconds,
                max_retries=0,  # we handle retries ourselves for clearer logging
                swallow_exceptions=False,
            )
        else:
            raise ValueError(f"Unsupported geocoder provider: {provider}")

    def reverse(self, latitude: float, longitude: float) -> GeocodeResult:
        key = cache_key(latitude, longitude)
        cached = self.cache.get(key)
        if cached is not None:
            return cached

        result = self._reverse_with_retry(latitude, longitude)
        self.cache.set(key, result)
        return result

    def _reverse_with_retry(self, latitude: float, longitude: float) -> GeocodeResult:
        last_error: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                location = self._reverse((latitude, longitude), exactly_one=True, addressdetails=True, language="en")
                if location is None or "address" not in location.raw:
                    return _unknown_result(self.provider)
                return self._parse(location.raw["address"], location.address)
            except (GeocoderTimedOut, GeocoderServiceError) as e:
                last_error = e
                wait = 0.5 * (2 ** (attempt - 1))
                logger.warning("Reverse geocode attempt %d/%d failed (%s); retrying in %.1fs", attempt, self.max_retries, e, wait)
                time.sleep(wait)
            except Exception as e:  # noqa: BLE001 - geocoding must never crash the pipeline
                last_error = e
                logger.error("Reverse geocode failed unexpectedly: %s", e)
                break

        logger.warning("Reverse geocoding gave up after %d attempts (%s); location fields set to Unknown", self.max_retries, last_error)
        return _unknown_result(self.provider)

    @staticmethod
    def _parse(address: dict, formatted: str) -> GeocodeResult:
        city = (
            address.get("city") or address.get("town") or address.get("municipality")
            or address.get("county") or UNKNOWN
        )
        state = address.get("state", UNKNOWN)
        postcode = address.get("postcode", UNKNOWN)
        locality = (
            address.get("suburb") or address.get("neighbourhood") or address.get("locality")
            or address.get("road") or UNKNOWN
        )
        return GeocodeResult(
            city=city, state=state, postcode=postcode, locality=locality,
            formatted_address=formatted or UNKNOWN, success=True, provider="nominatim",
        )
