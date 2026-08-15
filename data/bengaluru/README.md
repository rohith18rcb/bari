# Bengaluru GIS boundary data

## `wards.geojson` (included, real data)

- **Source:** [datameet/Municipal_Spatial_Data](https://github.com/datameet/Municipal_Spatial_Data/tree/master/Bangalore) — `BBMP.geojson`
- **Upstream origin:** scraped from KSRSAC (Karnataka State Remote Sensing Applications Centre) official GIS portal
- **License:** Creative Commons Attribution-ShareAlike 2.5 India (CC BY-SA 2.5 IN)
- **Content:** 243 BBMP ward polygons (2022 delimitation), with `KGISWardName` / `KGISWardNo` properties
- **Downloaded:** automatically by this project — see `core/boundaries.py`

This is real, authoritative-derived ward geometry — not fabricated. Point-in-polygon
lookups against this file are used to resolve a GPS coordinate to a BBMP ward name.

## `zones.geojson` (not included — bring your own)

BBMP's 8 administrative zones (Bommanahalli, Dasarahalli, East, West, South,
RR Nagar, Mahadevapura, Yelahanka) do not have a readily available, clearly
licensed public GeoJSON at the time this project was built. Rather than
fabricate zone boundaries, **BARI ships without one** and zone will resolve
to `"Unknown"` unless you supply this file yourself.

To enable zone resolution:

1. Obtain a legitimate BBMP zone-boundary GeoJSON (e.g. exported from a GIS
   tool, an official portal, or by dissolving ward polygons using an
   authoritative ward→zone mapping table).
2. Save it as `data/bengaluru/zones.geojson`.
3. Ensure each feature has a `name` (or `zone`/`ZONE_NAME`) property — see
   `core/boundaries.py::_extract_name` for the accepted property keys.
4. Restart the pipeline / dashboard — `core/boundaries.py` loads boundary
   files lazily and will pick it up automatically.

If the file is absent, the system does **not** crash or invent a value —
`zone` is simply reported as `"Unknown"`, and location resolution otherwise
proceeds normally using ward lookup + reverse geocoding (city/locality/postcode).
