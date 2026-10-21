"""Actual read-only SQLite PC reference API. Bounded keyset pages and lazy details.
Does not rank, pick a sector, hydrate full DB, or access raw archives/network.
"""
from common import ro,normalize
import json,zlib

class DiskReader:
 def __init__(self,path):
  self.db=ro(path);self.db.execute('PRAGMA cache_size=-8192');self.db.execute('PRAGMA query_only=ON')
  self.revision=self.db.execute("SELECT value FROM meta WHERE key='package_revision'").fetchone()[0]
 def close(self):self.db.close()
 def lookup(self,text,limit=128,cursor=None,cancel=None):
  if not 1<=limit<=128:raise ValueError('PAGE_LIMIT')
  key=normalize(text);after=''
  if cursor:
   if cursor['revision']!=self.revision or cursor['key']!=key:raise ValueError('CURSOR_REVISION_OR_QUERY_MISMATCH')
   after=cursor['after']
  if cancel and cancel():return dict(candidates=[],has_more=True,continuation=cursor,cancelled=True,consensus_allowed=False,revision=self.revision)
  rows=self.db.execute('SELECT p.cid,c.oid,c.pid,c.location_status,c.automatic_eligibility FROM postings p JOIN candidates c ON c.cid=p.cid WHERE p.lookup_key=? AND p.cid>? ORDER BY p.cid LIMIT ?',(key,after,limit+1)).fetchall()
  more=len(rows)>limit;rows=rows[:limit]
  return dict(candidates=[dict(zip(['cid','oid','pid','location_status','automatic_eligibility'],r)) for r in rows],has_more=more,continuation=dict(revision=self.revision,key=key,after=rows[-1][0]) if more else None,cancelled=False,consensus_allowed=False,revision=self.revision)
 def detail(self,oid):
  row=self.db.execute('SELECT payload FROM details WHERE oid=?',(oid,)).fetchone()
  if not row:raise ValueError('DETAIL_NOT_LOCAL')
  return json.loads(zlib.decompress(row[0]))
 def point(self,pid):
  row=self.db.execute('SELECT * FROM points WHERE pid=?',(pid,)).fetchone()
  if not row:raise ValueError('POINT_NOT_LOCAL')
  return row
 def aliases(self,oid,limit=128,after=''):
  if not 1<=limit<=128:raise ValueError('PAGE_LIMIT')
  return self.db.execute('SELECT aid,role,text,provenance FROM aliases WHERE oid=? AND aid>? ORDER BY aid LIMIT ?',(oid,after,limit)).fetchall()
 def geometry(self,oid):
  row=self.db.execute('SELECT payload,status FROM geometry WHERE oid=?',(oid,)).fetchone()
  return (json.loads(zlib.decompress(row[0])) if row[0] else None,row[1]) if row else (None,'NOT_SUPPLIED')
 def observations(self,oid,limit=128,after=''):
  if not 1<=limit<=128:raise ValueError('PAGE_LIMIT')
  return self.db.execute('SELECT obsid,payload FROM observations WHERE oid=? AND obsid>? ORDER BY obsid LIMIT ?',(oid,after,limit)).fetchall()
 def members(self,oid,limit=128,after=-1):
  if not 1<=limit<=128:raise ValueError('PAGE_LIMIT')
  return self.db.execute('SELECT ordinal,child,role FROM members WHERE parent=? AND ordinal>? ORDER BY ordinal LIMIT ?',(oid,after,limit)).fetchall()
 def links(self,oid,limit=128,after=''):
  if not 1<=limit<=128:raise ValueError('PAGE_LIMIT')
  return self.db.execute('SELECT lid,target,role,payload FROM links WHERE oid=? AND lid>? ORDER BY lid LIMIT ?',(oid,after,limit)).fetchall()
