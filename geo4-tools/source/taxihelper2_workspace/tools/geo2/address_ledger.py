"""Independent address-specific unit accounting over sealed master/mobile.
Postal Visicom aliases are both aliases and address variants; no exporter ledger relabelling.
Full private ledger stays outside mobile, with actual local posting checks per expected point.
"""
from common import *
from verify import independent_key,candidate_id
import collections,time

def run():
 path=OUT/'ADDRESS_VARIANT_LEDGER.sqlite'
 assert not path.exists(),'Completed/private attempt preserved; do not overwrite'
 ledger=sqlite3.connect(path);ledger.execute('CREATE TABLE units(aid TEXT PRIMARY KEY,oid TEXT,source TEXT,role TEXT,disposition TEXT,reason TEXT)')
 counts=collections.defaultdict(collections.Counter);errors=collections.Counter()
 with ro(OUT/'master.sqlite') as master,ro(OUT/'mobile.sqlite') as phone:
  for aid,oid,role,text,source,kind in master.execute('SELECT a.aid,a.oid,a.role,a.text,o.source,o.kind FROM aliases a JOIN objects o ON o.oid=a.oid ORDER BY a.aid'):
   if kind!='ADR' and not role.startswith(('addr:','structured_address','contact:street','contact:housenumber','contact:city','contact:postcode')):continue
   key=independent_key(text);disposition='INDEXED' if key else 'EXCLUDED_WITH_REASON'
   observed=phone.execute('SELECT oid,role,text FROM aliases WHERE aid=?',(aid,)).fetchone()
   if observed!=(oid,role,text):errors['address_alias_not_locally_identical']+=1
   expected_points=[row[0] for row in master.execute('SELECT pid FROM points WHERE oid=? ORDER BY pid',(oid,))] or [None]
   if key:
    for pid in expected_points:
     cid=candidate_id(oid,pid)
     if not phone.execute('SELECT 1 FROM postings WHERE lookup_key=? AND cid=?',(key,cid)).fetchone():errors['address_point_posting_missing']+=1
    counts[source]['searchable_address_variants']+=1
   else:counts[source]['invalid_search_text_retained_locally']+=1
   counts[source]['address_variants_total']+=1
   ledger.execute('INSERT INTO units VALUES(?,?,?,?,?,?)',(aid,oid,source,role,disposition,'POSTAL_VISICOM_ALIAS_AND_OR_OSM_ADDRESS_FIELD; ALL_POINT_POSTINGS_CHECKED' if key else 'EMPTY_OR_NON_ALPHANUMERIC_TEXT_WITH_LOCAL_DETAIL'))
 ledger.commit()
 for source in counts:
  counts[source]['distinct_address_objects']=ledger.execute('SELECT COUNT(DISTINCT oid) FROM units WHERE source=?',(source,)).fetchone()[0]
 ledger.close()
 result=dict(status='PASS' if not errors else 'FAIL',errors=dict(errors),sources={k:dict(v) for k,v in counts.items()},ledger_sha256=sha(path),
  semantics='Visicom ADR labels/observed variants/hypotheses are independently counted as address variants; OSM addr/structured/contact fields separately count field variants, not independent buildings. All these units also have master alias IDs and mobile alias/candidate postings.',
  unexplained_omissions=0 if not errors else None)
 dump(OUT/'ADDRESS_COVERAGE.json',result);print(js(result),flush=True)
 assert not errors

if __name__=='__main__':run()
