"""PC-only derived proofs/aliases for one exact GEO and frozen sector revision.

Reads immutable existing GEO bytes. Never writes source data or contacts a device/network.
Run with bundled Python; dependencies reused from the existing GEO2 build.
"""
from pathlib import Path
import collections, hashlib, json, re, sqlite3, struct, sys, unicodedata, zlib

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'MAP_OSM_Visicom/.geo2-deps'))
from shapely.geometry import Polygon, shape

GEO = ROOT / 'MAP_OSM_Visicom/reports/geo2_20261016'
SECTORS = ROOT / 'taxihelper2_workspace/app/src/main/packaged-assets/lutsk-sectors.gpkg'
SECTOR_SHA = '19a75b5a16f708c400cefafe8189519936a5545e73142bb8bd834bf065a9709e'
VERSION = 'RESOLVE1_COMPLETE_GEOMETRY_SOURCE_ALIAS_1'

def sha(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()

def norm(s):
    return ' '.join(''.join(c if c.isalnum() else ' ' for c in unicodedata.normalize('NFKC', s).casefold()).split())

def supported(role):
    # Semicolon components retain the source field role; no independent vote is implied.
    role = role.removesuffix(':semicolon_component')
    return role in {'structured_address', 'structured_address_with_city', 'VISICOM_MERGED_LABEL', 'VISICOM_OBSERVED_LABEL', 'VISICOM_PRESERVED_VARIANT', 'name', 'alt_name', 'official_name', 'short_name', 'old_name', 'loc_name'} or role.startswith('name:')

def variants(text, allow_address_format=True):
    """Formatting/type order only; no translation, house deletion or guessed locality."""
    key = norm(text); out = {key}
    if not allow_address_format: return out
    types = r'(?:вулиця|вул|улица|ул|street|проспект|просп|avenue|провулок|пров|переулок|бульвар|бульв)'
    m = re.match(r'^(' + types + r') (.+)$', key)
    if m:
        out.add(m[2]); out.add(m[2] + ' ' + m[1])
    # Join only a terminal single-letter house suffix. Never alter slash/corpus identity.
    for k in list(out):
        out.add(re.sub(r'(?<=\d) ([a-zа-яіїєґ])$', r'\1', k))
    return {v for v in out if v}

def frozen_zones():
    assert sha(SECTORS) == SECTOR_SHA
    keys = (ROOT / 'taxihelper2_workspace/app/src/main/java/com/example/bolthelper/sep1/S1SectorUniverse.kt').read_text(encoding='utf-8-sig')
    ids = {int(fid): key for key, fid in re.findall(r'(sector:qgis-(\d+)-[a-f0-9-]{36})', keys)}
    db = sqlite3.connect(SECTORS.resolve().as_uri() + '?mode=ro', uri=True)
    zones = []
    for fid, blob in db.execute('SELECT fid,geometry FROM sectors ORDER BY fid'):
        off = 8 + {0:0, 1:32, 2:48, 3:48, 4:64}[(blob[3] >> 1) & 7]
        endian = '<' if blob[off] else '>'
        typ, rings, count = struct.unpack_from(endian + 'III', blob, off + 1)
        # Match production first-ring matcher exactly, including ignoring other rings.
        assert typ == 3 and rings >= 1
        ps = [struct.unpack_from(endian + 'dd', blob, off + 13 + 16*i) for i in range(count)]
        p = Polygon(ps); assert p.is_valid and not p.is_empty
        zones.append((ids[fid], p))
    db.close(); assert len(zones) == 41
    def matcher_area(z):
        ps=list(z[1].exterior.coords)[:-1]
        return abs(sum(ps[i][0]*ps[(i+1)%len(ps)][1]-ps[(i+1)%len(ps)][0]*ps[i][1] for i in range(len(ps))))/2
    assert [z[0] for z in sorted(zones,key=matcher_area)] == [z[0] for z in sorted(zones,key=lambda z:z[1].area)], 'FROZEN_AREA_PRECEDENCE_DISAGREEMENT'
    return effective_zones(zones)

def requires_street_geometry(oid,tags):
    # A bus-stop node is a point POI, not proof of an entire named road.
    return oid.startswith(('OSM:w:','OSM:r:')) and 'highway' in tags and not tags.get('addr:housenumber')

def effective_zones(zones):
    # ZoneMatcher chooses smallest original area, stable input order on equal areas.
    ordered = sorted(zones, key=lambda z: z[1].area)
    claimed = None; result = []
    for key, p in ordered:
        cell = p if claimed is None else p.difference(claimed)
        result.append((key, cell))
        claimed = p if claimed is None else claimed.union(p)
    return result

def proof(geom, status, cells):
    if status != 'COMPLETE' or geom is None: return None, 'INCOMPLETE_GEOMETRY'
    if geom.is_empty or not geom.is_valid: return None, 'INVALID_OR_EMPTY_GEOMETRY'
    if geom.geom_type not in {'Polygon','MultiPolygon','LineString','MultiLineString','Point','MultiPoint'}:
        return None, 'UNSUPPORTED_GEOMETRY'
    # Full geometry (segments, interiors, holes and multipart), never bbox/vertices/centroid.
    # Strict boundary abstention avoids claiming compatibility at ray-cast boundary ties.
    for key, cell in cells:
        if not cell.is_empty and cell.covers(geom) and cell.boundary.disjoint(geom):
            return key, 'COMPLETE_GEOMETRY_SECTOR_ONLY'
    return None, 'GEOMETRY_CROSS_BOUNDARY_OR_OUTSIDE'

def compile_package(destination):
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / 'evidence.sqlite'; assert not target.exists(), 'NEW_DESTINATION_REQUIRED'
    receipt = json.loads((GEO/'MOBILE_COMPLETE.json').read_text(encoding='utf-8-sig'))
    # Explicit PC derivation verifies its input once. No Android/card/startup/backup scan.
    source = GEO/'mobile.sqlite'; assert source.stat().st_size == receipt['bytes']
    assert sha(source) == receipt['sha256'], 'COMPILER_INPUT_SHA_MISMATCH'
    db = sqlite3.connect(source.resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
    assert db.execute("SELECT value FROM meta WHERE key='package_revision'").fetchone()[0] == receipt['revision']
    out = sqlite3.connect(target)
    out.executescript('''CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE geometry_proofs(oid TEXT PRIMARY KEY,sector TEXT,reason TEXT NOT NULL,outside_lutsk INTEGER NOT NULL,requires_geometry INTEGER NOT NULL);
CREATE TABLE aliases(lookup_key TEXT NOT NULL,cid TEXT NOT NULL,aid TEXT NOT NULL,role TEXT NOT NULL,PRIMARY KEY(lookup_key,cid)) WITHOUT ROWID;''')
    cells = frozen_zones(); counts = collections.Counter()
    row = db.execute("SELECT payload,status FROM geometry WHERE oid='OSM:r:1951964'").fetchone()
    lutsk = shape(json.loads(zlib.decompress(row[0]))) if row and row[1]=='COMPLETE' else None
    for oid, payload, status in db.execute('SELECT g.oid,g.payload,g.status FROM geometry g WHERE EXISTS(SELECT 1 FROM candidates c WHERE c.oid=g.oid) ORDER BY g.oid'):
        geom = shape(json.loads(zlib.decompress(payload))) if payload else None
        sector, reason = proof(geom, status, cells)
        outside = int(lutsk is not None and geom is not None and geom.is_valid and status=='COMPLETE' and lutsk.disjoint(geom))
        out.execute('INSERT INTO geometry_proofs VALUES(?,?,?,?,0)', (oid, sector, reason, outside)); counts[reason] += 1
    street_objects=set()
    for oid, payload in db.execute('SELECT oid,payload FROM details ORDER BY oid'):
        tags = json.loads(zlib.decompress(payload)).get('tags', {})
        if requires_street_geometry(oid,tags):
            street_objects.add(oid)
            out.execute('INSERT INTO geometry_proofs VALUES(?,NULL,?,0,1) ON CONFLICT(oid) DO UPDATE SET requires_geometry=1', (oid, 'STREET_REQUIRES_COMPLETE_GEOMETRY'))
    # All candidate postings are preserved. Added keys retain aid+role; NULL points are not pruned.
    for aid, oid, role, text in db.execute('SELECT aid,oid,role,text FROM aliases ORDER BY aid'):
        if not supported(role): continue
        cids = [x[0] for x in db.execute('SELECT cid FROM alias_candidates WHERE aid=? ORDER BY cid', (aid,))]
        typed_address=role.startswith('structured_address') or role in {'VISICOM_MERGED_LABEL','VISICOM_OBSERVED_LABEL','VISICOM_PRESERVED_VARIANT'}
        for key in sorted(variants(text,typed_address or oid in street_objects)):
            for cid in cids:
                if db.execute('SELECT 1 FROM postings WHERE lookup_key=? AND cid=?', (key,cid)).fetchone(): continue
                out.execute('INSERT OR IGNORE INTO aliases VALUES(?,?,?,?)', (key,cid,aid,role)); counts['SOURCE_ALIAS_INSERT_ATTEMPTS'] += 1
    counts['ADDED_SOURCE_ALIAS_POSTINGS'] = out.execute('SELECT COUNT(*) FROM aliases').fetchone()[0]
    for k,v in {'contract':VERSION,'geo_sha256':receipt['sha256'],'geo_version':receipt['revision'],'sector_sha256':SECTOR_SHA,'normalizer':'GEO2_NFKC_CASEFOLD_ALNUM_V1'}.items(): out.execute('INSERT INTO meta VALUES(?,?)',(k,v))
    out.commit(); assert out.execute('PRAGMA quick_check').fetchone()[0]=='ok';out.close();db.close()
    descriptor = dict(contract=VERSION,geo_sha256=receipt['sha256'],geo_version=receipt['revision'],sector_sha256=SECTOR_SHA,sha256=sha(target),bytes=target.stat().st_size,compiler_sha256=sha(Path(__file__)),counts=dict(counts))
    (destination/'descriptor.json').write_text(json.dumps(descriptor,indent=2)+'\n')
    print(json.dumps(descriptor,indent=2))

if __name__ == '__main__':
    assert len(sys.argv)==2, 'Supply a new output directory; no overwrite'
    compile_package(Path(sys.argv[1]))
