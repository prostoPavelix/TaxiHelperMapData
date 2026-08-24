import javax.xml.stream.XMLInputFactory;
import javax.xml.stream.XMLStreamConstants;
import javax.xml.stream.XMLStreamReader;
import java.io.BufferedWriter;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.OutputStreamWriter;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/** One-time build tool: OSM road geometry -> compact Android street lookup. */
public final class BuildStreetIndex {
    private static final double MIN_LAT = 50.62, MAX_LAT = 50.87;
    private static final double MIN_LON = 25.12, MAX_LON = 25.52;

    public static void main(String[] args) throws Exception {
        if (args.length != 2) throw new IllegalArgumentException("Usage: input.osm output.tsv");
        Map<Long, Point> nodes = new HashMap<>();
        Set<String> written = new HashSet<>();
        XMLInputFactory factory = XMLInputFactory.newFactory();
        try (FileInputStream input = new FileInputStream(args[0]);
             BufferedWriter output = new BufferedWriter(new OutputStreamWriter(
                 new FileOutputStream(args[1]), StandardCharsets.UTF_8))) {
            XMLStreamReader reader = factory.createXMLStreamReader(input, "UTF-8");
            List<Long> refs = null;
            String name = null;
            boolean road = false;
            while (reader.hasNext()) {
                int event = reader.next();
                if (event == XMLStreamConstants.START_ELEMENT) {
                    switch (reader.getLocalName()) {
                        case "node" -> nodes.put(
                            Long.parseLong(reader.getAttributeValue(null, "id")),
                            new Point(
                                Double.parseDouble(reader.getAttributeValue(null, "lat")),
                                Double.parseDouble(reader.getAttributeValue(null, "lon"))
                            )
                        );
                        case "way" -> {
                            refs = new ArrayList<>();
                            name = null;
                            road = false;
                        }
                        case "nd" -> { if (refs != null) refs.add(Long.parseLong(reader.getAttributeValue(null, "ref"))); }
                        case "tag" -> {
                            if (refs == null) break;
                            String key = reader.getAttributeValue(null, "k");
                            String value = reader.getAttributeValue(null, "v");
                            if ("name".equals(key)) name = value;
                            if ("highway".equals(key) && !"footway".equals(value) && !"path".equals(value)) road = true;
                        }
                    }
                } else if (event == XMLStreamConstants.END_ELEMENT && "way".equals(reader.getLocalName())) {
                    if (road && name != null && refs != null) {
                        String normalized = normalize(name);
                        for (int i = 0; i < refs.size(); i += 4) writePoint(nodes.get(refs.get(i)), normalized, output, written);
                        if (!refs.isEmpty()) writePoint(nodes.get(refs.get(refs.size() - 1)), normalized, output, written);
                    }
                    refs = null;
                }
            }
            reader.close();
        }
        System.out.println("Street index records: " + written.size());
    }

    private static void writePoint(Point point, String name, BufferedWriter output, Set<String> written) throws Exception {
        if (point == null || point.lat < MIN_LAT || point.lat > MAX_LAT || point.lon < MIN_LON || point.lon > MAX_LON) return;
        String record = name + "\t" + point.lat + "\t" + point.lon;
        if (written.add(record)) {
            output.write(record);
            output.newLine();
        }
    }

    static String normalize(String value) {
        return value.toLowerCase(new Locale("uk"))
            .replaceAll("(?iu)(^|\\s)(вулиця|вул|проспект|просп|провулок|пров|майдан|площа)\\.?(?=\\s|$)", "$1")
            .replaceAll("[^\\p{L}]+", " ").trim().replaceAll("\\s+", " ");
    }

    record Point(double lat, double lon) {}
}
