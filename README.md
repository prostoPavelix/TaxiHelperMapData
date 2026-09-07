# TaxiHelperMapData

Public OpenStreetMap-derived offline data bundles for Taxi Helper.

The repository contains only reproducible public geodata tooling. It does **not** contain driver
history, sectors, manual address rules, application source code or any other private Taxi Helper
data. GitHub Actions publishes a stable `offline-map-latest` release containing:

- `lutsk_area.map` — Mapsforge visual map;
- `lutsk_addresses.tsv` — normalized addresses, POIs, aliases and coordinates;
- `lutsk_streets.tsv` — sampled street geometry;
- `visual_roads.bin` — lightweight main-road geometry;
- `road_graph.bin`, `road_anchor_index.bin` and `road_manifest.json` — ready V3 road data;
- `map-manifest.json` — version, sizes, SHA-256 hashes and change statistics.

Source: OpenStreetMap Volyn extract. Generated monthly and on manual workflow dispatch.

The seven files are built from one snapshot. Publication is blocked by address/street coverage
regressions, missing critical Lutsk street families, topology failures or mixed hashes. The phone
activates only the whole verified format-4 bundle and retains the previous complete version.
