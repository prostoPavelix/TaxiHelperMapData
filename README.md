# TaxiHelperMapData

Public OpenStreetMap-derived offline data bundles for Taxi Helper.

The repository contains only reproducible public geodata tooling. It does **not** contain driver
history, sectors, manual address rules, application source code or any other private Taxi Helper
data. GitHub Actions publishes a stable `offline-map-latest` release containing:

- `lutsk_area.map` — Mapsforge visual map;
- `lutsk_addresses.tsv` — normalized addresses, POIs, aliases and coordinates;
- `lutsk_streets.tsv` — sampled street geometry;
- `visual_roads.bin` — lightweight main-road geometry;
- `visual_minor_roads.bin`, `minor_manifest.json` — lightweight local roads and source proof;
- `rich_context.bin`, `rich_context_manifest.json` — selected Lutsk colour, rail and street/POI labels with source-map proof;
- `road_graph.bin`, `road_anchor_index.bin` and `road_manifest.json` — ready V3 road data;
- `map-manifest.json` — version, sizes, SHA-256 hashes and change statistics.

Source: OpenStreetMap Volyn extract. Generated monthly and on manual workflow dispatch.

Current verified production release: `20260907-215810`. It was built by GitHub Actions run
`34164856459` from OSM SHA-256
`21130f856f1a8c7a76ec9d850277ec5016bab7c93315d81d58fe688a8987e7e7` and was successfully
downloaded, atomically activated and used to rebuild Taxi Helper V3 generation 11 on a real
phone. See [ARCHITECTURE_AND_RELEASE_UK.md](ARCHITECTURE_AND_RELEASE_UK.md).

The format-5 eleven-file bundle is built from one snapshot. Publication is blocked by address/street coverage
regressions, missing critical Lutsk street families, topology failures or mixed hashes. The phone
activates only the whole verified bundle and retains the previous complete version. The current
production release remains format 4 until the matching Android client has been installed and
checked on the phone. The `codex/visual-map-bundle` branch runs the entire GitHub build and
verification without publishing the release. Merging that branch to `main` automatically publishes
format 5, so merge only after the matching Android version is on the phone.

The public, standard-library-only builders and fixtures are vendored in `map-tools/`. The
workflow therefore requires no access token for the private Android source repository and never
receives driver history, sector geometry, learned addresses or manual corrections.

Important: map, address/street indexes, main/minor roads, rich context and routing graph must
always be published from the same OSM snapshot. Never update only one file in
`offline-map-latest`. The rich-context Java filter and lightweight visual Python filter are
vendored unchanged from TaxiHelper `tools/`; keep their source and this copy synchronized when
changing map style. The workflow builds all payloads before uploading them and uploads the
activation manifest last. See [VISUAL_BUNDLE_V5.md](VISUAL_BUNDLE_V5.md) for rollout and rollback.
