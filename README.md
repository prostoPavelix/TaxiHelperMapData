# TaxiHelperMapData

Public OpenStreetMap-derived offline data bundles for Taxi Helper.

The repository contains only reproducible public geodata tooling. It does **not** contain driver
history, sectors, manual address rules, application source code or any other private Taxi Helper
data. GitHub Actions publishes a stable `offline-map-latest` release containing:

- `lutsk_area.map` — Mapsforge visual map;
- `lutsk_addresses.tsv` — normalized addresses, POIs, aliases and coordinates;
- `lutsk_streets.tsv` — sampled street geometry;
- `map-manifest.json` — version, sizes, SHA-256 hashes and change statistics.

Source: OpenStreetMap Volyn extract. Generated monthly and on manual workflow dispatch.
