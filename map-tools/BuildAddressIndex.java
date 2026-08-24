import javax.xml.stream.XMLInputFactory;
import javax.xml.stream.XMLStreamConstants;
import javax.xml.stream.XMLStreamReader;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

/** One-time build tool: full OSM address graph and named POIs -> compact offline lookup. */
public final class BuildAddressIndex {
    private static final List<String> NAME_KEYS = List.of(
        "name", "name:uk", "name:ru", "name:en", "official_name", "short_name",
        "alt_name", "old_name", "loc_name", "brand", "operator"
    );
    private static final Set<String> POI_KEYS = Set.of(
        "amenity", "shop", "tourism", "leisure", "healthcare", "office", "craft",
        "historic", "public_transport", "railway", "aeroway", "place", "man_made"
    );
    private static final double MAX_ORPHAN_STREET_DISTANCE_METERS = 90.0;
    private static final double MIN_STREET_AMBIGUITY_GAP_METERS = 14.0;
    private static final double MIN_STREET_AMBIGUITY_RATIO = 1.45;

    public static void main(String[] args) throws Exception {
        if (args.length < 2 || args.length > 3) throw new IllegalArgumentException(
            "Usage: input.osm output.tsv [existing.tsv]");
        Map<Long, Point> nodes = new HashMap<>();
        Map<Long, Element> taggedNodes = new HashMap<>();
        Map<Long, Element> ways = new HashMap<>();
        List<Element> relations = new ArrayList<>();
        List<PendingAddress> pending = new ArrayList<>();
        List<PendingQualification> pendingQualifications = new ArrayList<>();
        Set<String> records = new TreeSet<>();
        if (args.length == 3) {
            try (BufferedReader existing = new BufferedReader(new InputStreamReader(
                new FileInputStream(args[2]), StandardCharsets.UTF_8))) {
                for (String line; (line = existing.readLine()) != null;) if (!line.isBlank()) records.add(line);
            }
        }
        XMLStreamReader reader = XMLInputFactory.newFactory().createXMLStreamReader(
            new FileInputStream(args[0]), "UTF-8");
        Element current = null;
        while (reader.hasNext()) {
            int event = reader.next();
            if (event == XMLStreamConstants.START_ELEMENT) {
                String element = reader.getLocalName();
                if ("node".equals(element)) {
                    long id = Long.parseLong(reader.getAttributeValue(null, "id"));
                    Point point = new Point(
                        Double.parseDouble(reader.getAttributeValue(null, "lat")),
                        Double.parseDouble(reader.getAttributeValue(null, "lon")));
                    nodes.put(id, point);
                    current = new Element(id, "node", point);
                } else if ("way".equals(element) || "relation".equals(element)) {
                    current = new Element(Long.parseLong(reader.getAttributeValue(null, "id")), element, null);
                } else if ("nd".equals(element) && current != null) {
                    current.nodeRefs.add(Long.parseLong(reader.getAttributeValue(null, "ref")));
                } else if ("member".equals(element) && current != null) {
                    current.members.add(new Member(
                        reader.getAttributeValue(null, "type"),
                        Long.parseLong(reader.getAttributeValue(null, "ref")),
                        value(reader.getAttributeValue(null, "role"))));
                } else if ("tag".equals(element) && current != null) {
                    current.tags.put(reader.getAttributeValue(null, "k"), reader.getAttributeValue(null, "v"));
                }
            } else if (event == XMLStreamConstants.END_ELEMENT && current != null) {
                String element = reader.getLocalName();
                if ("node".equals(element)) {
                    if (!current.tags.isEmpty()) taggedNodes.put(current.id, current);
                    emit(current, current.point, records, pending, pendingQualifications);
                    current = null;
                } else if ("way".equals(element)) {
                    ways.put(current.id, current);
                    emit(current, centroid(current.nodeRefs, nodes), records, pending, pendingQualifications);
                    current = null;
                } else if ("relation".equals(element)) {
                    relations.add(current);
                    current = null;
                }
            }
        }
        reader.close();
        for (Element relation : relations) {
            emit(relation, relationCentroid(relation, nodes, ways), records, pending, pendingQualifications);
            applyAssociatedStreet(relation, taggedNodes, ways, nodes, records, pendingQualifications);
        }
        applyAdministrativeLocalities(relations, ways, nodes, records, pendingQualifications);
        applyAddressInterpolations(ways, taggedNodes, nodes, records, pending);
        attachOrphanAddressesToNearestStreet(pending, ways, nodes, records);
        try (BufferedWriter out = new BufferedWriter(new OutputStreamWriter(
            new FileOutputStream(args[1]), StandardCharsets.UTF_8))) {
            for (String record : records) { out.write(record); out.newLine(); }
        }
        System.out.println("Address/POI index records: " + records.size());
    }

    private static void emit(
        Element element, Point point, Set<String> records, List<PendingAddress> pending,
        List<PendingQualification> pendingQualifications
    ) {
        if (point == null || !insideRuntimeArea(point)) return;
        String street = firstNonBlank(element.tags.get("addr:street"), element.tags.get("addr:place"));
        String house = element.tags.get("addr:housenumber");
        add(records, street, house, point, 3);
        String locality = localityOf(element);
        addQualifiedAddress(records, street, house, locality, point, 4);
        if (street != null && house != null && locality == null)
            pendingQualifications.add(new PendingQualification(street, house, point, 4));
        if (house != null && !house.isBlank() && (street == null || street.isBlank())) {
            pending.add(new PendingAddress(element.type, element.id, house, localityOf(element), point));
        }
        if (!isNamedPoi(element.tags)) return;
        Set<String> names = new LinkedHashSet<>();
        for (String key : NAME_KEYS) splitNames(element.tags.get(key), names);
        for (String name : names) {
            for (String alias : aliases(name)) {
                add(records, alias, null, point, 5);
                if (street != null) add(records, alias + " " + street + " " + value(house), null, point, 7);
                if (street != null) addQualifiedAddress(
                    records, alias + " " + street, house, localityOf(element), point, 8);
            }
        }
    }

    /** Expands standard OSM even/odd/all address interpolation ways into offline points. */
    private static void applyAddressInterpolations(
        Map<Long, Element> ways, Map<Long, Element> taggedNodes, Map<Long, Point> nodes,
        Set<String> records, List<PendingAddress> pending
    ) {
        int emitted = 0;
        for (Element way : ways.values()) {
            String mode = way.tags.get("addr:interpolation");
            if (mode == null || way.nodeRefs.size() < 2) continue;
            Element first = taggedNodes.get(way.nodeRefs.get(0));
            Element last = taggedNodes.get(way.nodeRefs.get(way.nodeRefs.size() - 1));
            if (first == null || last == null) continue;
            Integer start = integerHouse(first.tags.get("addr:housenumber"));
            Integer end = integerHouse(last.tags.get("addr:housenumber"));
            Point startPoint = nodes.get(first.id), endPoint = nodes.get(last.id);
            if (start == null || end == null || startPoint == null || endPoint == null || start.equals(end)) continue;
            int direction = end > start ? 1 : -1;
            int step = ("even".equals(mode) || "odd".equals(mode)) ? 2 : 1;
            step *= direction;
            String street = firstNonBlank(
                way.tags.get("addr:street"), first.tags.get("addr:street"), last.tags.get("addr:street"),
                way.tags.get("addr:place"), first.tags.get("addr:place"), last.tags.get("addr:place")
            );
            for (int number = start; direction > 0 ? number <= end : number >= end; number += step) {
                double fraction = (number - start) / (double) (end - start);
                Point point = new Point(
                    startPoint.lat + fraction * (endPoint.lat - startPoint.lat),
                    startPoint.lon + fraction * (endPoint.lon - startPoint.lon));
                if (street != null) add(records, street, String.valueOf(number), point, 2);
                else pending.add(new PendingAddress(
                    "interpolation", way.id, String.valueOf(number), localityOf(way), point));
                emitted++;
            }
        }
        System.out.println("Interpolated address points emitted: " + emitted);
    }

    private static void applyAssociatedStreet(
        Element relation, Map<Long, Element> taggedNodes, Map<Long, Element> ways,
        Map<Long, Point> nodes, Set<String> records, List<PendingQualification> pendingQualifications
    ) {
        if (!"associatedStreet".equals(relation.tags.get("type"))) return;
        Set<String> names = new LinkedHashSet<>();
        for (Member member : relation.members) {
            if (!"street".equals(member.role)) continue;
            Element street = "way".equals(member.type) ? ways.get(member.ref) : taggedNodes.get(member.ref);
            if (street != null) for (String key : NAME_KEYS) splitNames(street.tags.get(key), names);
        }
        if (names.isEmpty()) splitNames(relation.tags.get("name"), names);
        for (Member member : relation.members) {
            if (!("house".equals(member.role) || "address".equals(member.role))) continue;
            Element house = "way".equals(member.type) ? ways.get(member.ref) : taggedNodes.get(member.ref);
            if (house == null) continue;
            String number = house.tags.get("addr:housenumber");
            Point point = house.point != null ? house.point : centroid(house.nodeRefs, nodes);
            if (number == null || point == null) continue;
            for (String name : names) {
                add(records, name, number, point, 4);
                String locality = localityOf(house);
                addQualifiedAddress(records, name, number, locality, point, 5);
                if (locality == null)
                    pendingQualifications.add(new PendingQualification(name, number, point, 5));
            }
        }
    }

    /** Adds settlement-qualified variants using OSM administrative/place boundary polygons. */
    private static void applyAdministrativeLocalities(
        List<Element> relations, Map<Long, Element> ways, Map<Long, Point> nodes,
        Set<String> records, List<PendingQualification> pending
    ) {
        List<LocalityBoundary> boundaries = new ArrayList<>();
        for (Element relation : relations) {
            if (!isSettlementBoundary(relation.tags)) continue;
            String name = firstNonBlank(relation.tags.get("name:uk"), relation.tags.get("name"));
            if (name == null) continue;
            List<List<Point>> rings = outerRings(relation, ways, nodes);
            if (!rings.isEmpty()) boundaries.add(new LocalityBoundary(name, rings));
        }
        int qualified = 0;
        for (PendingQualification address : pending) {
            LocalityBoundary best = null;
            for (LocalityBoundary boundary : boundaries) {
                if (!boundary.contains(address.point)) continue;
                if (best == null || boundary.area < best.area) best = boundary;
            }
            if (best != null) {
                addQualifiedAddress(records, address.street, address.house, best.name,
                    address.point, address.confidence);
                qualified++;
            }
        }
        System.out.println("Addresses qualified by settlement boundaries: " + qualified
            + " (boundaries: " + boundaries.size() + ")");
    }

    private static boolean isSettlementBoundary(Map<String, String> tags) {
        String place = tags.get("place");
        if (place != null && Set.of("city", "town", "village", "hamlet").contains(place)) return true;
        if (!"administrative".equals(tags.get("boundary"))) return false;
        Integer level;
        try { level = Integer.valueOf(tags.get("admin_level")); }
        catch (RuntimeException ignored) { return false; }
        return level >= 8;
    }

    private static List<List<Point>> outerRings(
        Element relation, Map<Long, Element> ways, Map<Long, Point> nodes
    ) {
        List<List<Long>> chains = new ArrayList<>();
        for (Member member : relation.members) {
            if (!"way".equals(member.type) || "inner".equals(member.role)) continue;
            Element way = ways.get(member.ref);
            if (way != null && way.nodeRefs.size() >= 2) chains.add(new ArrayList<>(way.nodeRefs));
        }
        List<List<Point>> result = new ArrayList<>();
        while (!chains.isEmpty()) {
            List<Long> ring = chains.remove(chains.size() - 1);
            boolean advanced = true;
            while (!ring.get(0).equals(ring.get(ring.size() - 1)) && advanced) {
                advanced = false;
                for (int i = 0; i < chains.size(); i++) {
                    List<Long> next = chains.get(i);
                    Long end = ring.get(ring.size() - 1);
                    if (end.equals(next.get(0))) ring.addAll(next.subList(1, next.size()));
                    else if (end.equals(next.get(next.size() - 1))) {
                        Collections.reverse(next); ring.addAll(next.subList(1, next.size()));
                    } else continue;
                    chains.remove(i); advanced = true; break;
                }
            }
            if (ring.size() >= 4 && ring.get(0).equals(ring.get(ring.size() - 1))) {
                List<Point> points = new ArrayList<>();
                for (Long ref : ring) { Point point = nodes.get(ref); if (point != null) points.add(point); }
                if (points.size() >= 4) result.add(points);
            }
        }
        return result;
    }

    private static void attachOrphanAddressesToNearestStreet(
        List<PendingAddress> pending, Map<Long, Element> ways,
        Map<Long, Point> nodes, Set<String> records
    ) {
        List<StreetGeometry> streets = new ArrayList<>();
        for (Element way : ways.values()) {
            if (!way.tags.containsKey("highway")) continue;
            Set<String> names = new LinkedHashSet<>();
            for (String key : NAME_KEYS) splitNames(way.tags.get(key), names);
            if (names.isEmpty()) continue;
            List<Point> geometry = new ArrayList<>();
            for (Long ref : way.nodeRefs) {
                Point point = nodes.get(ref);
                if (point != null) geometry.add(point);
            }
            if (geometry.size() >= 2) streets.add(new StreetGeometry(names, geometry));
        }
        int attached = 0;
        int ambiguous = 0;
        for (PendingAddress address : pending) {
            Map<String, StreetCandidate> candidates = new HashMap<>();
            for (StreetGeometry street : streets) {
                if (!street.nearBoundingBox(address.point, MAX_ORPHAN_STREET_DISTANCE_METERS)) continue;
                double distance = street.distanceMeters(address.point);
                if (distance > MAX_ORPHAN_STREET_DISTANCE_METERS) continue;
                String identity = street.identity();
                StreetCandidate previous = candidates.get(identity);
                if (previous == null || distance < previous.distance)
                    candidates.put(identity, new StreetCandidate(street, distance));
            }
            List<StreetCandidate> ordered = new ArrayList<>(candidates.values());
            ordered.sort(Comparator.comparingDouble(StreetCandidate::distance));
            StreetGeometry best = ordered.isEmpty() ? null : ordered.get(0).street;
            if (best == null) continue;
            if (ordered.size() > 1) {
                double first = ordered.get(0).distance, second = ordered.get(1).distance;
                if (second - first < MIN_STREET_AMBIGUITY_GAP_METERS
                    || second / Math.max(1.0, first) < MIN_STREET_AMBIGUITY_RATIO) {
                    ambiguous++;
                    continue;
                }
            }
            for (String name : best.names) {
                add(records, name, address.house, address.point, 2);
                addQualifiedAddress(records, name, address.house, address.locality, address.point, 3);
            }
            attached++;
        }
        System.out.println("Orphan house numbers attached to named streets: " + attached);
        System.out.println("Ambiguous orphan house numbers skipped: " + ambiguous);
    }

    private static boolean isNamedPoi(Map<String, String> tags) {
        boolean named = NAME_KEYS.stream().anyMatch(tags::containsKey);
        if (!named) return false;
        if (POI_KEYS.stream().anyMatch(tags::containsKey)) return true;
        return tags.containsKey("building") && !"no".equals(tags.get("building"));
    }

    private static void splitNames(String value, Set<String> names) {
        if (value == null) return;
        for (String name : value.split("[;|]")) if (!name.isBlank()) names.add(name.trim());
    }

    private static Set<String> aliases(String value) {
        Set<String> result = new LinkedHashSet<>();
        result.add(value);
        String city = value.replaceAll("(?iu)city", " Сіті ");
        result.add(city);
        result.add(city.replaceAll("(?iu)\\bторгово[- ]розважальний центр\\b", "ТРЦ"));
        return result;
    }

    private static void add(Set<String> records, String value, String house, Point p, int confidence) {
        if (value == null || value.isBlank()) return;
        String key = normalize(value + " " + value(house));
        if (key.isBlank()) return;
        records.add(key + "\t" + p.lat + "\t" + p.lon + "\t" + confidence);
    }

    private static void addQualifiedAddress(
        Set<String> records, String street, String house, String locality, Point point, int confidence
    ) {
        if (street == null || house == null || locality == null) return;
        add(records, street + " " + house + " " + locality, null, point, confidence);
    }

    private static String localityOf(Element element) {
        return firstNonBlank(
            element.tags.get("addr:city"), element.tags.get("addr:town"),
            element.tags.get("addr:village"), element.tags.get("addr:place")
        );
    }

    private static String value(String value) { return value == null ? "" : value; }
    private static String firstNonBlank(String... values) {
        for (String value : values) if (value != null && !value.isBlank()) return value;
        return null;
    }
    private static Integer integerHouse(String value) {
        if (value == null) return null;
        java.util.regex.Matcher matcher = java.util.regex.Pattern.compile("^\\s*(\\d{1,4})").matcher(value);
        return matcher.find() ? Integer.valueOf(matcher.group(1)) : null;
    }
    private static Point centroid(List<Long> refs, Map<Long, Point> nodes) {
        double lat = 0, lon = 0; int count = 0;
        for (Long ref : refs) { Point p = nodes.get(ref); if (p != null) { lat += p.lat; lon += p.lon; count++; } }
        return count == 0 ? null : new Point(lat / count, lon / count);
    }
    private static Point relationCentroid(Element relation, Map<Long, Point> nodes, Map<Long, Element> ways) {
        double lat = 0, lon = 0; int count = 0;
        for (Member member : relation.members) {
            Point p = "node".equals(member.type) ? nodes.get(member.ref) :
                "way".equals(member.type) && ways.containsKey(member.ref) ? centroid(ways.get(member.ref).nodeRefs, nodes) : null;
            if (p != null) { lat += p.lat; lon += p.lon; count++; }
        }
        return count == 0 ? null : new Point(lat / count, lon / count);
    }
    private static boolean insideRuntimeArea(Point p) {
        return p.lat >= 50.62 && p.lat <= 50.87 && p.lon >= 25.12 && p.lon <= 25.52;
    }
    private static String normalize(String value) {
        return value.toLowerCase(Locale.forLanguageTag("uk"))
            .replace('’', '\'').replace('ʼ', '\'').replace('`', '\'')
            .replaceAll("(?iu)(^|\\s)(вулиця|вул|проспект|просп|провулок|пров|майдан|площа)\\.?(?=\\s|$)", "$1")
            .replaceAll("[^\\p{L}\\p{N}]+", " ").trim().replaceAll("\\s+", " ");
    }

    private static final class Element {
        final long id; final String type; final Point point;
        final List<Long> nodeRefs = new ArrayList<>();
        final List<Member> members = new ArrayList<>();
        final Map<String,String> tags = new HashMap<>();
        Element(long id, String type, Point point) { this.id = id; this.type = type; this.point = point; }
    }
    private record Member(String type, long ref, String role) {}
    private record PendingAddress(String type, long id, String house, String locality, Point point) {}
    private record PendingQualification(String street, String house, Point point, int confidence) {}
    private record StreetCandidate(StreetGeometry street, double distance) {}
    private record Point(double lat, double lon) {}

    private static final class LocalityBoundary {
        final String name; final List<List<Point>> rings; final double area;
        LocalityBoundary(String name, List<List<Point>> rings) {
            this.name = name; this.rings = rings;
            this.area = rings.stream().mapToDouble(LocalityBoundary::ringArea).sum();
        }
        boolean contains(Point point) {
            for (List<Point> ring : rings) if (inside(point, ring)) return true;
            return false;
        }
        private static boolean inside(Point point, List<Point> ring) {
            boolean result = false;
            for (int i = 0, j = ring.size() - 1; i < ring.size(); j = i++) {
                Point a = ring.get(i), b = ring.get(j);
                if ((a.lat > point.lat) != (b.lat > point.lat)
                    && point.lon < (b.lon - a.lon) * (point.lat - a.lat) /
                        (b.lat - a.lat) + a.lon) result = !result;
            }
            return result;
        }
        private static double ringArea(List<Point> ring) {
            double result = 0;
            for (int i = 0, j = ring.size() - 1; i < ring.size(); j = i++)
                result += ring.get(j).lon * ring.get(i).lat - ring.get(i).lon * ring.get(j).lat;
            return Math.abs(result / 2.0);
        }
    }

    private static final class StreetGeometry {
        final Set<String> names; final List<Point> points;
        final double minLat, maxLat, minLon, maxLon;
        StreetGeometry(Set<String> names, List<Point> points) {
            this.names = names; this.points = points;
            minLat = points.stream().mapToDouble(Point::lat).min().orElse(0);
            maxLat = points.stream().mapToDouble(Point::lat).max().orElse(0);
            minLon = points.stream().mapToDouble(Point::lon).min().orElse(0);
            maxLon = points.stream().mapToDouble(Point::lon).max().orElse(0);
        }
        boolean nearBoundingBox(Point p, double meters) {
            double latPad = meters / 111_320.0;
            double lonPad = meters / (111_320.0 * Math.cos(Math.toRadians(p.lat)));
            return p.lat >= minLat - latPad && p.lat <= maxLat + latPad
                && p.lon >= minLon - lonPad && p.lon <= maxLon + lonPad;
        }
        double distanceMeters(Point p) {
            double best = Double.POSITIVE_INFINITY;
            for (int i = 1; i < points.size(); i++)
                best = Math.min(best, pointSegmentDistanceMeters(p, points.get(i - 1), points.get(i)));
            return best;
        }
        String identity() {
            return names.stream().map(BuildAddressIndex::normalize).sorted().findFirst().orElse("");
        }
        private static double pointSegmentDistanceMeters(Point p, Point a, Point b) {
            double scaleX = 111_320.0 * Math.cos(Math.toRadians(p.lat)), scaleY = 111_320.0;
            double ax = (a.lon - p.lon) * scaleX, ay = (a.lat - p.lat) * scaleY;
            double bx = (b.lon - p.lon) * scaleX, by = (b.lat - p.lat) * scaleY;
            double dx = bx - ax, dy = by - ay, length2 = dx * dx + dy * dy;
            double t = length2 == 0 ? 0 : Math.max(0, Math.min(1, -(ax * dx + ay * dy) / length2));
            return Math.hypot(ax + t * dx, ay + t * dy);
        }
    }
}
