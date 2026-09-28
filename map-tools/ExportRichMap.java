import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import org.mapsforge.core.model.*;
import org.mapsforge.map.datastore.*;
import org.mapsforge.map.reader.MapFile;

/** Deterministic visual extraction from the active full OSM map, independent of sectors. */
public final class ExportRichMap {
    private static final double LAT0=50.7472,LON0=25.3254,LAT_M=111132.0;
    private static final double LON_M=111320.0*Math.cos(Math.toRadians(LAT0));
    // Conservative Lutsk footprint: surrounding villages keep normal operational roads.
    private static final double CITY_X=6200,CITY_Y=5700;
    // Verified place= village/suburb coordinates in the active Mapsforge source.
    // Separate small footprints prevent a blanket return of remote map detail.
    private static final double[][] NEIGHBORS={
        {50.7100328336323,25.406495625,1100}, // Pidhaitsi
        {50.70435440082821,25.35533165625,1000}, // Boratyn
        {50.746582311369636,25.416209625,1000}, // Strumivka
        {50.76942427465924,25.33550365625,950}, // Vyshkiv
        {50.69756440082821,25.30297734375,950}, // Veresneve
        {50.682986838192875,25.25955303125,1000}, // Hirka Polonka
        {50.69756040082821,25.22013171875,950}, // Baiv
        {50.70689040082821,25.25930003125,950}, // Horodyshche
        {50.744621311369634,25.229561375,1000}, // Zaborol
        {50.777918274659235,25.2732866875,950}, // Mylushi, not Mylushyn
        {50.76773427465923,25.2804336875,950} // Zmiinets
    };
    private static final byte WATER=1,GREEN=2,RESIDENTIAL=3,BUILDING=4,RAIL=5,WATERWAY=6,
        MAJOR_NAME=7,SPORTS=8,POI_NAME=9,INDUSTRIAL=10,LOCAL_NAME=11,ZOOM=15;
    private static final int MAX_FEATURES=20_000,MAX_POINTS=300_000;
    private record Feature(byte type,int[] points,String name) {}
    private static final List<Feature> features=new ArrayList<>();
    private static final Set<String> seen=new HashSet<>();
    private static final Map<String,List<int[]>> roadFragments=new TreeMap<>();
    private static final Set<String> seenRoadFragments=new HashSet<>();
    private static int totalPoints=0;
    private static int x(double longitude){return (int)Math.round((longitude-LON0)*LON_M);}
    private static int y(double latitude){return (int)Math.round((latitude-LAT0)*LAT_M);}
    private static int tileX(double longitude){return (int)Math.floor((longitude+180)/360*(1<<ZOOM));}
    private static int tileY(double latitude){double r=Math.toRadians(latitude);return (int)Math.floor((1-Math.log(Math.tan(r)+1/Math.cos(r))/Math.PI)/2*(1<<ZOOM));}
    private static String tag(List<Tag> tags,String key){for(Tag t:tags)if(t.key.equals(key))return t.value;return null;}
    private static boolean oneOf(String value,String... choices){return value!=null && Arrays.asList(choices).contains(value);}
    private static boolean inCity(int px,int py){double u=px/CITY_X,v=py/CITY_Y;return u*u+v*v<=1;}
    private static int regionFor(int px,int py){
        int nearest=-1;double best=Double.POSITIVE_INFINITY;
        for(int i=0;i<NEIGHBORS.length;i++){
            double dx=px-x(NEIGHBORS[i][1]),dy=py-y(NEIGHBORS[i][0]);
            double normalized=(dx*dx+dy*dy)/(NEIGHBORS[i][2]*NEIGHBORS[i][2]);
            if(normalized<=1&&normalized<best){best=normalized;nearest=i+1;}
        }
        return nearest>=0?nearest:inCity(px,py)?0:-1;
    }
    private static int[] project(LatLong[] points){int[] result=new int[points.length*2];for(int i=0;i<points.length;i++){result[2*i]=x(points[i].longitude);result[2*i+1]=y(points[i].latitude);}return result;}
    private static double length(int[] p){double n=0;for(int i=2;i<p.length;i+=2)n+=Math.hypot(p[i]-p[i-2],p[i+1]-p[i-1]);return n;}
    private static double area(int[] p){double n=0;for(int i=0;i<p.length-2;i+=2)n+=(double)p[i]*p[i+3]-(double)p[i+2]*p[i+1];return Math.abs(n)/2;}
    private static int[] reverse(int[] p){int[] r=new int[p.length];for(int i=0;i<p.length;i+=2){r[i]=p[p.length-i-2];r[i+1]=p[p.length-i-1];}return r;}
    private static boolean near(int ax,int ay,int bx,int by){return Math.hypot(ax-bx,ay-by)<=25;}
    private static int[] join(int[] a,int[] b){int[] r=Arrays.copyOf(a,a.length+b.length-2);System.arraycopy(b,2,r,a.length,b.length-2);return r;}
    private static void collectRoad(byte type,String name,int[] p){
        if(!centerInCoverage(p)||length(p)<60)return;
        String key=type+":"+name;
        if(seenRoadFragments.add(key+Arrays.toString(p)))roadFragments.computeIfAbsent(key,k->new ArrayList<>()).add(p);
    }
    /** Stitch OSM way fragments by matching endpoints so text can follow a real street corridor. */
    private static void addRoadCorridors(){
        for(var entry:roadFragments.entrySet()){
            List<int[]> fragments=new ArrayList<>(entry.getValue());
            while(!fragments.isEmpty()){
                int[] chain=fragments.remove(0);boolean extended;
                do {extended=false;
                    for(int i=0;i<fragments.size();i++){
                        int[] next=fragments.get(i);int[] candidate=null;
                        if(near(chain[chain.length-2],chain[chain.length-1],next[0],next[1]))candidate=join(chain,next);
                        else if(near(chain[chain.length-2],chain[chain.length-1],next[next.length-2],next[next.length-1]))candidate=join(chain,reverse(next));
                        else if(near(chain[0],chain[1],next[next.length-2],next[next.length-1]))candidate=join(next,chain);
                        else if(near(chain[0],chain[1],next[0],next[1]))candidate=join(reverse(next),chain);
                        if(candidate!=null && candidate.length<=8192){chain=candidate;fragments.remove(i);extended=true;break;}
                    }
                }while(extended);
                byte type=Byte.parseByte(entry.getKey().substring(0,entry.getKey().indexOf(':')));
                if(length(chain)>=(type==MAJOR_NAME?180:120))add(type,chain,entry.getKey().substring(entry.getKey().indexOf(':')+1));
            }
        }
    }
    private static int featureRegion(int[] p){long sx=0,sy=0;for(int i=0;i<p.length;i+=2){sx+=p[i];sy+=p[i+1];}return regionFor((int)(sx/(p.length/2)),(int)(sy/(p.length/2)));}
    private static boolean centerInCoverage(int[] p){return featureRegion(p)>=0;}
    private static void add(byte type,int[] p,String name){
        if(p.length<2||p.length>8192||!centerInCoverage(p))return;
        byte[] bytes=name==null?new byte[0]:name.getBytes(StandardCharsets.UTF_8);if(bytes.length>160)return;
        if(!seen.add(type+":"+Arrays.toString(p)+":"+name))return;
        totalPoints+=p.length/2;
        if(features.size()>=MAX_FEATURES||totalPoints>MAX_POINTS)throw new IllegalStateException("Rich map exceeds bounds");
        features.add(new Feature(type,p,name));
    }
    private static void way(Way way){
        String name=tag(way.tags,"name"),highway=tag(way.tags,"highway"),railway=tag(way.tags,"railway"),waterway=tag(way.tags,"waterway"),natural=tag(way.tags,"natural"),landuse=tag(way.tags,"landuse"),leisure=tag(way.tags,"leisure"),building=tag(way.tags,"building"),amenity=tag(way.tags,"amenity");
        byte type=0;
        if(oneOf(natural,"water","bay")||oneOf(waterway,"riverbank"))type=WATER;
        else if(oneOf(leisure,"pitch","stadium","sports_centre","playground"))type=SPORTS;
        else if(oneOf(leisure,"park","garden","recreation_ground")||oneOf(landuse,"grass","forest","recreation_ground","meadow")||oneOf(natural,"wood","grassland","scrub"))type=GREEN;
        else if(oneOf(landuse,"residential"))type=RESIDENTIAL;
        else if(oneOf(landuse,"commercial","industrial","retail"))type=INDUSTRIAL;
        else if(building!=null&&!building.equals("no"))type=BUILDING;
        for(LatLong[] ring:way.latLongs){
            if(ring.length<2)continue;int[] p=project(ring);
            double size=area(p);
            if(type!=0&&ring.length>=3&&size>=(type==BUILDING?1_500:type==RESIDENTIAL?4_000:type==INDUSTRIAL?3_000:type==SPORTS?500:type==GREEN?700:1_000))add(type,p,null);
            // Rail yards/sidings are noisy; retain only useful continuous lines.
            if(oneOf(railway,"rail")&&length(p)>=250)add(RAIL,p,null);
            if(oneOf(waterway,"river","canal")&&length(p)>=100)add(WATERWAY,p,null);
            // Preserve the actual road line. A short or occupied line receives no text.
            if(name!=null&&tag(way.tags,"place")==null&&oneOf(highway,"motorway","trunk","primary","secondary","tertiary"))collectRoad(MAJOR_NAME,name,p);
            else if(name!=null&&tag(way.tags,"place")==null&&oneOf(highway,"residential","living_street","unclassified"))collectRoad(LOCAL_NAME,name,p);
        }
        if(name!=null&&tag(way.tags,"place")==null&&
            (oneOf(amenity,"hospital","university","school","bus_station","theatre")||
             oneOf(leisure,"park","stadium")||oneOf(railway,"station")||
             oneOf(tag(way.tags,"shop"),"mall","supermarket","department_store")||oneOf(tag(way.tags,"tourism"),"museum","attraction"))){
            LatLong point=way.labelPosition;
            if(point==null && way.latLongs.length>0&&way.latLongs[0].length>0)point=way.latLongs[0][way.latLongs[0].length/2];
            if(point!=null)add(POI_NAME,new int[]{x(point.longitude),y(point.latitude)},name);
        }
    }
    private static void poi(PointOfInterest poi){
        if(tag(poi.tags,"place")!=null)return;String name=tag(poi.tags,"name");if(name==null||name.isBlank())return;
        if(oneOf(tag(poi.tags,"amenity"),"hospital","university","school","bus_station","theatre")||oneOf(tag(poi.tags,"railway"),"station")||oneOf(tag(poi.tags,"tourism"),"museum","attraction")||oneOf(tag(poi.tags,"shop"),"mall","supermarket","department_store"))add(POI_NAME,new int[]{x(poi.position.longitude),y(poi.position.latitude)},name);
    }
    private static void write(Path output)throws IOException{
        Files.createDirectories(output.getParent());try(DataOutputStream out=new DataOutputStream(new BufferedOutputStream(Files.newOutputStream(output)))){
            out.write("THRICH01".getBytes(StandardCharsets.US_ASCII));out.writeInt(3);
            out.writeDouble(LAT0);out.writeDouble(LON0);out.writeDouble(LAT_M);out.writeDouble(LON_M);out.writeInt(features.size());out.writeInt(totalPoints);
            for(Feature f:features){byte[] label=f.name==null?new byte[0]:f.name.getBytes(StandardCharsets.UTF_8);out.writeByte(f.type);out.writeShort(f.points.length/2);out.writeShort(label.length);for(int c:f.points)out.writeInt(c);out.write(label);}
        }
    }
    /** Keep 35% of the previous 2/15 set: the largest 7/150 of original
     * decorative polygons of each kind. Road geometry and
     * named corridors are intentionally untouched so the street network stays complete. */
    private static void retainLargestDecorativeAreas(){
        Set<Feature> retained=Collections.newSetFromMap(new IdentityHashMap<>());
        for(int region=0;region<=NEIGHBORS.length;region++){
            for(int type:new int[]{WATER,GREEN,RESIDENTIAL,BUILDING,SPORTS,INDUSTRIAL}){
                List<Feature> group=new ArrayList<>();
                for(Feature f:features)if(f.type==type&&featureRegion(f.points)==region)group.add(f);
                group.sort(Comparator.comparingDouble((Feature f)->area(f.points)).reversed());
                retained.addAll(group.subList(0,(7*group.size()+149)/150));
            }
        }
        features.removeIf(f->(f.type==WATER||f.type==GREEN||f.type==RESIDENTIAL||
            f.type==BUILDING||f.type==SPORTS||f.type==INDUSTRIAL)&&!retained.contains(f));
        totalPoints=0;for(Feature f:features)totalPoints+=f.points.length/2;
    }
    public static void main(String[] args)throws Exception{
        if(args.length!=2)throw new IllegalArgumentException("source.map output.bin");MapFile map=new MapFile(new File(args[0]));
        try{BoundingBox b=map.boundingBox();int w=tileX(b.minLongitude),e=tileX(b.maxLongitude),n=tileY(b.maxLatitude),s=tileY(b.minLatitude);
            for(int tx=w;tx<=e;tx++)for(int ty=n;ty<=s;ty++){MapReadResult data=map.readMapData(new Tile(tx,ty,ZOOM,256));for(Way item:data.ways)way(item);for(PointOfInterest item:data.pois)poi(item);}
            addRoadCorridors();
            retainLargestDecorativeAreas();
            features.sort(Comparator.comparingInt((Feature f)->f.type)
                .thenComparing((Feature first,Feature second)->(first.type==MAJOR_NAME||first.type==LOCAL_NAME)&&first.type==second.type?Double.compare(length(second.points),length(first.points)):0)
                .thenComparingInt(f->f.points[0]).thenComparingInt(f->f.points[1]).thenComparing(f->f.name==null?"":f.name));
            write(Path.of(args[1]));int[] counts=new int[12];for(Feature f:features)counts[f.type]++;System.out.println("features="+features.size()+" points="+totalPoints+" types="+Arrays.toString(counts));
        }finally{map.close();}
    }
}
