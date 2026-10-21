"""GEO4 packed exact-base transport v1; offline generation/reconstruction only.
Bounded block reads, independently compressed full fallback, no active SQLite patch.
Signing uses explicit test keys; never generates/reads a production signing secret.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import time
import zlib
from compiler import sha,write

BLOCK=256*1024
PACK_LIMIT=256*1024*1024
RAW_LIMIT=4*1024**3
HASH=re.compile('[a-f0-9]{64}')
NAME=re.compile('[a-z0-9][a-z0-9._-]{0,95}')
DOMAIN=b'TaxiHelper-GEO4-MANIFEST-1\0'

def canonical(obj):return json.dumps(obj,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode('utf-8')
def digest(b):return hashlib.sha256(b).hexdigest()

def sign(payload,key,key_id,domain=DOMAIN):
    body=canonical(payload)
    return canonical(dict(contract='GEO4_SIGNED_ENVELOPE_1',key_id=key_id,payload_b64=base64.b64encode(body).decode('ascii'),signature_b64=base64.b64encode(key.sign(domain+body)).decode('ascii')))

def authenticate(envelope,keys):
    if len(envelope)>8*1024*1024:raise ValueError('ENVELOPE_BOUND')
    e=json.loads(envelope)
    if e['contract']!='GEO4_SIGNED_ENVELOPE_1' or e['key_id'] not in keys:raise ValueError('TRUST_KEY')
    body=base64.b64decode(e['payload_b64'],validate=True);sig=base64.b64decode(e['signature_b64'],validate=True)
    if len(body)>5*1024*1024 or len(sig)!=64:raise ValueError('SIGNATURE_BOUND')
    keys[e['key_id']].verify(sig,DOMAIN+body)
    obj=json.loads(body)
    if canonical(obj)!=body:raise ValueError('NON_CANONICAL_SIGNED_PAYLOAD')
    validate(obj)
    return obj

def number(v,minimum=0,maximum=RAW_LIMIT):
    if type(v) is not int or not minimum<=v<=maximum:raise ValueError('INTEGER_BOUND')
    return v

def file_spec(f):
    if not NAME.fullmatch(f['name']) or not HASH.fullmatch(f['sha256']):raise ValueError('FILE_ID')
    number(f['bytes'],1,2*1024**3-1)

def validate(m):
    if m['contract']!='GEO4_RELEASE_1':raise ValueError('MANIFEST_CONTRACT')
    number(m['sequence'],1,2**53-1)
    if digest(canonical(m['identity']))!=m['logical_identity']:raise ValueError('LOGICAL_IDENTITY')
    if m['capabilities']!=dict(schema='GEO2_MASTER_1',reader='GEO3_DISK_1',normalizer='GEO2_NFKC_CASEFOLD_ALNUM_V1',evidence='RESOLVE1_COMPLETE_GEOMETRY_SOURCE_ALIAS_1',adapter='RESOLVE1_GEOMETRY_SOURCE_ALIAS_4',transport='GEO4_PACKED_ZLIB_1'):raise ValueError('CAPABILITY')
    if m['identity']['sector_sha256']!='19a75b5a16f708c400cefafe8189519936a5545e73142bb8bd834bf065a9709e':raise ValueError('SECTORS_CHANGED')
    if len(m['components'])!=2 or {c['role'] for c in m['components']}!={'base','resolver'}:raise ValueError('COMPONENT_CLOSURE')
    names=set()
    def addfile(f):
        file_spec(f)
        if f['name'] in names:raise ValueError('DUPLICATE_ASSET')
        names.add(f['name'])
    addfile(m['proof'])
    if m['proof']['name']!='completeness.json':raise ValueError('PROOF_NAME')
    for c in m['components']:
        number(c['raw_bytes'],1);number(c['base_bytes'])
        if not HASH.fullmatch(c['raw_sha256']) or not HASH.fullmatch(c['base_sha256']):raise ValueError('RAW_ID')
        if c['role']=='base' and not HASH.fullmatch(c['version']):raise ValueError('BASE_VERSION')
        if c['full']['codec']!='zlib':raise ValueError('CODEC')
        addfile(c['full'])
        if c['full']['name']!=c['role']+'.full.z':raise ValueError('FULL_NAME')
        packs={}
        if len(c['packs'])>64:raise ValueError('PACK_COUNT')
        for p in c['packs']:
            addfile(p)
            if not re.fullmatch(re.escape(c['role'])+r'\.c\d{3}\.pack',p['name']):raise ValueError('PACK_NAME')
            if p['bytes']>PACK_LIMIT:raise ValueError('PACK_BOUND')
            packs[p['name']]=p
        if len(c['chunks'])!=(c['raw_bytes']+BLOCK-1)//BLOCK:raise ValueError('CHUNK_COUNT')
        offset=0;ranges={name:[] for name in packs}
        for b in c['chunks']:
            number(b['target_offset']);number(b['bytes'],1,BLOCK)
            if b['target_offset']!=offset or b['bytes']!=min(BLOCK,c['raw_bytes']-offset) or not HASH.fullmatch(b['sha256']):raise ValueError('TARGET_COVERAGE')
            offset+=b['bytes']
            if b['source']=='base':
                number(b['base_offset'])
                if b['base_offset']+b['bytes']>c['base_bytes']:raise ValueError('BASE_RANGE')
            elif b['source']=='pack':
                number(b['offset']);number(b['encoded_bytes'],1,BLOCK+8192)
                p=packs.get(b['pack'])
                if p is None or b['offset']+b['encoded_bytes']>p['bytes']:raise ValueError('PACK_RANGE')
                ranges[b['pack']].append((b['offset'],b['offset']+b['encoded_bytes']))
            else:raise ValueError('CHUNK_SOURCE')
        if offset!=c['raw_bytes']:raise ValueError('TARGET_SIZE')
        for name,rs in ranges.items():
            end=0
            for a,b in sorted(rs):
                if a!=end:raise ValueError('DUPLICATE_OVERLAPPING_OR_UNUSED_PACK_RANGE')
                end=b
            if end!=packs[name]['bytes']:raise ValueError('INCOMPLETE_PACK_COVERAGE')
    if len(names)>256:raise ValueError('RELEASE_ASSET_COUNT')
    return m

def component(old,target,role,output,version=''):
    start=time.perf_counter();index={};old_hash=hashlib.sha256();old_bytes=0
    with old.open('rb') as f:
        for b in iter(lambda:f.read(BLOCK),b''):
            index.setdefault((digest(b),len(b)),old_bytes);old_hash.update(b);old_bytes+=len(b)
    index_seconds=time.perf_counter()-start;chunks=[];packs=[];pack=None;pack_bytes=0;pack_hash=None;full=output/(role+'.full.z');raw_hash=hashlib.sha256();raw_bytes=0;encoded_hash=hashlib.sha256();encoded_bytes=0;compressor=zlib.compressobj(6)
    def closepack():
        nonlocal pack
        if pack:
            pack.flush();os.fsync(pack.fileno());pack.close();packs.append(dict(name=Path(pack.name).name,bytes=pack_bytes,sha256=pack_hash.hexdigest()));pack=None
    try:
        with target.open('rb') as src,full.open('xb') as dst:
            for b in iter(lambda:src.read(BLOCK),b''):
                if raw_bytes+len(b)>RAW_LIMIT:raise ValueError('RAW_BOUND')
                h=digest(b);chunk=dict(target_offset=raw_bytes,bytes=len(b),sha256=h)
                previous=index.get((h,len(b)))
                if previous is not None:chunk.update(source='base',base_offset=previous)
                else:
                    encoded=zlib.compress(b,6)
                    if pack is None or pack_bytes+len(encoded)>PACK_LIMIT:
                        closepack();pack=(output/f'{role}.c{len(packs):03}.pack').open('xb');pack_bytes=0;pack_hash=hashlib.sha256()
                    chunk.update(source='pack',pack=Path(pack.name).name,offset=pack_bytes,encoded_bytes=len(encoded));pack.write(encoded);pack_hash.update(encoded);pack_bytes+=len(encoded)
                chunks.append(chunk);raw_hash.update(b);raw_bytes+=len(b)
                encoded=compressor.compress(b);dst.write(encoded);encoded_hash.update(encoded);encoded_bytes+=len(encoded)
            encoded=compressor.flush();dst.write(encoded);encoded_hash.update(encoded);encoded_bytes+=len(encoded);dst.flush();os.fsync(dst.fileno())
        closepack()
    finally:
        if pack:pack.close()
    return dict(role=role,version=version,raw_bytes=raw_bytes,raw_sha256=raw_hash.hexdigest(),base_bytes=old_bytes,base_sha256=old_hash.hexdigest(),
                full=dict(name=full.name,bytes=encoded_bytes,sha256=encoded_hash.hexdigest(),codec='zlib'),packs=packs,chunks=chunks),dict(index_seconds=index_seconds,prepare_seconds=time.perf_counter()-start,index_entries=len(index),reused_bytes=sum(b['bytes'] for b in chunks if b['source']=='base'))

def choose(c,base_sha,request_overhead=1024):
    if base_sha==c['raw_sha256']:return 'skip'
    compact=sum(p['bytes']+request_overhead for p in c['packs'])
    return 'compact' if base_sha==c['base_sha256'] and compact<c['full']['bytes']+request_overhead else 'full'

def verify_asset(root,spec):
    file_spec(spec);p=root/spec['name']
    if not p.is_file() or p.stat().st_size!=spec['bytes'] or sha(p)!=spec['sha256']:raise ValueError('ENCODED_ASSET_HASH_OR_SIZE')
    return p

def inflate_block(encoded,length):
    d=zlib.decompressobj();b=d.decompress(encoded,length+1)
    if len(b)!=length or not d.eof or d.unused_data or d.unconsumed_tail:raise ValueError('BOUNDED_CHUNK_DECODE')
    return b

def reconstruct(c,old,assets,target,mode):
    if target.exists() or target.resolve()==old.resolve():raise ValueError('NEW_TARGET_REQUIRED')
    start=time.perf_counter();written=0;h=hashlib.sha256();reads=0
    def emit(dst,b):
        nonlocal written
        written+=len(b)
        if written>c['raw_bytes']:raise ValueError('RAW_DECODE_OVERFLOW')
        dst.write(b);h.update(b)
    if mode=='skip':
        if old.stat().st_size!=c['raw_bytes'] or sha(old)!=c['raw_sha256']:raise ValueError('SKIP_IDENTITY')
        return dict(mode=mode,raw_bytes=0,encoded_bytes=0,old_read_bytes=0,seconds=time.perf_counter()-start,sha256=c['raw_sha256'])
    if mode=='compact':
        if old.stat().st_size!=c['base_bytes']:raise ValueError('BASE_SIZE')
        # Whole old hash is a PC proof only; Android verifies each reused chunk from a held lease.
        if sha(old)!=c['base_sha256']:raise ValueError('WRONG_BASE')
        paths={p['name']:verify_asset(assets,p) for p in c['packs']}
        with old.open('rb') as source,target.open('xb') as dst:
            for chunk in c['chunks']:
                if chunk['source']=='base':source.seek(chunk['base_offset']);b=source.read(chunk['bytes']);reads+=len(b)
                else:
                    with paths[chunk['pack']].open('rb') as p:p.seek(chunk['offset']);encoded=p.read(chunk['encoded_bytes'])
                    b=inflate_block(encoded,chunk['bytes'])
                if digest(b)!=chunk['sha256']:raise ValueError('CHUNK_HASH')
                emit(dst,b)
            dst.flush();os.fsync(dst.fileno())
        wire=sum(p['bytes'] for p in c['packs'])
    elif mode=='full':
        path=verify_asset(assets,c['full']);d=zlib.decompressobj()
        with path.open('rb') as src,target.open('xb') as dst:
            for data in iter(lambda:src.read(64*1024),b''):
                if d.eof:raise ValueError('TRAILING_COMPRESSED_DATA')
                while data:
                    b=d.decompress(data,1<<20);data=d.unconsumed_tail;emit(dst,b)
                    if d.unused_data:raise ValueError('TRAILING_COMPRESSED_DATA')
            if not d.eof:raise ValueError('TRUNCATED_FULL_STREAM')
            dst.flush();os.fsync(dst.fileno())
        wire=c['full']['bytes']
    else:raise ValueError('MODE')
    if written!=c['raw_bytes'] or h.hexdigest()!=c['raw_sha256'] or sha(target)!=c['raw_sha256']:raise ValueError('FINAL_TARGET_HASH_OR_SIZE')
    return dict(mode=mode,raw_bytes=written,encoded_bytes=wire,old_read_bytes=reads,seconds=time.perf_counter()-start,sha256=h.hexdigest())

def restore_with_fallback(manifest,role,old,assets,output,base_sha):
    validate(manifest);c=next(c for c in manifest['components'] if c['role']==role);mode=choose(c,base_sha)
    try:return reconstruct(c,old,assets,output,mode)
    except Exception as exc:
        if mode!='compact':raise
        # Exactly one separate full attempt, never overwrite partial output or a live resource.
        result=reconstruct(c,old,assets,output.with_name(output.name+'.full'), 'full');result['compact_failure']=type(exc).__name__+':'+str(exc);result['fallback_attempts']=1;return result
