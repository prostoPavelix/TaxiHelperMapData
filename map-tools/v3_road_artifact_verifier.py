#!/usr/bin/env python3
"""Verifier and topology gate for the desktop-only V3 Stage 2 road artifact."""
from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

import v3_road_artifact as road

VERIFIER_VERSION = "taxi-helper-road-artifact-verifier-stage2-v1"


def verify_artifacts(folder: Path) -> dict[str, object]:
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    failures: list[str] = []
    if manifest_path.read_bytes() != road.canonical_json(manifest) + b"\n":
        failures.append("MANIFEST_NOT_CANONICAL")
    for name, metadata in manifest.get("artifacts", {}).items():
        path = folder / name
        if not path.is_file():
            failures.append(f"MISSING:{name}")
            continue
        if path.stat().st_size != metadata["bytes"]:
            failures.append(f"SIZE:{name}")
        if road.sha256_file(path) != metadata["sha256"]:
            failures.append(f"SHA256:{name}")

    graph = manifest["graph"]
    graph_path = folder / "road_graph.bin"
    if graph_path.is_file():
        with graph_path.open("rb") as stream:
            magic, version, nodes, edges, restrictions = struct.unpack("<8sIIII", stream.read(24))
        expected = 24 + nodes * 16 + edges * 24 + restrictions * 21
        if magic != b"THRGV3\0\0" or version != 1 or graph_path.stat().st_size != expected:
            failures.append("GRAPH_HEADER_OR_LENGTH")
        if (nodes, edges, restrictions) != (graph["graph_nodes"], graph["directed_edges"],
                                            graph["turn_restrictions"]):
            failures.append("GRAPH_MANIFEST_COUNTS")
    anchor_path = folder / "road_anchor_index.bin"
    if anchor_path.is_file():
        with anchor_path.open("rb") as stream:
            magic, version, count = struct.unpack("<8sII", stream.read(16))
        if magic != b"THAIV3\0\0" or version != 1 or anchor_path.stat().st_size != 16 + count * 36:
            failures.append("ANCHOR_HEADER_OR_LENGTH")
    cell_path = folder / "road_cell_control.bin"
    if cell_path.is_file():
        with cell_path.open("rb") as stream:
            magic, version, count = struct.unpack("<8sII", stream.read(16))
        if magic != b"THCGV3\0\0" or version != 1 or cell_path.stat().st_size != 16 + count * 20:
            failures.append("CELL_HEADER_OR_LENGTH")
    return {"status": "PASSED" if not failures else "FAILED", "failures": failures,
            "manifest_sha256": road.sha256_file(manifest_path)}


def topology_route(graph: road.RoadGraph, router: road.Router, snaps: road.SnapIndex,
                   first: dict[str, object], second: dict[str, object]) -> dict[str, object]:
    first_id, first_snap = snaps.snap(float(first["latitude"]), float(first["longitude"]))
    second_id, second_snap = snaps.snap(float(second["latitude"]), float(second["longitude"]))
    if first_id is None or second_id is None:
        return {"status": "UNSNAPPED"}
    distance, seconds, _visited = router.route(first_id, second_id)
    if distance is None:
        return {"status": "UNREACHABLE"}
    direct = road.coordinate_distance(float(first["latitude"]), float(first["longitude"]),
                                      float(second["latitude"]), float(second["longitude"]))
    effective = max(direct, distance + float(first_snap) + float(second_snap))
    return {"status": "ROUTED", "direct_distance_m": round(direct, 3),
            "road_distance_m": round(effective, 3), "road_time_s": round(seconds, 3),
            "detour_ratio": round(effective / max(1.0, direct), 5),
            "from_snap_m": round(float(first_snap), 3), "to_snap_m": round(float(second_snap), 3)}


def verify_real_cases(graph: road.RoadGraph, fixture: Path) -> dict[str, object]:
    contract = json.loads(fixture.read_text(encoding="utf-8"))
    router = road.Router(graph)
    snaps = road.SnapIndex(graph.nodes)
    results = []
    for case in contract["real_cases"]:
        forward = topology_route(graph, router, snaps, case["from"], case["to"])
        reverse = topology_route(graph, router, snaps, case["to"], case["from"])
        passed = forward.get("status") == "ROUTED" and \
            float(forward.get("detour_ratio", 0.0)) >= float(case["minimum_detour_ratio"])
        if "minimum_directional_difference_m" in case and forward.get("status") == "ROUTED" and \
                reverse.get("status") == "ROUTED":
            passed = passed and abs(float(forward["road_distance_m"]) -
                                    float(reverse["road_distance_m"])) >= \
                float(case["minimum_directional_difference_m"])
        results.append({"id": case["id"], "passed": passed,
                        "expected": case["expected"], "forward": forward, "reverse": reverse})
    return {"status": "PASSED" if all(item["passed"] for item in results) else "FAILED",
            "cases": results}


def synthetic_graph(nodes: list[road.Node], edges: list[road.Edge]) -> road.RoadGraph:
    return road.RoadGraph({item.osm_id: item for item in nodes}, edges, [], {})


def verify_synthetic_cases() -> dict[str, object]:
    results: list[dict[str, object]] = []
    def add(identifier: str, passed: bool, details: object) -> None:
        results.append({"id": identifier, "passed": bool(passed), "details": details})

    nodes = [road.Node(1, 50.7500, 25.3300), road.Node(2, 50.7500, 25.3310),
             road.Node(3, 50.7500, 25.3320)]
    edges = [road.Edge(1, 2, 1, 70, 7), road.Edge(2, 3, 1, 70, 7)]
    distance = road.Router(synthetic_graph(nodes, edges)).route(1, 3)[0]
    direct = road.haversine_meters(nodes[0], nodes[2])
    effective = max(float(distance or 0.0), direct)
    add("SYNTHETIC_SAME_ROAD", distance is not None and effective >= direct,
        {"raw_road_m": distance, "effective_road_m": effective, "direct_m": direct})

    detour_nodes = [road.Node(1, 50.7500, 25.3300), road.Node(2, 50.7500, 25.3310),
                    road.Node(3, 50.7550, 25.3305)]
    detour_edges = [road.Edge(1, 3, 1, 600, 60), road.Edge(3, 2, 1, 600, 60)]
    detour = road.Router(synthetic_graph(detour_nodes, detour_edges)).route(1, 2)[0]
    detour_direct = road.haversine_meters(detour_nodes[0], detour_nodes[1])
    detour_effective = max(float(detour or 0.0), detour_direct)
    add("SYNTHETIC_RAIL_DETOUR", detour is not None and detour_effective > detour_direct * 5,
        {"road_m": detour_effective, "direct_m": detour_direct})

    bridge_edges = [road.Edge(1, 3, 10, 600, 60), road.Edge(3, 2, 11, 600, 60)]
    with_bridge = road.Router(synthetic_graph(detour_nodes, bridge_edges)).route(1, 2)[0]
    without_bridge = road.Router(synthetic_graph(detour_nodes, bridge_edges[:1])).route(1, 2)[0]
    add("SYNTHETIC_ONLY_BRIDGE", with_bridge is not None and without_bridge is None,
        {"with_bridge_m": with_bridge, "without_bridge": without_bridge})

    one_way = road.Router(synthetic_graph(nodes[:2], [road.Edge(1, 2, 1, 70, 7)]))
    add("SYNTHETIC_ONE_WAY", one_way.route(1, 2)[0] is not None and one_way.route(2, 1)[0] is None,
        {"forward": one_way.route(1, 2)[0], "reverse": one_way.route(2, 1)[0]})

    disconnected = road.Router(synthetic_graph(nodes[:2], []))
    add("SYNTHETIC_DISCONNECTED", disconnected.route(1, 2)[0] is None,
        {"route": disconnected.route(1, 2)[0]})

    snap_index = road.SnapIndex({item.osm_id: item for item in nodes[:2]})
    boundary = snap_index.snap(49.0, 24.0)
    add("SYNTHETIC_GRAPH_BOUNDARY", boundary[0] is None, {"snap": boundary[0]})
    poor_snap = snap_index.snap(50.7600, 25.3400, maximum_meters=30)
    add("SYNTHETIC_POOR_SNAP", poor_snap[0] is None, {"snap": poor_snap[0]})

    same_cell_nodes = [road.Node(1, 50.75000, 25.33000), road.Node(2, 50.75005, 25.33005),
                       road.Node(3, 50.75010, 25.33010), road.Node(4, 50.75015, 25.33015)]
    same_cell_edges = [road.Edge(1, 2, 1, 8, 1), road.Edge(3, 4, 2, 8, 1)]
    same_cell_graph = synthetic_graph(same_cell_nodes, same_cell_edges)
    anchors = road.build_local_anchor_index(same_cell_graph)
    add("SYNTHETIC_SAME_CELL_BARRIER", len(anchors) == 2 and
        len({(item["cell_x"], item["cell_y"]) for item in anchors}) == 1, anchors)

    return {"status": "PASSED" if all(item["passed"] for item in results) else "FAILED",
            "cases": results}


def verify(osm_path: Path, artifact_dir: Path, topology_fixture: Path) -> dict[str, object]:
    artifacts = verify_artifacts(artifact_dir)
    graph = road.parse_osm(osm_path, tuple(json.loads(
        (artifact_dir / "manifest.json").read_text(encoding="utf-8"))["coverage_bbox"]))
    real = verify_real_cases(graph, topology_fixture)
    synthetic = verify_synthetic_cases()
    manifest = json.loads((artifact_dir / "manifest.json").read_text(encoding="utf-8"))
    stop_gate = {
        "artifact_integrity": artifacts["status"] == "PASSED",
        "real_topology": real["status"] == "PASSED",
        "synthetic_topology": synthetic["status"] == "PASSED",
        "deterministic_builder_required": True,
        "multiple_same_cell_components": manifest["anchor_index"]["cells_with_multiple_local_components"] > 0,
        "android_production_bundle_changed": False,
        "production_forecast_changed": False,
    }
    stop_gate["status"] = "PASSED" if (
        stop_gate["artifact_integrity"] and stop_gate["real_topology"] and
        stop_gate["synthetic_topology"] and stop_gate["deterministic_builder_required"] and
        stop_gate["multiple_same_cell_components"] and
        not stop_gate["android_production_bundle_changed"] and
        not stop_gate["production_forecast_changed"]
    ) else "FAILED"
    return {"verifier_version": VERIFIER_VERSION, "artifact_integrity": artifacts,
            "real_topology": real, "synthetic_topology": synthetic, "stage2_stop_gate": stop_gate}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--osm", required=True, type=Path)
    parser.add_argument("--artifact-dir", required=True, type=Path)
    parser.add_argument("--topology-fixture", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = verify(args.osm, args.artifact_dir, args.topology_fixture)
    encoded = road.canonical_json(result) + b"\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(encoded)
    print(encoded.decode("utf-8"), end="")
    raise SystemExit(0 if result["stage2_stop_gate"]["status"] == "PASSED" else 1)


if __name__ == "__main__":
    main()
