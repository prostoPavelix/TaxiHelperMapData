#!/usr/bin/env python3
"""Build a deterministic format-3 release directory for Taxi Helper offline geodata."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

FILES = (
    "lutsk_area.map", "lutsk_addresses.tsv", "lutsk_streets.tsv", "visual_roads.bin",
    "road_graph.bin", "road_anchor_index.bin", "road_manifest.json",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_release(
    sources: dict[str, Path], visual_manifest: Path, road_manifest: Path, output: Path,
    version: str, generated_at: str, statistics: dict | None = None,
) -> dict:
    if not version.replace("-", "").isdigit() or len(version) != 15:
        raise ValueError("version must have YYYYMMDD-HHMMSS form")
    visual = json.loads(visual_manifest.read_text(encoding="utf-8"))
    osm_sha = visual.get("osm_snapshot_sha256", "")
    if len(osm_sha) != 64 or any(char not in "0123456789abcdefABCDEF" for char in osm_sha):
        raise ValueError("visual manifest has no valid OSM SHA-256")
    expected_visual = visual.get("artifact", {})
    if sha256(sources["visual_roads.bin"]) != expected_visual.get("sha256"):
        raise ValueError("visual binary does not match its provenance manifest")
    road = json.loads(road_manifest.read_text(encoding="utf-8"))
    if road.get("osm_snapshot_sha256", "").lower() != osm_sha.lower():
        raise ValueError("road and visual artifacts come from different OSM snapshots")
    for name in ("road_graph.bin", "road_anchor_index.bin"):
        expected = road.get("artifacts", {}).get(name, {})
        if sha256(sources[name]) != expected.get("sha256") or \
                sources[name].stat().st_size != expected.get("bytes"):
            raise ValueError(f"{name} does not match its provenance manifest")
    sources = dict(sources)
    sources["road_manifest.json"] = road_manifest

    output.mkdir(parents=True, exist_ok=True)
    specs: dict[str, dict[str, int | str]] = {}
    for name in FILES:
        source = sources[name]
        if not source.is_file():
            raise FileNotFoundError(source)
        destination = output / name
        if source.resolve() != destination.resolve():
            shutil.copyfile(source, destination)
        specs[name] = {"size": destination.stat().st_size, "sha256": sha256(destination)}
    manifest = {
        "format": 4,
        "version": version,
        "generatedAt": generated_at,
        "osmSnapshotSha256": osm_sha.lower(),
        "files": specs,
        "statistics": statistics or {},
    }
    encoded = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    pending = output / "map-manifest.json.pending"
    pending.write_text(encoded, encoding="utf-8", newline="\n")
    pending.replace(output / "map-manifest.json")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--map", type=Path, required=True)
    parser.add_argument("--addresses", type=Path, required=True)
    parser.add_argument("--streets", type=Path, required=True)
    parser.add_argument("--visual", type=Path, required=True)
    parser.add_argument("--visual-manifest", type=Path, required=True)
    parser.add_argument("--road-graph", type=Path, required=True)
    parser.add_argument("--road-anchors", type=Path, required=True)
    parser.add_argument("--road-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--statistics-json", type=Path)
    args = parser.parse_args()
    build_release(
        {
            "lutsk_area.map": args.map,
            "lutsk_addresses.tsv": args.addresses,
            "lutsk_streets.tsv": args.streets,
            "visual_roads.bin": args.visual,
            "road_graph.bin": args.road_graph,
            "road_anchor_index.bin": args.road_anchors,
        },
        args.visual_manifest, args.road_manifest, args.output, args.version, args.generated_at,
        json.loads(args.statistics_json.read_text(encoding="utf-8"))
        if args.statistics_json else None,
    )


if __name__ == "__main__":
    main()
