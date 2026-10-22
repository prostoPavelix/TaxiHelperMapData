"""Bounded read-only Geofabrik metadata discovery; never downloads PBF or executes suppliers.
Not invoked by AUTO1-A checks. Future trusted workflow adapter; no latest URL fallback.
"""
import datetime as dt
import re
import urllib.request
from auto1 import completed_snapshot

ORIGIN="https://download.geofabrik.de/europe/"

def discover(fetch, today):
    # fetch(url, method, maximum) -> (status, headers, bounded body)
    status, _, body=fetch(ORIGIN+"ukraine.html", "GET", 2*1024*1024)
    if status != 200:raise ValueError("LISTING_HTTP")
    if len(body)>2*1024*1024:raise ValueError("LISTING_BOUND")
    names=sorted(set(re.findall(rb'ukraine-(\d{6})\.osm\.pbf',body)),reverse=True)
    if not names:raise ValueError("NO_DATED_LISTING")
    # Latest dated snapshot only: unavailable newest is failure, never silently choose older.
    stamp=names[0].decode("ascii")
    date=dt.datetime.strptime(stamp,"%y%m%d").date()
    url=ORIGIN+"ukraine-"+stamp+".osm.pbf"
    code, headers, _=fetch(url,"HEAD",0)
    md5code, _, raw=fetch(url+".md5","GET",4096)
    if md5code!=200 or len(raw)>4096:raise ValueError("SOURCE_MD5_BOUND")
    md5=raw.decode("ascii").split()[0]
    if not re.fullmatch("[a-f0-9]{32}",md5):raise ValueError("SOURCE_MD5_FORMAT")
    if headers.get("content-encoding", "identity") not in ("identity", ""):raise ValueError("SOURCE_ENCODING")
    entry=dict(date=date.isoformat(),url=url,completed=date<today,http_status=code,
               bytes=int(headers.get("content-length","-1")),coverage="ukraine",md5=md5,
               etag=headers.get("etag"),last_modified=headers.get("last-modified"))
    return completed_snapshot([entry],today)

def network_fetch(url, method, maximum):
    if not re.fullmatch(r"https://download\.geofabrik\.de/europe/(ukraine\.html|ukraine-\d{6}\.osm\.pbf(?:\.md5)?)",url):raise ValueError("SOURCE_ORIGIN")
    request=urllib.request.Request(url,method=method,headers={"User-Agent":"TaxiHelper-GEO4-AUTO1","Accept-Encoding":"identity"})
    with urllib.request.urlopen(request,timeout=30) as response:
        if response.url!=url:raise ValueError("SOURCE_REDIRECT_REQUIRES_REVIEW")
        body=b"" if method=="HEAD" else response.read(maximum+1)
        if len(body)>maximum:raise ValueError("SOURCE_METADATA_BOUND")
        return response.status,{k.lower():v for k,v in response.headers.items()},body

if __name__=="__main__":
    import json
    print(json.dumps(discover(network_fetch,dt.datetime.now(dt.timezone.utc).date()),sort_keys=True))
