"""Offline lossless geographic ADDR2 closure export. Never reads phone/personal data.

Only a new output directory is accepted. Originals are opened SQLite read-only.
Retains duplicates, original JSON bytes, IDs, source-coordinate evidence and stale links.
"""
import argparse
from contextlib import closing
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

FILTERS = {
    'objects': "source!='OSM'",
    'variants': "object_id IN (SELECT object_id FROM objects WHERE source!='OSM')",
    'candidates': "object_id IN (SELECT object_id FROM objects WHERE source!='OSM')",
    'locality_assertions': "object_id IN (SELECT object_id FROM objects WHERE source!='OSM')",
    'edges': "from_id IN (SELECT object_id FROM objects WHERE source!='OSM') OR to_id IN (SELECT object_id FROM objects WHERE source!='OSM')",
    'raw_records': '1',
    'archive_files': '1',
    'accounting': "object_id IN (SELECT object_id FROM objects WHERE source!='OSM')",
    'tokens': "candidate_id IN (SELECT c.candidate_id FROM candidates c JOIN objects o ON o.object_id=c.object_id WHERE o.source!='OSM')",
}

def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()

def ro(path):
    return sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)

def row_digest(db, table, predicate='1'):
    # All columns/order and duplicate multiplicity, not COUNT or DISTINCT alone.
    n = len(db.execute('PRAGMA table_info(' + table + ')').fetchall())
    query = 'SELECT * FROM ' + table + ' WHERE ' + predicate + ' ORDER BY ' + ','.join(str(i+1) for i in range(n))
    h = hashlib.sha256(); count = 0
    for row in db.execute(query):
        b = json.dumps(row, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        h.update(len(b).to_bytes(8, 'big')); h.update(b); count += 1
    return dict(rows=count, sha256=h.hexdigest())

def export(addr2, merged, raw, output):
    output.mkdir(parents=True, exist_ok=False)
    (output/'.gitignore').write_text('*\n', encoding='utf-8')
    target = output/'addr2-geographic.sqlite'; proofs = {}
    with closing(ro(addr2)) as src, closing(sqlite3.connect(target)) as dest:
        for table, predicate in FILTERS.items():
            sql = src.execute('SELECT sql FROM sqlite_master WHERE type=\'table\' AND name=?', (table,)).fetchone()[0]
            dest.execute(sql)
            columns = len(src.execute('PRAGMA table_info(' + table + ')').fetchall())
            dest.executemany('INSERT INTO ' + table + ' VALUES (' + ','.join('?' for _ in range(columns)) + ')', src.execute('SELECT * FROM '+table+' WHERE '+predicate))
            expected = row_digest(src, table, predicate); actual = row_digest(dest, table)
            if expected != actual: raise ValueError('ROW_VALUE_OR_MULTIPLICITY_LOSS:'+table)
            proofs[table] = actual
        dest.commit()
        if dest.execute('PRAGMA quick_check').fetchone()[0] != 'ok': raise ValueError('EXPORTED_SQLITE_CORRUPT')
        if dest.execute("SELECT COUNT(*) FROM objects WHERE source='OSM'").fetchone()[0]: raise ValueError('OSM_OBJECT_LEAK')
    files = []
    for src, name in [(merged, 'merged_all_sources.sqlite')] + [(p, 'raw/'+p.relative_to(raw).as_posix()) for p in sorted(raw.rglob('*')) if p.is_file()]:
        dst = output/name; dst.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(src, dst)
        expected = sha(src)
        if sha(dst) != expected: raise ValueError('COPIED_SOURCE_MISMATCH:'+name)
        files.append(dict(path=name, bytes=dst.stat().st_size, sha256=expected, original_path=src.as_posix()))
    files.append(dict(path=target.name, bytes=target.stat().st_size, sha256=sha(target)))
    result = dict(contract='GEO4_ADDITIONAL_INPUT_1', status='PASS', source_addr2_sha256=sha(addr2), tables=proofs, files=files,
                  links='Original links retained verbatim, historical OSM target identities NOT revalidated by export; compiler marks stale.',
                  exclusions='OSM-only objects and their candidates/tokens/accounting; geographic raw archive and all original file passports retained. No personal source paths accepted implicitly.')
    (output/'manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return result

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ['addr2', 'merged', 'raw', 'output']: p.add_argument('--'+name, type=Path, required=True)
    a = p.parse_args(); result = export(a.addr2, a.merged, a.raw, a.output)
    print(json.dumps(dict(status=result['status'], tables=result['tables'], bytes=sum(f['bytes'] for f in result['files'])), indent=2))
