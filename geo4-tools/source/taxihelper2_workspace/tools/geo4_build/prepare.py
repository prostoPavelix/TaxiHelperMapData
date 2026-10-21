"""Seal explicit local inputs for a NEW offline GEO4 candidate. No network/source writes.

Reuses the bounded historical supplement with its distinct epochs. New source dates require
a separate compatible supplement/closure review, not relabeling old captures as same-epoch.
"""
import argparse
import json
from pathlib import Path
import shutil
from compiler import ROOT,sha,write,toolchain

def prepare(source,additional,supplement,output,aoi,dependencies=None):
    if dependencies is None:raise ValueError('EXPLICIT_PROVENANCE_CAPSULE_REQUIRED')
    if output.exists():raise FileExistsError('NEW_OUTPUT_REQUIRED')
    manifest=json.loads((additional/'manifest.json').read_text(encoding='utf-8'))
    if manifest['status']!='PASS':raise ValueError('ADDITIONAL_INPUT_NOT_VERIFIED')
    pins=[]
    def pin(path,role):
        pins.append(dict(path=str(path.resolve()),role=role,bytes=path.stat().st_size,sha256=sha(path)))
    for f in manifest['files']:
        p=additional/f['path']
        if p.stat().st_size!=f['bytes'] or sha(p)!=f['sha256']:raise ValueError('INPUT_CHANGED:'+f['path'])
    output.mkdir(parents=True);(output/'.gitignore').write_text('*\n',encoding='utf-8')
    shutil.copytree(supplement,output/'supplement')
    pin(source,'dated_osm');pin(aoi,'aoi');pin(additional/'manifest.json','additional_manifest')
    # Raw archives remain unchanged and hash-bound by the verified additional manifest.
    for f in manifest['files']:pins.append(dict(path=str((additional/f['path']).resolve()),role='additional:'+f['path'],bytes=f['bytes'],sha256=f['sha256']))
    for p in sorted((ROOT/'taxihelper2_workspace/tools/geo2').glob('*.py')):pin(p,'compiler:'+p.name)
    for name in ['compiler.py','prepare.py']:pin(Path(__file__).parent/name,'driver:'+name)
    pin(ROOT/'taxihelper2_workspace/tools/geo2/requirements.txt','dependency_constraints')
    if dependencies:
        passport=json.loads((dependencies/'manifest.json').read_text(encoding='utf-8'))
        if passport['status']!='PASS' or passport['additional_manifest_sha256']!=sha(additional/'manifest.json'):raise ValueError('PROVENANCE_CLOSURE_BINDING')
        pin(dependencies/'manifest.json','provenance_manifest')
        for row in passport['references']:
            name=row['portable_location']
            p=additional/name.removeprefix('additional/') if row['reused_existing_copy'] else dependencies/name.removeprefix('dependencies/')
            if sha(p)!=row['sha256']:raise ValueError('PROVENANCE_FILE_CHANGED')
            pin(p,'provenance:'+name)
    for p in [ROOT/'taxihelper2_workspace/tools/geo2/INCLUSION_POLICY.json',ROOT/'taxihelper2_workspace/tools/resolve1/compile_evidence.py',ROOT/'taxihelper2_workspace/app/src/main/packaged-assets/lutsk-sectors.gpkg',ROOT/'docs/taxihelper_2_0/geo1/AOI_EVIDENCE.json']:pin(p,'contract:'+p.name)
    for p in [ROOT/'taxihelper2_workspace/tools/locality_probe/analyze.py',ROOT/'taxihelper2_workspace/tools/addr2/core.py',ROOT/'taxihelper2_workspace/app/src/main/java/com/example/bolthelper/sep1/S1SectorUniverse.kt']:pin(p,'compiler_dependency:'+p.name)
    for p in sorted((output/'supplement').glob('*')):pin(p,'supplement:'+p.name)
    cfg=dict(contract='GEO4_PC_COMPILER_INPUT_1',OUT=str(output.resolve()),SOURCE=str(source.resolve()),ADDR2=str((additional/'addr2-geographic.sqlite').resolve()),MERGED=str((additional/'merged_all_sources.sqlite').resolve()),aoi=str(aoi.resolve()),pins=pins,toolchain=toolchain(),
             note='Offline only. Original compiler algorithms, frozen sector/AOI. No extend_names repair; clean V2 extraction includes all name fields. Supplement epochs remain independent.')
    write(output/'CONFIG.json',cfg);return cfg

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['source','additional','supplement','output']:p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--aoi',type=Path,default=ROOT/'docs/taxihelper_2_0/geo1/AOI_PROPOSAL.geojson')
    p.add_argument('--dependencies',type=Path,required=True)
    a=p.parse_args();prepare(a.source,a.additional,a.supplement,a.output,a.aoi,a.dependencies)
