#!/usr/bin/env python3
"""Verify THRICH01 v3 and bind its bytes to the same source map and OSM release."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inspect(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    if len(data) < 60 or data[:8] != b"THRICH01":
        raise ValueError("Invalid rich context header")
    version, lat, lon, lat_m, lon_m, count, declared_points = struct.unpack_from(">i4d2i", data, 8)
    if version != 3 or not (1 <= count <= 200_000 and 1 <= declared_points <= 1_500_000):
        raise ValueError("Unsupported rich context version or counts")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180 and 50_000 <= lat_m <= 150_000 and 20_000 <= lon_m <= 150_000):
        raise ValueError("Invalid rich context projection")
    offset = 8 + struct.calcsize(">i4d2i")
    observed_points = 0
    types = {str(kind): 0 for kind in range(1, 12)}
    for _ in range(count):
        if offset + 5 > len(data):
            raise ValueError("Truncated rich feature")
        kind, points, name_length = struct.unpack_from(">BHH", data, offset)
        offset += 5
        if kind not in range(1, 12) or not (1 <= points <= 4096) or name_length > 160:
            raise ValueError("Invalid rich feature")
        if kind in (1, 2, 3, 4, 8, 10) and points < 3 or kind in (5, 6, 7, 11) and points < 2 or kind == 9 and points != 1:
            raise ValueError("Invalid rich feature geometry")
        if (kind in (7, 9, 11)) != (name_length > 0):
            raise ValueError("Invalid rich feature label")
        payload = points * 8 + name_length
        if offset + payload > len(data):
            raise ValueError("Truncated rich feature payload")
        for x, y in struct.iter_unpack(">ii", data[offset:offset + points * 8]):
            if abs(x) > 100_000 or abs(y) > 100_000:
                raise ValueError("Rich geometry is outside supported projection")
        offset += payload
        observed_points += points
        types[str(kind)] += 1
    if offset != len(data) or observed_points != declared_points:
        raise ValueError("Rich context length/count mismatch")
    return {"format_version": version, "feature_count": count, "point_count": observed_points, "feature_counts": types}


def build(binary: Path, source_map: Path, osm_source: Path, output: Path) -> dict[str, object]:
    details = inspect(binary)
    manifest = {
        "format_version": 3,
        "asset": binary.name,
        "asset_bytes": binary.stat().st_size,
        "asset_sha256": sha256(binary),
        "source_map_sha256": sha256(source_map),
        "osm_snapshot_sha256": sha256(osm_source),
        **details,
        "source": "OpenStreetMap / release Mapsforge map",
        "license": "ODbL-1.0",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return manifest


def verify(binary: Path, source_map: Path, osm_source: Path, manifest_path: Path) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    details = inspect(binary)
    expected = {
        "format_version": 3,
        "asset": binary.name,
        "asset_bytes": binary.stat().st_size,
        "asset_sha256": sha256(binary),
        "source_map_sha256": sha256(source_map),
        "osm_snapshot_sha256": sha256(osm_source),
        **details,
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise ValueError(f"Rich context manifest mismatch: {key}")
    return details


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--map", type=Path, required=True)
    parser.add_argument("--osm", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.binary, args.map, args.osm, args.manifest) if args.command == "build" else verify(
        args.binary, args.map, args.osm, args.manifest
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
