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

Current public release: format 5, `20260928-222232`, built and published by
[GitHub Actions run 36491715838](https://github.com/prostoPavelix/TaxiHelperMapData/actions/runs/36491715838)
from OSM SHA-256 `fda3c4068e87965ec21a209cdab153abc70f95e5db76fd5af0a94a3cdeb2fcc7`.
The compatible Android APK was installed on the working phone first. The owner deferred
downloading/activating this new map on the phone to a later test. The previous verified release
`20260907-215810` was downloaded and activated on a phone; see
[ARCHITECTURE_AND_RELEASE_UK.md](ARCHITECTURE_AND_RELEASE_UK.md).

The format-5 eleven-file bundle is built from one snapshot. Publication is blocked by address/street coverage
regressions, missing critical Lutsk street families, topology failures or mixed hashes. The phone
activates only the whole verified bundle and retains the previous complete version. The
`codex/visual-map-bundle` branch was first built and verified twice without publishing. It was
then fast-forwarded to `main` after the matching Android APK was installed. The phone download
and activation check remains pending.

The public, standard-library-only builders and fixtures are vendored in `map-tools/`. The
workflow therefore requires no access token for the private Android source repository and never
receives driver history, sector geometry, learned addresses or manual corrections.

Important: map, address/street indexes, main/minor roads, rich context and routing graph must
always be published from the same OSM snapshot. Never update only one file in
`offline-map-latest`. The rich-context Java filter and lightweight visual Python filter are
vendored unchanged from TaxiHelper `tools/`; keep their source and this copy synchronized when
changing map style. The workflow builds all payloads before uploading them and uploads the
activation manifest last. See [VISUAL_BUNDLE_V5.md](VISUAL_BUNDLE_V5.md) for rollout and rollback.
