"""One bounded fresh-process/cached-OS smoke of actual mobile disk API, no OS cache flush."""
from common import *
from reader import DiskReader
import time,statistics,platform,threading
import psutil

def full_query(reader,text):
 cursor=None;ids=[];pages=0
 while True:
  result=reader.lookup(text,cursor=cursor);pages+=1;ids.extend(x['cid'] for x in result['candidates'])
  if not result['has_more']:break
  cursor=result['continuation']
 return ids,pages

def run():
 with ro(OUT/'mobile.sqlite') as db:
  n=db.execute('SELECT COUNT(DISTINCT lookup_key) FROM postings').fetchone()[0]
  # Deterministic ordered103-key stratification: save only a query-set hash publicly.
  selected={round(i*(n-1)/102) for i in range(103)};queries=[key for i,(key,) in enumerate(db.execute('SELECT DISTINCT lookup_key FROM postings ORDER BY lookup_key')) if i in selected]
 dump(OUT/'PERFORMANCE_QUERIES_PRIVATE.json',queries)
 process=psutil.Process();baseline=process.memory_info().rss;peak=[baseline];stop=threading.Event()
 def sample():
  while not stop.wait(.005):peak[0]=max(peak[0],process.memory_info().rss)
 thread=threading.Thread(target=sample);thread.start()
 start=time.perf_counter();reader=DiskReader(OUT/'mobile.sqlite');first=reader.lookup(queries[0]);cold_ms=(time.perf_counter()-start)*1000
 detail_ms=None
 if first['candidates']:
  t=time.perf_counter();reader.detail(first['candidates'][0]['oid']);detail_ms=(time.perf_counter()-t)*1000
 latencies=[];rounds=[];expected={};maximum_pages=0;retrieved=0
 for turn in range(5):
  batch=[]
  for text in queries:
   t=time.perf_counter();ids,pages=full_query(reader,text);elapsed=(time.perf_counter()-t)*1000
   if text in expected:assert ids==expected[text]
   else:expected[text]=ids
   maximum_pages=max(maximum_pages,pages);retrieved+=len(ids);latencies.append(elapsed);batch.append(elapsed)
  rounds.append(dict(p50_ms=statistics.median(batch),max_ms=max(batch)))
 reader.close();stop.set();thread.join();peak[0]=max(peak[0],process.memory_info().rss)
 ordered=sorted(latencies);memory=process.memory_info()
 result=dict(status='ONE_BOUNDED_PC_SMOKE',environment=dict(platform=platform.platform(),python=platform.python_version(),logical_cpus=psutil.cpu_count(),physical_ram_bytes=psutil.virtual_memory().total),
  cold_definition='Fresh reader/SQLite connection in this Python process, OS page cache NOT cleared and likely warm after build/verifier; no physical cold-storage claim',
  first_open_plus_first_page_ms=cold_ms,first_lazy_detail_ms=detail_ms,warm_all_pages_lookup=dict(queries=len(queries),rounds=5,samples=len(latencies),p50_ms=statistics.median(latencies),p95_ms=ordered[int(.95*(len(ordered)-1))],max_ms=max(latencies),max_pages=maximum_pages,retrieved_postings=retrieved),
  process_rss=dict(baseline_bytes=baseline,sampled_peak_bytes=peak[0],increment_bytes=peak[0]-baseline,sampling_seconds=.005),sqlite_cache_limit_bytes=8*1024*1024,
  query_set_sha256=hashlib.sha256(js(queries).encode()).hexdigest(),same_results_all_rounds=True,
  components_bytes={p.name:p.stat().st_size for p in [OUT/'master.sqlite',OUT/'mobile.sqlite',OUT/'visual_roads.bin']},
  limits=['Not Android/Motorola','No comparison speedup ratio to different ADDR2 APIs','Lookup returns candidate IDs/status; detail and source point lazy; all pages included in warm query latency','Process RSS includes Python runtime; SQLite limit is configuration, not separately measured native cache occupancy'])
 dump(OUT/'PERFORMANCE.json',result);print(js(result),flush=True)

if __name__=='__main__':run()
