"""Explicit-input GEO4 offline build driver reusing unchanged GEO2/RESOLVE1 algorithms.

No acquisition, phone, publishing, display generation or source mutation. Each invocation
runs one phase in a separate process; metric receipts survive phase failure.
Configure a new private job with prepare.py first. No implicit 'latest' inputs.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sys
import threading
import time
import traceback

ROOT=Path(__file__).resolve().parents[3]

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''):h.update(b)
    return h.hexdigest()

def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def toolchain():
    if platform.system()=='Windows':sys.path.insert(0,str(ROOT/'MAP_OSM_Visicom/.geo2-deps'))
    import zlib,shapely
    return dict(python=platform.python_version(),sqlite=__import__('sqlite3').sqlite_version,
                zlib=zlib.ZLIB_RUNTIME_VERSION,geos=shapely.geos_version_string,
                packages={n:importlib.metadata.version(n) for n in ['osmium','shapely','numpy','psutil']})

def configure(config):
    cfg=json.loads(config.read_text(encoding='utf-8'))
    for entry in cfg['pins']:
        if sha(Path(entry['path']))!=entry['sha256']:raise ValueError('PIN_MISMATCH:'+entry['role'])
    sys.path.insert(0,str(ROOT/'taxihelper2_workspace/tools/geo2'))
    import common
    # GEO2 imports no binary dependencies until after these explicit overrides.
    legacy_deps=str(ROOT/'MAP_OSM_Visicom/.geo2-deps')
    if platform.system()!='Windows':sys.path[:]=[p for p in sys.path if p!=legacy_deps]
    for key in ['OUT','SOURCE','ADDR2','MERGED']:setattr(common,key,Path(cfg[key]))
    common.aoi=lambda:json.loads(Path(cfg['aoi']).read_text(encoding='utf-8'))['features'][0]['geometry']
    if 'toolchain' in cfg and cfg['toolchain']!=toolchain():raise ValueError('TOOLCHAIN_LOCK_MISMATCH')
    return cfg,common

def run(config,phase):
    total_start=time.perf_counter();cfg,common=configure(config);pin_seconds=time.perf_counter()-total_start
    import psutil
    out=common.OUT;receipt=out/('PHASE_'+phase+'.json')
    if receipt.exists():raise FileExistsError('Phase receipt exists; preserve attempt: '+str(receipt))
    proc=psutil.Process();stop=threading.Event();rss=[0];disk=[0];samples=[0]
    def sample():
        while not stop.is_set():
            try:
                rss[0]=max(rss[0],sum(p.memory_info().rss for p in [proc]+proc.children(recursive=True) if p.is_running()))
                disk[0]=max(disk[0],sum(p.stat().st_size for p in out.rglob('*') if p.is_file()))
                samples[0]+=1
            except (OSError,psutil.Error):pass
            stop.wait(.1)
    thread=threading.Thread(target=sample,daemon=True);thread.start();start=time.perf_counter();status='FAIL';error=None
    try:
        if phase=='extract':
            import extract;extract.run()
        elif phase=='build':
            import build;build.run()
        elif phase=='supplement':
            import supplement;supplement.run()
        elif phase=='verify':
            import verify;verify.run()
            import name_fields;name_fields.run()
            import address_ledger;address_ledger.run()
        elif phase=='sidecar':
            sys.path.insert(0,str(ROOT/'taxihelper2_workspace/tools/resolve1'))
            import compile_evidence
            compile_evidence.GEO=out
            compile_evidence.compile_package(out/'resolve1')
            descriptor=json.loads((out/'resolve1/descriptor.json').read_text(encoding='utf-8'))
            if descriptor['geo_sha256']!=sha(out/'mobile.sqlite'):raise ValueError('SIDECAR_BASE_BINDING')
        else:raise ValueError('UNKNOWN_PHASE')
        status='PASS'
    except BaseException as exc:
        error=type(exc).__name__+': '+str(exc);traceback.print_exc();raise
    finally:
        stop.set();thread.join()
        write(receipt,dict(status=status,error=error,phase=phase,elapsed_seconds=time.perf_counter()-start,
              pin_validation_seconds=pin_seconds,total_seconds=time.perf_counter()-total_start,
              native_process_peak_wset_bytes=getattr(proc.memory_info(),'peak_wset',None),
              sampled_process_tree_rss_peak=rss[0],sampled_job_disk_peak=disk[0],sample_interval_seconds=.1,samples=samples[0],
              platform=platform.platform(),python=sys.version,sqlite=__import__('sqlite3').sqlite_version,
              config_sha256=sha(config),limit='Sampling may miss shorter peaks. Disk counts this candidate directory including retained checkpoints; immutable source input storage reported separately.'))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True);p.add_argument('--phase',choices=['extract','build','supplement','verify','sidecar'],required=True)
    a=p.parse_args();run(a.config,a.phase)
