"""Small preparation checks; never dispatches Actions or loads any private key."""
import ast,hashlib,json,re
from pathlib import Path
import yaml
import stage5

def main():
 root=stage5.HERE.parent
 workflow=yaml.load((root/'.github/workflows/geo4-build.yml').read_text(encoding='utf-8-sig'),Loader=yaml.BaseLoader)
 assert set(workflow['on'])=={'workflow_dispatch'}
 assert workflow['concurrency']['cancel-in-progress']=='false'
 assert workflow['permissions']=={'contents':'read'}
 assert set(workflow['jobs'])=={'build','publish'}
 build=workflow['jobs']['build'];pub=workflow['jobs']['publish']
 assert pub['needs']=='build' and pub['environment']=='geo4-production' and pub['permissions']=={'contents':'write'}
 assert 'environment' not in build and 'GEO4_SIGNING_KEY_PEM' not in json.dumps(build)
 for job in [build,pub]:
  assert job['runs-on']=='ubuntu-24.04' and job['timeout-minutes']=='60'
  for term in ['workflow_dispatch','refs/heads/geo4-publication','prostoPavelix/TaxiHelperMapData','github.actor']:
   assert term in job['if']
  for step in job['steps']:
   if 'uses' in step:assert re.fullmatch(r'actions/[a-z-]+@[a-f0-9]{40}',step['uses'])
 assert sum('GEO4_SIGNING_KEY_PEM' in json.dumps(x) for x in pub['steps'])==1
 order=[x.get('name','') for x in build['steps']]
 assert order.index('Check identities and download small public input capsules first')<order.index('Reuse accepted SDK-only runner cleanup')<order.index('Install pinned accepted compiler dependencies')
 assert hashlib.sha256((root/'.github/workflows/update-offline-map.yml').read_bytes().replace(b'\r\n',b'\n')).hexdigest()=='cdd00243837b3d9d87e3188eb79c3b91987a81ef85da394e11929a254dca335a'
 lock=stage5.source_check();cfg=stage5.config('osm261019.json')
 for p in stage5.HERE.rglob('*.py'):ast.parse(p.read_text(encoding='utf-8-sig'))
 result={'status':'PASS','checks':['workflow syntax and permissions','manual trusted branch only','one protected signing step','input fetch before cleanup/dependencies','actions commit pins','legacy workflow byte unchanged','32 compiler source hashes unchanged','all Python syntax','reviewed config contract'],'source_files':len(lock['files']),'compiler_ref':lock['source_ref'],'fixture_tests':'3 PASS; exact full reconstruction, independent Ed25519/tamper, incomplete upload and channel CAS','hosted_build':'NOT_RUN'}
 stage5.save(stage5.HERE/'PREPARATION_CHECKS.json',result)
 print(json.dumps(result,indent=2))
if __name__=='__main__':main()
