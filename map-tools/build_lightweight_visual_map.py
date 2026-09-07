#!/usr/bin/env python3
"""Build and verify Taxi Helper's compact, render-only main-road bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


MAGIC = b"THLROAD1"
FORMAT_VERSION = 1
BUILDER_VERSION = "taxi-helper-lightweight-visual-map-v1"
VISUAL_SPEC_VERSION = "lutsk-main-roads-no-labels-v1"
GRID_SPEC_VERSION = "v2-local-metric-350m-v1"
ORIGIN_LATITUDE = 50.7472
ORIGIN_LONGITUDE = 25.3254
METERS_PER_LATITUDE = 111_132.0
METERS_PER_LONGITUDE = 111_320.0 * math.cos(math.radians(ORIGIN_LATITUDE))

# The visual file intentionally excludes buildings, POIs, footways, service roads and names.
# Tertiary roads remain available only for the closest renderer scale because several important
# Lutsk connectors are classified as tertiary in OSM.
ROAD_CLASSES = {
    "motorway": 0,
    "motorway_link": 0,
    "trunk": 0,
    "trunk_link": 0,
    "primary": 1,
    "primary_link": 1,
    "secondary": 2,
    "secondary_link": 2,
    "tertiary": 3,
    "tertiary_link": 3,
}


@dataclass(frozen=True)
class Road:
    osm_id: int
    road_class: int
    points: tuple[tuple[int, int], ...]


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def project(latitude: float, longitude: float) -> tuple[int, int]:
    return (
        round((longitude - ORIGIN_LONGITUDE) * METERS_PER_LONGITUDE),
        round((latitude - ORIGIN_LATITUDE) * METERS_PER_LATITUDE),
    )


def parse_osm(path: Path) -> tuple[list[Road], dict[str, int], tuple[float, float, float, float]]:
    nodes: dict[int, tuple[float, float]] = {}
    raw_ways: list[tuple[int, int, tuple[int, ...]]] = []
    tag_counts = {tag: 0 for tag in ROAD_CLASSES}
    for _, element in ET.iterparse(path, events=("end",)):
        name = _local_name(element.tag)
        if name == "node":
            node_id = int(element.attrib["id"])
            latitude = float(element.attrib["lat"])
            longitude = float(element.attrib["lon"])
            nodes[node_id] = (latitude, longitude)
        elif name == "way":
            highway = None
            references: list[int] = []
            for child in element:
                child_name = _local_name(child.tag)
                if child_name == "nd":
                    references.append(int(child.attrib["ref"]))
                elif child_name == "tag" and child.attrib.get("k") == "highway":
                    highway = child.attrib.get("v")
            if highway in ROAD_CLASSES and len(references) >= 2:
                raw_ways.append((int(element.attrib["id"]), ROAD_CLASSES[highway], tuple(references)))
                tag_counts[highway] += 1
        # Children of a way must remain intact until the enclosing `way` END event. Clearing every
        # `nd`/`tag` here would erase its attributes before the parent can inspect them.
        if name in {"node", "way"}:
            element.clear()

    roads: list[Road] = []
    min_lat = min_lon = float("inf")
    max_lat = max_lon = float("-inf")
    for way_id, road_class, references in sorted(raw_ways):
        points: list[tuple[int, int]] = []
        for reference in references:
            coordinate = nodes.get(reference)
            if coordinate is None:
                continue
            latitude, longitude = coordinate
            min_lat = min(min_lat, latitude)
            min_lon = min(min_lon, longitude)
            max_lat = max(max_lat, latitude)
            max_lon = max(max_lon, longitude)
            point = project(*coordinate)
            if not points or points[-1] != point:
                points.append(point)
        if len(points) >= 2:
            if len(points) > 65_535:
                raise ValueError(f"OSM way {way_id} has too many points")
            roads.append(Road(way_id, road_class, tuple(points)))

    if not roads:
        raise ValueError("No supported main roads found in OSM source")
    return roads, tag_counts, (min_lat, min_lon, max_lat, max_lon)


def write_binary(path: Path, roads: list[Road]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    total_points = sum(len(road.points) for road in roads)
    with path.open("wb") as output:
        output.write(MAGIC)
        output.write(struct.pack(">I4dII", FORMAT_VERSION, ORIGIN_LATITUDE, ORIGIN_LONGITUDE,
                                 METERS_PER_LATITUDE, METERS_PER_LONGITUDE,
                                 len(roads), total_points))
        for road in roads:
            output.write(struct.pack(">BBH", road.road_class, 0, len(road.points)))
            for x_meters, y_meters in road.points:
                output.write(struct.pack(">ii", x_meters, y_meters))


def read_binary(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    header_size = len(MAGIC) + struct.calcsize(">I4dII")
    if len(data) < header_size or data[: len(MAGIC)] != MAGIC:
        raise ValueError("Invalid lightweight visual-map magic")
    offset = len(MAGIC)
    version, origin_lat, origin_lon, meters_lat, meters_lon, road_count, declared_points = \
        struct.unpack_from(">I4dII", data, offset)
    offset += struct.calcsize(">I4dII")
    if version != FORMAT_VERSION:
        raise ValueError(f"Unsupported lightweight visual-map format {version}")
    if not 1 <= road_count <= 10_000 or not 2 <= declared_points <= 500_000:
        raise ValueError("Implausible lightweight visual-map counts")
    class_counts = {str(index): 0 for index in range(4)}
    observed_points = 0
    for _ in range(road_count):
        if offset + 4 > len(data):
            raise ValueError("Truncated road header")
        road_class, reserved, point_count = struct.unpack_from(">BBH", data, offset)
        offset += 4
        if road_class not in range(4) or reserved != 0 or point_count < 2:
            raise ValueError("Invalid road entry")
        byte_count = point_count * 8
        if offset + byte_count > len(data):
            raise ValueError("Truncated road geometry")
        offset += byte_count
        observed_points += point_count
        class_counts[str(road_class)] += 1
    if offset != len(data) or observed_points != declared_points:
        raise ValueError("Lightweight visual-map length/count mismatch")
    return {
        "format_version": version,
        "origin": [origin_lat, origin_lon],
        "meters_per_degree": [meters_lat, meters_lon],
        "road_count": road_count,
        "point_count": observed_points,
        "class_counts": class_counts,
        "bytes": len(data),
    }


def build(source: Path, binary: Path, manifest: Path) -> dict[str, object]:
    roads, tag_counts, coverage = parse_osm(source)
    write_binary(binary, roads)
    decoded = read_binary(binary)
    source_hash = sha256(source)
    binary_hash = sha256(binary)
    result = {
        "format_version": FORMAT_VERSION,
        "builder_version": BUILDER_VERSION,
        "visual_spec_version": VISUAL_SPEC_VERSION,
        "grid_spec_version": GRID_SPEC_VERSION,
        "osm_snapshot_id": source_hash[:16],
        "osm_snapshot_sha256": source_hash,
        "coverage_bbox": list(coverage),
        "projection": {
            "name": "lutsk-local-equirectangular",
            "origin_latitude": ORIGIN_LATITUDE,
            "origin_longitude": ORIGIN_LONGITUDE,
            "meters_per_latitude_degree": METERS_PER_LATITUDE,
            "meters_per_longitude_degree": METERS_PER_LONGITUDE,
        },
        "content": {
            "road_count": decoded["road_count"],
            "point_count": decoded["point_count"],
            "class_counts": decoded["class_counts"],
            "included_highway_tags": sorted(tag for tag, count in tag_counts.items() if count),
            "excluded": ["buildings", "house_numbers", "poi", "street_labels", "minor_roads"],
        },
        "artifact": {
            "name": binary.name,
            "bytes": binary.stat().st_size,
            "sha256": binary_hash,
        },
        "license": {
            "source": "OpenStreetMap",
            "data_license": "ODbL-1.0",
            "attribution_required": True,
        },
    }
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                        encoding="utf-8")
    return result


def verify(binary: Path, manifest: Path) -> dict[str, object]:
    decoded = read_binary(binary)
    metadata = json.loads(manifest.read_text(encoding="utf-8"))
    if metadata.get("format_version") != FORMAT_VERSION:
        raise ValueError("Manifest format does not match the reader")
    artifact = metadata.get("artifact", {})
    if artifact.get("name") != binary.name:
        raise ValueError("Manifest artifact name mismatch")
    if artifact.get("bytes") != binary.stat().st_size:
        raise ValueError("Manifest artifact size mismatch")
    if artifact.get("sha256") != sha256(binary):
        raise ValueError("Manifest artifact SHA-256 mismatch")
    content = metadata.get("content", {})
    if content.get("road_count") != decoded["road_count"] or \
            content.get("point_count") != decoded["point_count"]:
        raise ValueError("Manifest content counts mismatch")
    return decoded


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--source", type=Path, required=True)
    build_parser.add_argument("--binary", type=Path, required=True)
    build_parser.add_argument("--manifest", type=Path, required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--binary", type=Path, required=True)
    verify_parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.source, args.binary, args.manifest) if args.command == "build" \
        else verify(args.binary, args.manifest)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
