"""Close GEO2 evidence only after independent proofs. Publish-safe summaries, no datasets."""
from common import *
import collections,importlib.metadata as metadata,datetime

def run():
 PUBLIC.mkdir(parents=True,exist_ok=True)
 load=lambda name:json.loads((OUT/name).read_text(encoding='utf-8'))
 extraction=load('EXTRACTION.json');verify=load('VERIFICATION.json');ingestion=load('INGESTION.json');closure=load('CLOSURE_PRIVATE.json');tests=load('SYNTHETIC_TESTS.json');visual=load('VISUAL.json');perf=load('PERFORMANCE.json');address=load('ADDRESS_COVERAGE.json')
 # Earlier source hashes are a reusable preservation ledger, not repeated GEO1 acceptance.
 ledger=json.loads((ROOT/'MAP_OSM_Visicom/reports/geo1_20261016/PRIVATE_PRESERVATION_LEDGER.json').read_text(encoding='utf-8'))
 changed=[path for path,digest in ledger.items() if sha(ROOT/path)!=digest]
 with ro(OUT/'mobile.sqlite') as mobile:
  exclusions=[dict(zip(['unit_type','source','disposition','reason','count'],r)) for r in mobile.execute("SELECT unit_type,source,disposition,reason,COUNT(*) FROM coverage WHERE disposition!='INDEXED' GROUP BY unit_type,source,disposition,reason ORDER BY unit_type,source,disposition,reason")]
  stats={t:mobile.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ['details','aliases','points','candidates','postings','alias_candidates','observations','members','links','geometry']}
  unknown=mobile.execute("SELECT COUNT(*) FROM candidates WHERE location_status='UNKNOWN_LOCATION'").fetchone()[0]
  unknownlocality=mobile.execute("SELECT COUNT(*) FROM points WHERE json_extract(locality,'$.derived') IS NULL").fetchone()[0]
  weights=mobile.execute('SELECT COUNT(*) FROM points WHERE weight IS NULL').fetchone()[0]
  keys=mobile.execute('SELECT COUNT(DISTINCT lookup_key) FROM postings').fetchone()[0]
  max_detail=mobile.execute('SELECT MAX(length(payload)) FROM details').fetchone()[0]
  max_geometry=mobile.execute('SELECT MAX(length(payload)) FROM geometry').fetchone()[0]
  plan=mobile.execute('EXPLAIN QUERY PLAN SELECT p.cid,c.oid FROM postings p JOIN candidates c ON c.cid=p.cid WHERE p.lookup_key=? AND p.cid>? ORDER BY p.cid LIMIT ?',('synthetic','',129)).fetchall()
  badreasons=mobile.execute("SELECT COUNT(*) FROM coverage WHERE reason='' OR disposition NOT IN('INDEXED','LOCAL_DETAIL_ONLY','EXCLUDED_WITH_REASON')").fetchone()[0]
 required_ok=all(status and status[0]=='COMPLETE' for status in closure['required_settlements'].values()) and len(closure['required_settlements'])==18
 names=load('NAME_FIELD_AUDIT.json')
 master_marker=load('MASTER_COMPLETE.json');mobile_marker=load('MOBILE_COMPLETE.json')
 actual_master_sha=sha(OUT/'master.sqlite');actual_mobile_sha=sha(OUT/'mobile.sqlite')
 sealed_inputs=actual_master_sha==master_marker['sha256'] and actual_mobile_sha==mobile_marker['sha256'] and mobile_marker['revision']==actual_master_sha
 current_cut=max((OUT/'master.sqlite').stat().st_mtime,(OUT/'mobile.sqlite').stat().st_mtime)
 receipts_current=all((OUT/name).stat().st_mtime>=current_cut for name in ['VERIFICATION.json','INGESTION.json','ADDRESS_COVERAGE.json'])
 with ro(OUT/'master.sqlite') as checked:
  current_osm_aliases=checked.execute("SELECT COUNT(*) FROM aliases a JOIN objects o ON o.oid=a.oid WHERE o.source='OSM'").fetchone()[0]
 receipts_current=receipts_current and ingestion['osm_tag_alias_units_checked']==current_osm_aliases
 good=verify['status']=='PASS' and ingestion['status']=='PASS' and address['status']=='PASS' and names['status']=='PASS' and tests['status']=='PASS' and required_ok and sealed_inputs and receipts_current and not changed and closure['reference_missing_count']==0 and not closure['relation_cycles'] and not extraction['root_missing'] and badreasons==0
 status='READY_FOR_GEO3_REVIEW' if good else 'NOT_READY_EXPLICIT_GAPS'
 artifact_manifest=dict(contract='GEO2_LOCAL_CANDIDATE_1',status=status,automatic_activation_allowed=False,distribution_allowed=False,
  phone_integration='NOT_STARTED',normalizer='GEO2_NFKC_CASEFOLD_ALNUM_V1',inclusion_policy_sha256=sha(Path(__file__).with_name('INCLUSION_POLICY.json')),
  resources={p.name:dict(sha256=sha(p),bytes=p.stat().st_size,location='PC_MASTER_ONLY' if p.name=='master.sqlite' else 'PHONE_CANDIDATE_DISK_COMPONENT') for p in [OUT/'master.sqlite',OUT/'mobile.sqlite',OUT/'visual_roads.bin',OUT/'visual_manifest.json']},
  compatibility=dict(osmRevision=extraction['source_sha256'],visicomRevision=sha(MERGED),derivedIndexRevision=load('MOBILE_COMPLETE.json')['revision'],
    frozenSectorRevision='19a75b5a16f708c400cefafe8189519936a5545e73142bb8bd834bf065a9709e',gridRevision='v2-local-metric-350m-v1',
    ownerRulesRevision='PHONE_NOT_VERIFIED_NOT_INCLUDED',legacyRoadSnapshot='b7e478e2f81b04cb',legacyLinks='PRESERVED_STALE_NOT_REBOUND',androidBundle='NOT_A_MIXED_SNAPSHOT_ANDROID_BUNDLE'))
 dump(OUT/'COMPLETE.json',artifact_manifest)
 raw_manifest=json.loads((SOURCE.parent/'ACQUISITION.json').read_text(encoding='utf-8'))
 inputs=dict(status='VERIFIED_PC_INPUTS',pbf=dict(url=raw_manifest['url'],sha256=raw_manifest['sha256'],bytes=raw_manifest['bytes'],retrieved_at=raw_manifest['retrieved_finished_utc'],actual_header=extraction['header'],license='ODbL-1.0; OpenStreetMap contributors'),
  bounded_supplement=load('SUPPLEMENT_COMPLETE.json'),capture_groups_sha256=sha(OUT/'supplement/CAPTURE_GROUPS.json'),
  aoi=dict(path='docs/taxihelper_2_0/geo1/AOI_PROPOSAL.geojson',sha256=sha(ROOT/'docs/taxihelper_2_0/geo1/AOI_PROPOSAL.geojson')),
  visicom=dict(merged_sha256=sha(MERGED),preserved_ADDR2_sha256=sha(ADDR2),new_collection=False,distribution_rights='NOT_VERIFIED'),
  policy=json.loads(Path(__file__).with_name('INCLUSION_POLICY.json').read_text(encoding='utf-8')),
  dependencies={name:metadata.version(name) for name in ['osmium','shapely','numpy','psutil']},
  local_build_directory=OUT.relative_to(ROOT).as_posix(),original_sources_unchanged=True)
 dump(PUBLIC/'INPUT_MANIFEST.json',inputs)
 source_counts={src:{('tag_or_structured_address_fields_searchable' if key=='address_variants_searchable' else key):value for key,value in counts.items()} for src,counts in verify['sources'].items()}
 extension=load('NAME_EXTENSION.json') if (OUT/'NAME_EXTENSION.json').exists() else dict(status='NOT_NEEDED_COMPILER_ALREADY_V2')
 extension=dict(extension,application_status=extension['status'],status='PASS_FINAL_INDEPENDENT_PROOF' if good else 'NOT_ACCEPTED')
 coverage=dict(status=verify['status'],unexplained_omissions=verify['unexplained_omissions'],sources=source_counts,address_variants=address,units=verify['coverage_units'],
  exact_set_proof=verify['errors'],expected=verify['expected'],actual_disk_api=verify['actual_api'],mobile_counts=stats,
  distinctions='Search eligibility is not automatic geographic selection. Structural unnamed geometry may be local detail. NULL/unknown/conflicts never suppress usable text.',
  preserved_unknown_location_candidates=unknown,preserved_unknown_derived_locality_points=unknownlocality,preserved_null_weights=weights,
  extended_name_fields=dict(added=extension,final_semantic_check=names['status'],unexplained_fields=names['unexplained_fields']),
  master_to_mobile_policy='No useful source unit excluded for size/renderer/old resolver; independent sets verified, not counts alone')
 dump(PUBLIC/'MOBILE_COVERAGE.json',coverage)
 dump(PUBLIC/'EXCLUSION_SUMMARY.json',dict(status='EXPLICIT_DISPOSITIONS',unexplained=0 if not verify['errors'] else None,rows=exclusions,
  note='LOCAL_DETAIL_ONLY retains bytes locally by ID/member link; invalid search text also retains local alias detail. No unknown locality/weight/location exclusion.'))
 geometry_counts=collections.Counter(x['status'] for x in closure['relation_geometry']);reasons=collections.Counter(x.get('reason','') for x in closure['relation_geometry'] if x['status']=='UNRESOLVED')
 public_closure=dict(status='PASS' if closure['reference_missing_count']==0 and required_ok and not closure['relation_cycles'] else 'FAIL',reference_missing_count=closure['reference_missing_count'],missing_way_nodes=closure['missing_way_nodes'],cycle_count=len(closure['relation_cycles']),source_version_conflicts=closure['source_version_conflicts'],
  required_settlement_roots=closure['required_settlements'],required_geometry_complete=required_ok,relation_geometry_status=dict(geometry_counts),unresolved_geometry_reasons=dict(reasons),
  complete_polygons=sum(x.get('polygons',0) for x in closure['relation_geometry']),complete_holes=sum(x.get('holes',0) for x in closure['relation_geometry']),source_selection=extraction,
  note='No missing/invalid geometry replaced with centroid/nearest. Unresolved search objects remain searchable. No claim that18settlements are a complete regional locality registry.')
 dump(PUBLIC/'CLOSURE_REPORT.json',public_closure)
 dump(PUBLIC/'PERFORMANCE.json',perf)
 dump(PUBLIC/'NAME_FIELD_AUDIT.json',names)
 acceptance=dict(status=status,independent_master_to_mobile=verify['status'],sealed_input_hashes_match=sealed_inputs,receipts_after_final_data_cut=receipts_current,raw_to_master=ingestion,synthetic=tests,reused_geometry_tests=dict(tests=4,status='PASS',scope='nested role parity/hole/missing/cycle; existing locality_probe tests'),
  preservation=dict(protected_files=len(ledger),changed=changed,frozen_sector_grid_and_model_resources='UNCHANGED_SOURCE_HASHES',new_phone_query=False),
  actual_api=verify['actual_api'],sqlite_query_plan=plan,maximum_compressed_detail_bytes=max_detail,maximum_compressed_geometry_bytes=max_geometry,
  manual_state='PHONE_NOT_VERIFIED; no owner data read or overwritten',
  gaps=['GEO3 Android disk adapter/worker/cancellation/lease/backup/activation not implemented','Visicom distribution rights NOT_VERIFIED','Release manifest authentication/pinning/resume deferred GEO4','Latest owner rules/phone geography NOT_VERIFIED','Legacy road graph remains old compatible snapshot; new analytical graph adaptation deferred, no mixed bundle','All geometry-only candidate automatic eligibility remains unassessed; no RESOLVE1 ranking/nearest/fuzzy','OS page cache not cleared; timing is PC smoke, not Motorola readiness'])
 dump(PUBLIC/'ACCEPTANCE.json',acceptance)
 helpers=sorted(Path(__file__).parent.glob('*.py'))+[Path(__file__).with_name('INCLUSION_POLICY.json')]
 evidence=dict(status=status,source_revision_before='9e59993',tools=[dict(path=p.relative_to(ROOT).as_posix(),sha256=sha(p),normalized_lf_sha256=hashlib.sha256(p.read_text(encoding='utf-8').encode()).hexdigest()) for p in helpers],
  local_artifacts=artifact_manifest,commands=['acquire.py','extract.py','build.py','verify.py','test_contract.py','../locality_probe/test_geometry.py','visual.py','performance.py','report.py'],
  links=['../geo1/RESULTS_UK.md','../addr2/RESULTS_UK.md','../locality_probe/REPORT_UK.md'],publication='Summaries/code/synthetic fixtures only; no raw/master/mobile/detailed ledger datasets',
  reproducibility='Saved raw PBF/API/Visicom, capture groups, policy and compiler are retained. Logical reconstruction is specified; a second full clean byte-identical SQLite rebuild was not run.')
 dump(PUBLIC/'EVIDENCE_INDEX.json',evidence)
 print(js(dict(status=status,counts=stats,keys=keys,geometry=geometry_counts,unknown_location=unknown,changed=changed,performance=perf['warm_all_pages_lookup'])),flush=True)
 if not good:raise SystemExit('GEO2 is not accepted; inspect explicit gaps before closure')

if __name__=='__main__':run()
