# Coherent visual map release (format 5)

The prior format-4 release contains a Mapsforge map, address/street indexes, main-road overlay
and road graph. The Android APK supplied minor roads and rich coloured/labelled context separately.
If the OSM release changed, the rich context disappeared by provenance check, while minor roads
could still show stale APK geometry. Format 5 fixes this by adding four release files:

| Payload | Origin and verification |
| --- | --- |
| `visual_minor_roads.bin` | Same bounded OSM XML as main roads; SHA/size and `minor_manifest.json` |
| `minor_manifest.json` | OSM SHA, builder profile and minor binary SHA/size |
| `rich_context.bin` | Selective `ExportRichMap.java` extraction from this release's `lutsk_area.map`; THRICH01 v3 structural check |
| `rich_context_manifest.json` | Rich binary SHA/size, exact Mapsforge map SHA and OSM XML SHA |

The original seven files remain required. `build_offline_map_manifest_v5.py` rejects a differing
OSM SHA in the visual, minor or road manifests, mismatched nested binary specs, and a rich source
map hash different from the release map. `verify_offline_map_release_v5.py` repeats the relevant
checks on the assembled release and retains address regression and road topology gates. GitHub
Actions assembles from one downloaded PBF, verifies, uploads payloads first, and uploads
`map-manifest.json` last. The Android updater checks SHA/size/format for every file before atomic
activation with `.previous` rollback. It uses format-5 visual layers only from the activated bundle;
missing or damaged supplemental layers cannot cause an APK/OSM mixture.

The visual filters keep the accepted selective Lutsk rendering: all road classes needed by the
light map, a small subset of colour/objects, rail and curated labels. This change does not tune
display zoom, label selection, GPS cells, forecast, routing or learning. The public repository
contains only OSM-derived tooling and output, no private driving history or sectors.

Rollout order: (1) build and inspect the branch CI without publishing; (2) merge/install the
matching TaxiHelper Android code and test on the phone; (3) only then merge this map-data branch
or dispatch the workflow on `main`; (4) check the published manifest and phone download/activation.
The old Android updater supports formats through 4 and would reject 5, hence early publication
would suspend map updates on that build. For rollback, republish the prior verified format-4 bundle
and activation manifest last, or retain the current release until phone validation. The app keeps
the previously activated bundle if download or validation fails.
