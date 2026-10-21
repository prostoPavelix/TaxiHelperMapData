"""Stdlib-only SDK cleanup and resource sampling reused from accepted Linux1 approach."""
import json,os,platform,shutil,subprocess,sys,time
from pathlib import Path
def write(p,j):
 tmp=p.with_suffix('.next');tmp.write_text(json.dumps(j,indent=2),encoding='utf-8');tmp.replace(p)
def watch(root,worker):
 initial=shutil.disk_usage(root).free;started=time.monotonic();j={'initial_free_bytes':initial,'minimum_free_bytes':initial,'peak_additional_FS_bytes':0,'sampled_runner_tree_RSS_bytes':0,'interval_seconds':1,'scope':'Runner.Worker tree RSS, shared pages included; sampling may miss short peaks; FS includes background/dependencies','phases':{},'samples':0}
 while time.monotonic()-started<7200:
  free=shutil.disk_usage(root).free;parents={};rss={}
  for p in Path('/proc').iterdir():
   if not p.name.isdigit():continue
   try:
    vals={line.split(':',1)[0]:line.split(':',1)[1].strip() for line in (p/'status').read_text().splitlines() if ':' in line};parents[int(p.name)]=int(vals['PPid']);rss[int(p.name)]=int(vals.get('VmRSS','0 kB').split()[0])*1024
   except (OSError,ValueError,KeyError):continue
  tree={worker}
  while True:
   more={p for p,v in parents.items() if v in tree and p not in tree}
   if not more:break
   tree.update(more)
  memory=sum(rss.get(p,0) for p in tree);phase='SETUP'
  try:phase=json.loads((root/'phase.json').read_text())['phase']
  except (OSError,ValueError,KeyError):pass
  j['minimum_free_bytes']=min(j['minimum_free_bytes'],free);j['peak_additional_FS_bytes']=max(j['peak_additional_FS_bytes'],initial-free);j['sampled_runner_tree_RSS_bytes']=max(j['sampled_runner_tree_RSS_bytes'],memory);j['samples']+=1;j['elapsed_seconds']=time.monotonic()-started
  item=j['phases'].setdefault(phase,{'minimum_free_bytes':free,'sampled_RSS_bytes':0,'first_sample_seconds':time.monotonic()-started,'last_sample_seconds':0});item['minimum_free_bytes']=min(item['minimum_free_bytes'],free);item['sampled_RSS_bytes']=max(item['sampled_RSS_bytes'],memory);item['last_sample_seconds']=time.monotonic()-started
  write(root/'RESOURCE_RECEIPT.json',j)
  if (root/'watch.stop').exists():break
  time.sleep(1)
def start(root):
 root.mkdir(parents=True,exist_ok=True);pid=os.getpid();worker=0
 while pid>1:
  p=Path('/proc')/str(pid)
  if (p/'comm').read_text().strip()=='Runner.Worker':worker=pid;break
  pid=int((p/'stat').read_text().rsplit(')',1)[1].split()[1])
 if not worker:raise ValueError('RUNNER_WORKER_NOT_FOUND')
 proc=subprocess.Popen([sys.executable,__file__,'watch',str(root),str(worker)],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
 (root/'watch.pid').write_text(str(proc.pid))
def cleanup(root):
 if platform.system()!='Linux' or os.environ.get('ImageOS')!='ubuntu24':raise ValueError('DISPOSABLE_UBUNTU24_ONLY')
 sdk=Path('/usr/local/lib/android/sdk');free=shutil.disk_usage(root).free
 if sdk.exists():
  if sdk.is_symlink() or not sdk.is_dir() or sdk.resolve()!=sdk or sdk.stat().st_dev!=root.stat().st_dev:raise ValueError('SDK_SAFE_PATH')
  subprocess.run(['sudo','-n','rm','-rf','--one-file-system','--',str(sdk)],check=True)
 write(root/'SDK_CLEANUP.json',{'scope':'ONLY_ANDROID_SDK','free_before':free,'free_after':shutil.disk_usage(root).free})
def finish(root):
 (root/'watch.stop').touch();time.sleep(1.5)
 if (root/'RESOURCE_RECEIPT.json').exists():
  j=json.loads((root/'RESOURCE_RECEIPT.json').read_text())
  if j['minimum_free_bytes']<2*1024**3:raise ValueError('RESERVE_VIOLATED')
def admit(root,mode):
 free=shutil.disk_usage(root).free;minimum=(14 if mode=='build' else 6)*1024**3
 memory=os.sysconf('SC_PHYS_PAGES')*os.sysconf('SC_PAGE_SIZE');cg=Path('/sys/fs/cgroup/memory.max')
 if cg.is_file() and cg.read_text().strip().isdigit():memory=min(memory,int(cg.read_text()))
 write(root/'ADMISSION.json',{'mode':mode,'free_bytes':free,'required_free_bytes':minimum,'effective_memory_limit':memory,'reserve_bytes':2*1024**3})
 if free<minimum or memory<6*1024**3:raise ValueError('RESOURCE_ADMISSION')
if __name__=='__main__':
 mode=sys.argv[1];root=Path(sys.argv[2])
 if mode=='watch':watch(root,int(sys.argv[3]))
 elif mode=='start':start(root)
 elif mode=='cleanup':cleanup(root)
 elif mode=='finish':finish(root)
 elif mode=='admit':admit(root,sys.argv[3])
