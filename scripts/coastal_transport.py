"""Bounded HTTP and lossless partial-TIFF assembly; never open remote GDAL URLs."""

import base64
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
from pathlib import Path
import struct
import threading
import time
from urllib.parse import urlsplit

import requests


class GateError(RuntimeError):
    pass


class Budget:
    def __init__(self, ceiling, seconds, log, clock=time.monotonic, *, prior_reserved=0, prior_seconds=0):
        if (type(prior_reserved) is not int or not 0<=prior_reserved<ceiling
                or type(prior_seconds) is not int or not 0<=prior_seconds<seconds):
            raise GateError('Invalid carried acquisition budget')
        self.ceiling, self.seconds, self.clock = ceiling, seconds, clock
        self.attempt_start = clock()
        self.start = self.attempt_start-prior_seconds
        self.prior_reserved, self.prior_seconds = prior_reserved, prior_seconds
        self.reserved = prior_reserved
        self.received = 0
        self.stop_reason = None
        self.lock = threading.Lock()
        self.log = Path(log)
        with self.log.open('x', encoding='utf-8'):
            pass

    def check(self):
        if self.stop_reason is not None:
            raise GateError('Earlier gate failed: '+self.stop_reason)
        if self.clock()-self.start >= self.seconds:
            raise GateError('Two-hour acquisition limit reached')

    def stop(self, reason):
        with self.lock:
            if self.stop_reason is None:self.stop_reason=reason

    def reserve(self, count):
        with self.lock:
            self.check()
            if count < 0 or self.reserved+count > self.ceiling:
                raise GateError('Total transfer reservation would exceed approved ceiling')
            self.reserved += count

    def record(self, entry, received=0):
        with self.lock:
            self.received += received
            entry = dict(entry, elapsed_seconds=self.clock()-self.start,
                         cumulative_reserved_bytes=self.reserved, cumulative_body_bytes=self.received,
                         prior_reserved_bytes=self.prior_reserved, prior_elapsed_seconds=self.prior_seconds,
                         attempt_reserved_bytes=self.reserved-self.prior_reserved,
                         attempt_elapsed_seconds=self.clock()-self.attempt_start)
            with self.log.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(entry, allow_nan=False)+'\n')


class Transport:
    """Reserve response limits plus conservative HTTP overhead BEFORE every request.

    Reservations are never refunded, including failed and partial requests. Bodies
    are read in bounded chunks; redirects/full-file fallbacks are refused unread.
    """
    def __init__(self, budget, session=None, sleep=time.sleep):
        self.budget = budget
        self.session = session or requests.Session()
        self.sleep = sleep
        self.token_lock = threading.Lock()
        self.tokens = {}

    def request(self, method, url, *, length=0, expected=None, headers=None):
        if urlsplit(url).scheme != 'https':
            raise GateError('HTTPS required')
        for attempt in range(3):
            self.budget.reserve(length + 65536)  # all metadata, failed bodies and HTTP allowance
            received = 0
            try:
                timeout = max(.01, min(30., self.budget.seconds-(self.budget.clock()-self.budget.start)))
                with self.session.request(method, url, headers={'Accept-Encoding':'identity',**(headers or {})}, stream=True,
                                          timeout=(timeout,timeout), allow_redirects=False) as resp:
                    h = dict(resp.headers)
                    status = resp.status_code
                    # No response body is read until status and version/range pass.
                    if status in (429,500,502,503,504):
                        self.budget.record(dict(method=method,status=status,attempt=attempt,retry=True))
                        if attempt == 2:
                            raise GateError('Transient request retries exhausted')
                        wait = h.get('Retry-After',str(2**attempt))
                        try: delay=max(0.,float(wait))
                        except ValueError:
                            delay=max(0.,(parsedate_to_datetime(wait)-datetime.now(timezone.utc)).total_seconds())
                        if delay+self.budget.clock()-self.budget.start >= self.budget.seconds:
                            raise GateError('Retry-After exceeds acquisition deadline')
                        self.sleep(delay)
                        continue
                    if expected is not None:
                        off,n,size,etag = expected
                        if (status!=206 or h.get('Content-Range')!=f'bytes {off}-{off+n-1}/{size}'
                                or h.get('ETag')!=etag or int(h.get('Content-Length','-1'))!=n):
                            raise GateError('Range/ETag failed; body refused')
                    elif status!=200:
                        raise GateError(f'HTTP status {status}; body refused')
                    if method=='HEAD':
                        data=b''
                    else:
                        size=int(h.get('Content-Length','-1'))
                        if size<0 or size>length or h.get('Content-Encoding','identity')!='identity':
                            raise GateError('Unbounded/encoded response refused')
                        chunks=[]
                        while received<size:
                            self.budget.check()
                            chunk=resp.raw.read(min(65536,size-received))
                            if not chunk:raise requests.ConnectionError('Truncated response')
                            chunks.append(chunk);received+=len(chunk)
                        data=b''.join(chunks)
                    self.budget.check()
                    self.budget.record(dict(method=method,status=status,attempt=attempt,range=headers.get('Range') if headers else None,
                                            sha256=hashlib.sha256(data).hexdigest()),received)
                    return data,h
            except (requests.Timeout, requests.ConnectionError):
                self.budget.record(dict(method=method,attempt=attempt,network_failure=True),received)
                if attempt==2:raise GateError('Network retries exhausted') from None
                self.sleep(2**attempt)
        raise GateError('Unreachable retry state')

    def sign(self, unsigned):
        u=urlsplit(unsigned)
        if u.scheme!='https' or not u.netloc.startswith('sentinel2l2a') or not u.netloc.endswith('.blob.core.windows.net') or u.query:
            raise GateError('Unexpected unsigned source')
        container=(u.netloc,u.path.split('/')[1])
        with self.token_lock:
            if container not in self.tokens:
                from urllib.parse import urlencode
                raw,_=self.request('GET','https://planetarycomputer.microsoft.com/api/sas/v1/sign?'+urlencode({'href':unsigned}),length=16384)
                v=urlsplit(json.loads(raw)['href'])
                if (v.scheme,v.netloc,v.path)!=(u.scheme,u.netloc,u.path) or not v.query:
                    raise GateError('Unexpected signing response')
                self.tokens[container]=v.query
        return unsigned+'?'+self.tokens[container]

    def head(self, asset):
        url=self.sign(asset['url'])
        _,h=self.request('HEAD',url,headers={'If-Match':asset['etag']})
        if h.get('ETag')!=asset['etag'] or int(h.get('Content-Length','-1'))!=asset['file_size'] or h.get('Accept-Ranges')!='bytes':
            raise GateError('Source version/size/range changed before pixels')

    def read(self, asset, off, n):
        if off<0 or n<=0 or off+n>asset['file_size']:
            raise GateError('Invalid source range')
        return self.request('GET',self.sign(asset['url']),length=n,
                            expected=(off,n,asset['file_size'],asset['etag']),
                            headers={'If-Match':asset['etag'],'Range':f'bytes={off}-{off+n-1}'})[0]


TYPE_WIDTH={1:1,2:1,3:2,4:4,5:8,6:1,7:1,8:2,9:4,10:8,11:4,12:8,16:8}


def metadata_fields(read):
    """Read only first-IFD tag values; ignore overview IFDs and image payload."""
    header=read(0,8)
    if header[:2]!=b'II' or struct.unpack('<H',header[2:4])[0]!=42:
        raise GateError('Expected little-endian classic native TIFF')
    pos=struct.unpack('<I',header[4:8])[0]
    n=struct.unpack('<H',read(pos,2))[0]
    if not 1<=n<=100:raise GateError('Unexpected IFD count')
    raw=read(pos+2,n*12)
    fields=[]
    for i in range(n):
        tag,typ,count,value=struct.unpack('<HHI4s',raw[i*12:i*12+12])
        if typ not in TYPE_WIDTH or count*TYPE_WIDTH[typ]>65536 or count==0:
            raise GateError('Unexpected metadata tag')
        size=count*TYPE_WIDTH[typ]
        data=value[:size] if size<=4 else read(struct.unpack('<I',value)[0],size)
        fields.append(dict(tag=tag,type=typ,count=count,data=base64.b64encode(data).decode()))
    if len({v['tag'] for v in fields})!=n:raise GateError('Duplicate TIFF field')
    return fields


def assemble(fields, tiles):
    """Repack native compressed blocks without decoding; absent blocks stay sparse.

    Strip overview links and remap offsets in a local compact TIFF. Image block
    bytes are unchanged. No claim that this partial file is a complete tile.
    """
    data={v['tag']:(v['type'],v['count'],base64.b64decode(v['data'])) for v in fields}
    if 324 not in data or 325 not in data:raise GateError('Not tiled')
    count=data[324][1]
    if data[325][1]!=count or any(i<0 or i>=count for i in tiles):raise GateError('Tile IDs out of bounds')
    data[324]=(4,count,b'\0'*(count*4));data[325]=(4,count,b'\0'*(count*4))
    # Unused sub-IFDs/overview links and source-only GDAL structural hints omitted.
    data.pop(330,None)
    count_fields=len(data);out=bytearray(b'II'+struct.pack('<HIH',42,8,count_fields)+b'\0'*(count_fields*12+4))
    positions={}
    for i,(tag,(typ,count,value)) in enumerate(sorted(data.items())):
        entry=10+i*12
        struct.pack_into('<HHI',out,entry,tag,typ,count)
        if len(value)<=4:
            out[entry+8:entry+12]=value.ljust(4,b'\0');positions[tag]=entry+8
        else:
            if len(out)%2:out.extend(b'\0')
            positions[tag]=len(out);struct.pack_into('<I',out,entry+8,len(out));out.extend(value)
    for i,payload in sorted(tiles.items()):
        struct.pack_into('<I',out,positions[324]+4*i,len(out))
        struct.pack_into('<I',out,positions[325]+4*i,len(payload))
        out.extend(payload)
    return bytes(out)
