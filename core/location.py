"""location.py — the Location Engine: combines boundary lookups (zone/ward)
with reverse geocoding (city/state/locality/postcode) into one record.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.boundaries import resolve_ward, resolve_zone
from core.geocoding import UNKNOWN, GeocodeCache, GeocodeResult, ReverseGeocoder


@dataclass(frozen=True)
class LocationInfo:
    city: str
    state: str
    zone: str
    ward: str
    locality: str
    postcode: str
    formatted_address: str
    geocode_success: bool


class LocationEngine:
    """Resolves ward/zone (always, local point-in-polygon lookup) and,
    unless ``geocode_enabled=False``, city/state/locality/postcode via
    reverse geocoding. Disabling geocoding is a genuine no-network mode
    (not just a different cache) — for offline runs / avoiding Nominatim
    rate limits during bulk demo-data generation.
    """

    def __init__(self, geocoder: ReverseGeocoder | None = None, cache: GeocodeCache | None = None, geocode_enabled: bool = True):
        self.geocode_enabled = geocode_enabled
        self.geocoder = None if not geocode_enabled else (geocoder or ReverseGeocoder(cache=cache))

    def resolve(self, latitude: float, longitude: float) -> LocationInfo:
        ward = resolve_ward(latitude, longitude)
        zone = resolve_zone(latitude, longitude)

        if self.geocoder is None:
            geocode = GeocodeResult(city=UNKNOWN, state=UNKNOWN, postcode=UNKNOWN, locality=UNKNOWN, formatted_address=UNKNOWN, success=False, provider="disabled")
        else:
            geocode = self.geocoder.reverse(latitude, longitude)

        return LocationInfo(
            city=geocode.city,
            state=geocode.state,
            zone=zone,
            ward=ward,
            locality=geocode.locality,
            postcode=geocode.postcode,
            formatted_address=geocode.formatted_address,
            geocode_success=geocode.success,
        )
