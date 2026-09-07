#!/usr/bin/env python3
"""Deterministic desktop-only road artifact prototype for Taxi Helper V3 Stage 2.

The builder intentionally uses only Python's standard library. It reads a fixed OSM XML
snapshot, creates a directed passenger-car graph, and writes immutable binary artifacts.
Nothing in this module is imported by Android or used in the live overlay path.
"""
from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import math
import struct
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

BUILDER_VERSION = "taxi-helper-road-artifact-stage2-v1"
PROFILE_VERSION = "passenger-car-static-v1"
GRID_VERSION = "v2-local-metric-350m-v1"
EARTH_RADIUS_METERS = 6_371_000.0
GRID_EARTH_RADIUS_METERS = 6_378_137.0
GRID_LONGITUDE_SCALE = math.cos(math.radians(50.7472))
DEFAULT_BBOX = (50.6270027, 25.1536113, 50.8789503, 25.5917707)
MAX_SNAP_METERS = 250.0

DEFAULT_SPEED_KPH = {
    "motorway": 90, "motorway_link": 50, "trunk": 80, "trunk_link": 45,
    "primary": 60, "primary_link": 40, "secondary": 50, "secondary_link": 35,
    "tertiary": 45, "tertiary_link": 30, "unclassified": 40, "residential": 30,
    "living_street": 20, "service": 15, "road": 25, "track": 15,
}
DENIED_HIGHWAYS = {
    "footway", "pedestrian", "path", "cycleway", "steps", "bridleway", "corridor",
    "platform", "construction", "proposed", "raceway", "bus_guideway", "escape",
}
DENIED_ACCESS = {"no", "private", "agricultural", "forestry"}


@dataclass(frozen=True)
class Node:
    osm_id: int
    latitude: float
    longitude: float


@dataclass(frozen=True)
class Edge:
    source: int
    target: int
    way_id: int
    distance_m: float
    time_s: float


@dataclass(frozen=True)
class TurnRestriction:
    via_node: int
    from_way: int
    to_way: int
    kind: str


@dataclass
class RoadGraph:
    nodes: dict[int, Node]
    edges: list[Edge]
    restrictions: list[TurnRestriction]
    stats: dict[str, int]

    def adjacency(self) -> dict[int, list[Edge]]:
        result: dict[int, list[Edge]] = defaultdict(list)
        for edge in self.edges:
            result[edge.source].append(edge)
        for values in result.values():
            values.sort(key=lambda edge: (edge.target, edge.way_id, edge.distance_m))
        return dict(result)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def haversine_meters(first: Node, second: Node) -> float:
    d_lat = math.radians(second.latitude - first.latitude)
    d_lon = math.radians(second.longitude - first.longitude)
    first_lat = math.radians(first.latitude)
    second_lat = math.radians(second.latitude)
    value = math.sin(d_lat / 2) ** 2 + math.cos(first_lat) * math.cos(second_lat) * \
        math.sin(d_lon / 2) ** 2
    return 2 * EARTH_RADIUS_METERS * math.asin(math.sqrt(min(1.0, max(0.0, value))))


def coordinate_distance(latitude1: float, longitude1: float,
                        latitude2: float, longitude2: float) -> float:
    return haversine_meters(Node(0, latitude1, longitude1), Node(0, latitude2, longitude2))


def spatial_cell(latitude: float, longitude: float, meters: int = 350) -> tuple[int, int]:
    x = GRID_EARTH_RADIUS_METERS * math.radians(longitude) * GRID_LONGITUDE_SCALE
    y = GRID_EARTH_RADIUS_METERS * math.radians(latitude)
    return math.floor(x / meters), math.floor(y / meters)


def parse_speed_kph(value: str | None, highway: str) -> float:
    if value:
        normalized = value.lower().strip()
        for part in normalized.replace(";", " ").split():
            try:
                speed = float(part)
                if "mph" in normalized:
                    speed *= 1.609344
                if 5 <= speed <= 160:
                    return speed
            except ValueError:
                continue
    return float(DEFAULT_SPEED_KPH.get(highway, 25))


def is_routable(tags: dict[str, str]) -> bool:
    highway = tags.get("highway", "")
    if not highway or highway in DENIED_HIGHWAYS:
        return False
    if highway not in DEFAULT_SPEED_KPH and tags.get("motor_vehicle") not in {"yes", "designated"}:
        return False
    access = tags.get("motorcar", tags.get("motor_vehicle", tags.get("vehicle", tags.get("access", "yes"))))
    return access not in DENIED_ACCESS


def one_way(tags: dict[str, str]) -> int:
    value = tags.get("oneway", "").lower()
    if value == "-1":
        return -1
    if value in {"yes", "true", "1"} or tags.get("junction") == "roundabout":
        return 1
    return 0


def parse_osm(path: Path, bbox: tuple[float, float, float, float]) -> RoadGraph:
    min_lat, min_lon, max_lat, max_lon = bbox
    nodes: dict[int, Node] = {}
    edges: list[Edge] = []
    relation_candidates: list[TurnRestriction] = []
    stats = defaultdict(int)
    routable_way_ids: set[int] = set()

    for _event, element in ET.iterparse(path, events=("end",)):
        kind = element.tag.rsplit("}", 1)[-1]
        if kind == "node":
            stats["osm_nodes_seen"] += 1
            latitude = float(element.attrib["lat"])
            longitude = float(element.attrib["lon"])
            if min_lat <= latitude <= max_lat and min_lon <= longitude <= max_lon:
                osm_id = int(element.attrib["id"])
                nodes[osm_id] = Node(osm_id, latitude, longitude)
        elif kind == "way":
            stats["osm_ways_seen"] += 1
            tags = {child.attrib["k"]: child.attrib["v"] for child in element if child.tag.endswith("tag")}
            if is_routable(tags):
                way_id = int(element.attrib["id"])
                refs = [int(child.attrib["ref"]) for child in element if child.tag.endswith("nd")]
                direction = one_way(tags)
                speed = parse_speed_kph(tags.get("maxspeed"), tags["highway"])
                added = 0
                for first_id, second_id in zip(refs, refs[1:]):
                    first = nodes.get(first_id)
                    second = nodes.get(second_id)
                    if first is None or second is None or first_id == second_id:
                        continue
                    distance = haversine_meters(first, second)
                    if not math.isfinite(distance) or distance <= 0:
                        continue
                    seconds = distance / (speed / 3.6)
                    if direction >= 0:
                        edges.append(Edge(first_id, second_id, way_id, distance, seconds))
                        added += 1
                    if direction <= 0:
                        edges.append(Edge(second_id, first_id, way_id, distance, seconds))
                        added += 1
                if added:
                    routable_way_ids.add(way_id)
                    stats["routable_ways"] += 1
                    stats["oneway_ways"] += int(direction != 0)
        elif kind == "relation":
            tags = {child.attrib["k"]: child.attrib["v"] for child in element if child.tag.endswith("tag")}
            if tags.get("type") == "restriction" and tags.get("restriction"):
                stats["restriction_relations_seen"] += 1
                members = {(child.attrib.get("type"), child.attrib.get("role")): int(child.attrib["ref"])
                           for child in element if child.tag.endswith("member") and child.attrib.get("ref")}
                from_way = members.get(("way", "from"))
                to_way = members.get(("way", "to"))
                via_node = members.get(("node", "via"))
                if from_way is not None and to_way is not None and via_node is not None:
                    relation_candidates.append(TurnRestriction(
                        via_node, from_way, to_way, tags["restriction"].lower()
                    ))
                elif members.get(("way", "via")) is not None:
                    stats["unsupported_via_way_turn_restrictions"] += 1
        # Child nd/tag/member elements must remain intact until their parent way/relation
        # reaches the end event. Clearing only top-level entities still bounds memory.
        if kind in {"node", "way", "relation"}:
            element.clear()

    used_nodes = {edge.source for edge in edges} | {edge.target for edge in edges}
    nodes = {node_id: nodes[node_id] for node_id in sorted(used_nodes)}
    unique_edges = {
        (edge.source, edge.target, edge.way_id): edge for edge in
        sorted(edges, key=lambda item: (item.source, item.target, item.way_id, item.distance_m))
    }
    edges = list(unique_edges.values())
    restrictions = sorted(
        (item for item in relation_candidates if item.via_node in nodes and
         item.from_way in routable_way_ids and item.to_way in routable_way_ids),
        key=lambda item: (item.via_node, item.from_way, item.to_way, item.kind),
    )
    stats["graph_nodes"] = len(nodes)
    stats["directed_edges"] = len(edges)
    stats["turn_restrictions"] = len(restrictions)
    return RoadGraph(nodes, edges, restrictions, dict(sorted(stats.items())))


def build_local_anchor_index(graph: RoadGraph) -> list[dict[str, int]]:
    """Return one anchor per in-cell weak road component, preserving same-cell barriers."""
    cell_nodes: dict[tuple[int, int], list[int]] = defaultdict(list)
    for node in graph.nodes.values():
        cell_nodes[spatial_cell(node.latitude, node.longitude)].append(node.osm_id)
    undirected: dict[int, set[int]] = defaultdict(set)
    global_undirected: dict[int, set[int]] = defaultdict(set)
    for edge in graph.edges:
        global_undirected[edge.source].add(edge.target)
        global_undirected[edge.target].add(edge.source)
        if spatial_cell(graph.nodes[edge.source].latitude, graph.nodes[edge.source].longitude) == \
                spatial_cell(graph.nodes[edge.target].latitude, graph.nodes[edge.target].longitude):
            undirected[edge.source].add(edge.target)
            undirected[edge.target].add(edge.source)
    global_components: dict[int, int] = {}
    remaining_global = set(graph.nodes)
    global_component = 0
    while remaining_global:
        seed = min(remaining_global)
        stack = [seed]
        remaining_global.remove(seed)
        while stack:
            current = stack.pop()
            global_components[current] = global_component
            for neighbour in sorted(global_undirected.get(current, ())):
                if neighbour in remaining_global:
                    remaining_global.remove(neighbour)
                    stack.append(neighbour)
        global_component += 1

    anchors: list[dict[str, int]] = []
    for cell in sorted(cell_nodes):
        remaining = set(cell_nodes[cell])
        local_component = 0
        while remaining:
            seed = min(remaining)
            stack = [seed]
            component: list[int] = []
            remaining.remove(seed)
            while stack:
                current = stack.pop()
                component.append(current)
                for neighbour in sorted(undirected.get(current, ())):
                    if neighbour in remaining:
                        remaining.remove(neighbour)
                        stack.append(neighbour)
            center_lat = sum(graph.nodes[item].latitude for item in component) / len(component)
            center_lon = sum(graph.nodes[item].longitude for item in component) / len(component)
            anchor = min(component, key=lambda item: (
                coordinate_distance(center_lat, center_lon, graph.nodes[item].latitude,
                                    graph.nodes[item].longitude), item
            ))
            anchors.append({"cell_x": cell[0], "cell_y": cell[1],
                            "local_component": local_component, "anchor_node": anchor,
                            "global_component": global_components[anchor],
                            "node_count": len(component)})
            local_component += 1
    return anchors


def coarse_cell_edges(graph: RoadGraph) -> list[tuple[int, int, int, int, int]]:
    """Single-anchor cell graph used only as the deliberately lossy benchmark control."""
    best: dict[tuple[int, int, int, int], float] = {}
    for edge in graph.edges:
        source = spatial_cell(graph.nodes[edge.source].latitude, graph.nodes[edge.source].longitude)
        target = spatial_cell(graph.nodes[edge.target].latitude, graph.nodes[edge.target].longitude)
        if source == target:
            continue
        key = (source[0], source[1], target[0], target[1])
        best[key] = min(best.get(key, math.inf), edge.distance_m)
    return [(a, b, c, d, max(1, round(distance * 100)))
            for (a, b, c, d), distance in sorted(best.items())]


def write_graph(path: Path, graph: RoadGraph) -> None:
    node_ids = sorted(graph.nodes)
    indexes = {node_id: index for index, node_id in enumerate(node_ids)}
    edges = sorted(graph.edges, key=lambda item: (indexes[item.source], indexes[item.target], item.way_id))
    with path.open("wb") as stream:
        stream.write(struct.pack("<8sIIII", b"THRGV3\0\0", 1, len(node_ids), len(edges),
                                 len(graph.restrictions)))
        for node_id in node_ids:
            node = graph.nodes[node_id]
            stream.write(struct.pack("<qii", node_id, round(node.latitude * 10_000_000),
                                     round(node.longitude * 10_000_000)))
        for edge in edges:
            stream.write(struct.pack("<IIqII", indexes[edge.source], indexes[edge.target], edge.way_id,
                                     max(1, round(edge.distance_m * 100)),
                                     max(1, round(edge.time_s * 1000))))
        for restriction in graph.restrictions:
            kind = 1 if restriction.kind.startswith("only_") else \
                (2 if restriction.kind == "no_u_turn" else 0)
            stream.write(struct.pack("<IqqB", indexes[restriction.via_node], restriction.from_way,
                                     restriction.to_way, kind))


def write_anchor_index(path: Path, anchors: list[dict[str, int]], graph: RoadGraph) -> None:
    with path.open("wb") as stream:
        stream.write(struct.pack("<8sII", b"THAIV3\0\0", 1, len(anchors)))
        for item in anchors:
            node = graph.nodes[item["anchor_node"]]
            stream.write(struct.pack("<iiiiQiiI", item["cell_x"], item["cell_y"],
                                     item["local_component"], item["global_component"],
                                     item["anchor_node"],
                                     round(node.latitude * 10_000_000),
                                     round(node.longitude * 10_000_000), item["node_count"]))


def write_cell_graph(path: Path, edges: list[tuple[int, int, int, int, int]]) -> None:
    with path.open("wb") as stream:
        stream.write(struct.pack("<8sII", b"THCGV3\0\0", 1, len(edges)))
        for edge in edges:
            stream.write(struct.pack("<iiiiI", *edge))


class SnapIndex:
    def __init__(self, nodes: dict[int, Node], bucket_meters: int = 350):
        self.nodes = nodes
        self.bucket_meters = bucket_meters
        self.buckets: dict[tuple[int, int], list[int]] = defaultdict(list)
        for node in nodes.values():
            self.buckets[spatial_cell(node.latitude, node.longitude, bucket_meters)].append(node.osm_id)
        for values in self.buckets.values():
            values.sort()

    def snap(self, latitude: float, longitude: float,
             maximum_meters: float = MAX_SNAP_METERS) -> tuple[int | None, float | None]:
        cell = spatial_cell(latitude, longitude, self.bucket_meters)
        radius = max(1, math.ceil(maximum_meters / self.bucket_meters) + 1)
        best_id: int | None = None
        best_distance = math.inf
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                for node_id in self.buckets.get((cell[0] + dx, cell[1] + dy), ()):
                    node = self.nodes[node_id]
                    distance = coordinate_distance(latitude, longitude, node.latitude, node.longitude)
                    if (distance, node_id) < (best_distance, best_id or node_id):
                        best_id, best_distance = node_id, distance
        if best_id is None or best_distance > maximum_meters:
            return None, None
        return best_id, best_distance


class Router:
    def __init__(self, graph: RoadGraph):
        self.graph = graph
        self.adjacency = graph.adjacency()
        self.forbidden: set[tuple[int, int, int]] = set()
        self.same_way_u_turn_forbidden: set[tuple[int, int]] = set()
        self.only: dict[tuple[int, int], set[int]] = defaultdict(set)
        for item in graph.restrictions:
            if item.kind.startswith("only_"):
                self.only[(item.via_node, item.from_way)].add(item.to_way)
            elif item.kind == "no_u_turn" and item.from_way == item.to_way:
                self.same_way_u_turn_forbidden.add((item.via_node, item.from_way))
            else:
                self.forbidden.add((item.via_node, item.from_way, item.to_way))

    def route(self, start: int, target: int, cost: str = "distance",
              maximum_states: int = 500_000) -> tuple[float | None, float | None, int]:
        if start == target:
            return 0.0, 0.0, 0
        queue: list[tuple[float, int, int, int, float, float]] = [(0.0, start, -1, -1, 0.0, 0.0)]
        best: dict[tuple[int, int, int], float] = {(start, -1, -1): 0.0}
        visited = 0
        while queue and visited < maximum_states:
            priority, node_id, incoming_way, previous_node, distance, seconds = heapq.heappop(queue)
            state = (node_id, incoming_way, previous_node)
            if priority != best.get(state):
                continue
            visited += 1
            if node_id == target:
                return distance, seconds, visited
            allowed = self.only.get((node_id, incoming_way))
            for edge in self.adjacency.get(node_id, ()):
                if allowed is not None and edge.way_id not in allowed:
                    continue
                if (node_id, incoming_way, edge.way_id) in self.forbidden:
                    continue
                if (node_id, incoming_way) in self.same_way_u_turn_forbidden and \
                        edge.target == previous_node:
                    continue
                next_distance = distance + edge.distance_m
                next_seconds = seconds + edge.time_s
                next_priority = next_seconds if cost == "time" else next_distance
                next_state = (edge.target, edge.way_id, node_id)
                if next_priority < best.get(next_state, math.inf):
                    best[next_state] = next_priority
                    heapq.heappush(queue, (next_priority, edge.target, edge.way_id, node_id,
                                           next_distance, next_seconds))
        return None, None, visited


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1))
    return round(ordered[index], 3)


def benchmark_routes(graph: RoadGraph, route_samples: Path) -> dict[str, object]:
    router = Router(graph)
    snaps = SnapIndex(graph.nodes)
    by_source: dict[str, list[dict[str, object]]] = defaultdict(list)
    lookup_ms: list[float] = []
    with route_samples.open("r", encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream if line.strip()]
    for row in rows:
        if row.get("status") != "ACCEPTED" or not row.get("start") or not row.get("end"):
            continue
        start_lat, start_lon = map(float, row["start"])
        end_lat, end_lon = map(float, row["end"])
        started = time.perf_counter()
        start_node, start_snap = snaps.snap(start_lat, start_lon)
        end_node, end_snap = snaps.snap(end_lat, end_lon)
        if start_node is None or end_node is None:
            result = {"status": "UNSNAPPED"}
        else:
            distance, seconds, visited = router.route(start_node, end_node)
            if distance is None:
                result = {"status": "UNREACHABLE", "start_snap_m": start_snap,
                          "end_snap_m": end_snap, "visited_states": visited}
            else:
                direct = coordinate_distance(start_lat, start_lon, end_lat, end_lon)
                effective = max(direct, distance + float(start_snap) + float(end_snap))
                provider_m = float(row["provider_distance_km"]) * 1000
                result = {"status": "ROUTED", "road_distance_m": round(effective, 3),
                          "road_time_s": round(seconds, 3), "direct_distance_m": round(direct, 3),
                          "road_to_provider_ratio": round(effective / provider_m, 5),
                          "detour_ratio": round(effective / max(1.0, direct), 5),
                          "start_snap_m": round(float(start_snap), 3),
                          "end_snap_m": round(float(end_snap), 3), "visited_states": visited}
        result["lookup_ms"] = round((time.perf_counter() - started) * 1000, 3)
        lookup_ms.append(float(result["lookup_ms"]))
        by_source[str(row["source_type"])].append(result)
    summary: dict[str, object] = {}
    for source, values in sorted(by_source.items()):
        routed = [item for item in values if item["status"] == "ROUTED"]
        summary[source] = {
            "samples": len(values), "routed": len(routed),
            "unsnapped": sum(item["status"] == "UNSNAPPED" for item in values),
            "unreachable": sum(item["status"] == "UNREACHABLE" for item in values),
            "road_to_provider_ratio_p50": percentile(
                [float(item["road_to_provider_ratio"]) for item in routed], 0.50),
            "road_to_provider_ratio_p95": percentile(
                [float(item["road_to_provider_ratio"]) for item in routed], 0.95),
            "detour_ratio_p50": percentile([float(item["detour_ratio"]) for item in routed], 0.50),
            "snap_distance_p95_m": percentile([
                max(float(item["start_snap_m"]), float(item["end_snap_m"])) for item in routed
            ], 0.95),
        }
    return {"accepted_samples": sum(len(values) for values in by_source.values()),
            "by_source": summary,
            "desktop_lookup_ms": {"p50": percentile(lookup_ms, 0.50),
                                  "p95": percentile(lookup_ms, 0.95),
                                  "maximum": round(max(lookup_ms), 3) if lookup_ms else None}}


def build(osm_path: Path, output: Path, route_samples: Path | None = None,
          bbox: tuple[float, float, float, float] = DEFAULT_BBOX) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    graph = parse_osm(osm_path, bbox)
    parse_seconds = time.perf_counter() - started
    anchors = build_local_anchor_index(graph)
    cells = coarse_cell_edges(graph)
    graph_path = output / "road_graph.bin"
    anchor_path = output / "road_anchor_index.bin"
    cell_path = output / "road_cell_control.bin"
    write_graph(graph_path, graph)
    write_anchor_index(anchor_path, anchors, graph)
    write_cell_graph(cell_path, cells)
    artifact_files = [graph_path, anchor_path, cell_path]
    component_counts: dict[tuple[int, int], int] = defaultdict(int)
    for item in anchors:
        component_counts[(item["cell_x"], item["cell_y"])] += 1
    manifest = {
        "format_version": 1, "builder_version": BUILDER_VERSION,
        "routing_profile_version": PROFILE_VERSION, "grid_spec_version": GRID_VERSION,
        "osm_snapshot_sha256": sha256_file(osm_path),
        "osm_snapshot_id": sha256_file(osm_path)[:16], "coverage_bbox": list(bbox),
        "representation": "directed-node-edge-with-local-component-anchor-index",
        "graph": graph.stats,
        "anchor_index": {
            "anchors": len(anchors),
            "cells": len(component_counts),
            "cells_with_multiple_local_components": sum(count > 1 for count in component_counts.values()),
            "maximum_local_components_per_cell": max(component_counts.values(), default=0),
            "global_weak_components": len({item["global_component"] for item in anchors}),
        },
        "artifacts": {path.name: {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
                      for path in artifact_files},
        "license": {"source": "OpenStreetMap", "data_license": "ODbL-1.0",
                    "attribution_required": True},
        "capabilities": {"directed": True, "oneway": True, "access_filter": True,
                         "via_node_turn_restrictions": True,
                         "via_way_turn_restrictions": False,
                         "multiple_local_components_per_350m_cell": True},
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_bytes(canonical_json(manifest) + b"\n")
    benchmark = {
        "builder_version": BUILDER_VERSION, "build_seconds": round(time.perf_counter() - started, 3),
        "osm_parse_seconds": round(parse_seconds, 3), "manifest_sha256": sha256_file(manifest_path),
        "representations": {
            "directed_node_graph": {"bytes": graph_path.stat().st_size + anchor_path.stat().st_size,
                                    "preserves_same_cell_components": True,
                                    "selected_for_next_stage": True},
            "single_anchor_cell_control": {"bytes": cell_path.stat().st_size,
                                           "preserves_same_cell_components": False,
                                           "selected_for_next_stage": False,
                                           "rejection_reason": "Merges distinct roads inside one 350m cell."},
        },
    }
    if route_samples is not None:
        benchmark["route_validation"] = benchmark_routes(graph, route_samples)
        benchmark["route_samples_sha256"] = sha256_file(route_samples)
    (output / "benchmark.json").write_bytes(canonical_json(benchmark) + b"\n")
    return {"manifest": manifest, "benchmark": benchmark}


def parse_bbox(value: str) -> tuple[float, float, float, float]:
    parts = tuple(float(part) for part in value.split(","))
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("bbox must be minLat,minLon,maxLat,maxLon")
    return parts  # type: ignore[return-value]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--osm", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--route-samples", type=Path)
    parser.add_argument("--bbox", type=parse_bbox, default=DEFAULT_BBOX)
    args = parser.parse_args()
    result = build(args.osm, args.output, args.route_samples, args.bbox)
    print(json.dumps({"status": "BUILT", "nodes": result["manifest"]["graph"]["graph_nodes"],
                      "edges": result["manifest"]["graph"]["directed_edges"],
                      "manifest_sha256": result["benchmark"]["manifest_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
