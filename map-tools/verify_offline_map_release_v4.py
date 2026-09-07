#!/usr/bin/env python3
"""Fail-closed verifier for an automatically generated Taxi Helper map/V3 bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

REQUIRED = (
    "lutsk_area.map", "lutsk_addresses.tsv", "lutsk_streets.tsv", "visual_roads.bin",
    "road_graph.bin", "road_anchor_index.bin", "road_manifest.json",
)
CRITICAL_ADDRESS_TOKENS = (
    "ветеранів", "степана бандери", "молоді", "волі", "дубнівська",
    "соборності", "чорновола",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rows(path: Path) -> list[str]:
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def verify(root: Path, previous: Path | None = None) -> dict[str, object]:
    failures: list[str] = []
    manifest = json.loads((root / "map-manifest.json").read_text(encoding="utf-8"))
    if manifest.get("format") != 4:
        failures.append("MANIFEST_FORMAT")
    declared = manifest.get("files", {})
    for name in REQUIRED:
        path = root / name
        spec = declared.get(name, {})
        if not path.is_file():
            failures.append(f"MISSING:{name}")
        elif path.stat().st_size != spec.get("size") or sha256(path) != spec.get("sha256"):
            failures.append(f"INTEGRITY:{name}")

    road = json.loads((root / "road_manifest.json").read_text(encoding="utf-8"))
    source_hash = str(manifest.get("osmSnapshotSha256", "")).lower()
    if len(source_hash) != 64 or road.get("osm_snapshot_sha256", "").lower() != source_hash:
        failures.append("MIXED_OSM_SNAPSHOT")
    if road.get("routing_profile_version") != "passenger-car-static-v1":
        failures.append("ROUTING_PROFILE")
    if road.get("grid_spec_version") != "v2-local-metric-350m-v1":
        failures.append("GRID_SPEC")
    capabilities = road.get("capabilities", {})
    for name in ("directed", "oneway", "access_filter", "multiple_local_components_per_350m_cell"):
        if capabilities.get(name) is not True:
            failures.append(f"ROAD_CAPABILITY:{name}")

    address_rows = rows(root / "lutsk_addresses.tsv")
    street_rows = rows(root / "lutsk_streets.tsv")
    address_text = "\n".join(line.casefold() for line in address_rows)
    for token in CRITICAL_ADDRESS_TOKENS:
        if token not in address_text:
            failures.append(f"ADDRESS_REGRESSION:{token}")
    if previous and (previous / "lutsk_addresses.tsv").is_file():
        old_addresses = rows(previous / "lutsk_addresses.tsv")
        old_streets = rows(previous / "lutsk_streets.tsv")
        if len(address_rows) < len(old_addresses) * 0.95:
            failures.append("ADDRESS_COUNT_DROP_GT_5_PERCENT")
        if len(street_rows) < len(old_streets) * 0.90:
            failures.append("STREET_COUNT_DROP_GT_10_PERCENT")

    graph = road.get("graph", {})
    anchors = road.get("anchor_index", {})
    if graph.get("graph_nodes", 0) < 10_000 or graph.get("directed_edges", 0) < 20_000:
        failures.append("ROAD_COVERAGE_TOO_SMALL")
    if anchors.get("anchors", 0) < 1_000 or anchors.get("cells_with_multiple_local_components", 0) < 1:
        failures.append("ANCHOR_COVERAGE_TOO_SMALL")
    return {
        "status": "PASSED" if not failures else "FAILED",
        "failures": failures,
        "address_rows": len(address_rows),
        "street_rows": len(street_rows),
        "osm_snapshot_sha256": source_hash,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = verify(args.bundle, args.previous)
    encoded = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    raise SystemExit(0 if result["status"] == "PASSED" else 1)


if __name__ == "__main__":
    main()
