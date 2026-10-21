"""Inventory name-bearing source tag types independently of export counts. No source writes."""
from common import *
import collections

def run():
 counts=collections.defaultdict(collections.Counter);unknown=[]
 with ro(OUT/'master.sqlite') as db:
  for tags_s, in db.execute("SELECT tags FROM objects WHERE source='OSM' AND tags LIKE '%name%'"):
   tags=json.loads(tags_s);selected={k for k,v in search_texts(tags)}
   for field,value in tags.items():
    if 'name' not in field:continue
    if field in selected:status='SEARCHABLE_SOURCE_NAME'
    elif field.startswith('source:'):status='LOCAL_DETAIL_ONLY_SOURCE_ATTRIBUTION'
    elif field.startswith('noname'):status='LOCAL_DETAIL_ONLY_BOOLEAN_FLAG'
    elif field=='geonames:id':status='LOCAL_DETAIL_ONLY_EXTERNAL_IDENTIFIER'
    else:status='UNEXPLAINED';unknown.append(field)
    counts[status][field]+=1
 result=dict(status='PASS' if not unknown else 'FAIL',fields={k:dict(v) for k,v in counts.items()},unexplained_fields=sorted(set(unknown)),method='Inventory of all name-bearing tag keys in selected master, checked against independently verified source-to-alias extraction; values remain private; non-search metadata retained locally')
 dump(OUT/'NAME_FIELD_AUDIT.json',result);assert not unknown
 print('Name field inventory PASS;',len(counts['SEARCHABLE_SOURCE_NAME']),'searchable field types',flush=True)

if __name__=='__main__':run()
