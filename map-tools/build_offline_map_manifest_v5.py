#!/usr/bin/env python3
"""Build a provenance-bound format-5 map and visual release."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from build_rich_context_manifest import verify as verify_rich

FILES = (
    "lutsk_area.map", "lutsk_addresses.tsv", "lutsk_streets.tsv", "visual_roads.bin",
    "road_graph.bin", "road_anchor_index.bin", "road_manifest.json",
    "visual_minor_roads.bin", "minor_manifest.json", "rich_context.bin", "rich_context_manifest.json",
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
    minor_manifest: Path | None = None, rich_manifest: Path | None = None,
    osm_source: Path | None = None,
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
    if minor_manifest is None or rich_manifest is None or osm_source is None:
        raise ValueError("format 5 needs minor, rich, and OSM provenance")
    if sha256(osm_source).lower() != osm_sha.lower():
        raise ValueError("OSM source differs from the visual manifest")
    minor = json.loads(minor_manifest.read_text(encoding="utf-8"))
    if minor.get("osm_snapshot_sha256", "").lower() != osm_sha.lower():
        raise ValueError("minor roads come from another OSM snapshot")
    if minor.get("artifact", {}).get("sha256") != sha256(sources["visual_minor_roads.bin"]):
        raise ValueError("minor binary does not match its manifest")
    if minor.get("artifact", {}).get("bytes") != sources["visual_minor_roads.bin"].stat().st_size:
        raise ValueError("minor binary size does not match its manifest")
    verify_rich(sources["rich_context.bin"], sources["lutsk_area.map"], osm_source, rich_manifest)
    sources = dict(sources)
    sources["road_manifest.json"] = road_manifest
    sources["minor_manifest.json"] = minor_manifest
    sources["rich_context_manifest.json"] = rich_manifest

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
        "format": 5,
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
    parser.add_argument("--minor", type=Path, required=True)
    parser.add_argument("--minor-manifest", type=Path, required=True)
    parser.add_argument("--rich", type=Path, required=True)
    parser.add_argument("--rich-manifest", type=Path, required=True)
    parser.add_argument("--osm", type=Path, required=True)
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
            "visual_minor_roads.bin": args.minor,
            "rich_context.bin": args.rich,
        },
        args.visual_manifest, args.road_manifest, args.output, args.version, args.generated_at,
        json.loads(args.statistics_json.read_text(encoding="utf-8"))
        if args.statistics_json else None,
        args.minor_manifest, args.rich_manifest, args.osm,
    )


if __name__ == "__main__":
    main()
