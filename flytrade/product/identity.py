"""Presentation-only ERC-20 identity cache. Never imported by the trader.

Canonical responses supply the addresses; browsers cannot choose an RPC target.
A single bounded background queue fetches name(), symbol(), logo() from the local
4663 node. Read-only API requests never wait for that network work. Logo bytes
are cached locally; neither private URLs nor arbitrary HTML/SVG reach viewers.
"""
import http.client
import ipaddress
import json
from pathlib import Path
import queue
import re
import socket
import sqlite3
import ssl
import io
import threading
import time
import unicodedata
from urllib.parse import urlsplit, urljoin
from urllib.request import Request, build_opener, ProxyHandler

ADDRESS=re.compile(r'0x[0-9a-fA-F]{40}\Z')
CID=re.compile(r'(?:Qm[1-9A-HJ-NP-Za-km-z]{44}|b[a-z2-7]{30,120})\Z')
SELECTORS={'name':'0x06fdde03','symbol':'0x95d89b41','logo':'0xfb7f21eb'}
CHAIN_ID=4663
MAX_IMAGE=4*1024*1024


def clean_text(value,limit):
    return ''.join(c for c in value if unicodedata.category(c)[0]!='C').strip()[:limit]


def decode_string(raw,limit=1024):
    if not isinstance(raw,str) or not raw.startswith('0x') or len(raw)>8194:
        raise ValueError('Malformed identity result')
    data=bytes.fromhex(raw[2:])
    if len(data)==32: # Older ERC-20 bytes32 metadata.
        value=data.rstrip(b'\0')
    else:
        if len(data)<64:raise ValueError('Short identity result')
        offset=int.from_bytes(data[:32]);length=int.from_bytes(data[offset:offset+32])
        if offset!=32 or length>limit or offset+32+length>len(data):raise ValueError('Invalid identity string')
        value=data[offset+32:offset+32+length]
    return value.decode('utf-8',errors='strict')


def logo_url(uri):
    """Use the same compact IPFS image route published by the Pons frontend."""
    uri=uri.strip()
    if CID.fullmatch(uri):uri='ipfs://'+uri
    p=urlsplit(uri)
    if p.scheme=='ipfs':
        cid=p.netloc
        if p.path not in ('','/'):raise ValueError('Unsupported IPFS path')
        if not CID.fullmatch(cid):raise ValueError('Invalid CID')
        return f'https://www.ponsfamily.com/api/ipfs/content/{cid}?variant=compact'
    if p.scheme!='https' or p.username or p.password or not p.hostname or p.port not in (None,443):
        raise ValueError('Unsupported logo URL')
    # A CID is content-addressed regardless of the gateway named in the contract.
    parts=p.path.strip('/').split('/')
    if len(parts)==2 and parts[0]=='ipfs' and CID.fullmatch(parts[1]):
        return f'https://www.ponsfamily.com/api/ipfs/content/{parts[1]}?variant=compact'
    return uri


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self,host,address,timeout):
        super().__init__(host,timeout=timeout,context=ssl.create_default_context());self.address=address
    def connect(self):
        raw=socket.create_connection((self.address,443),self.timeout)
        self.sock=self._context.wrap_socket(raw,server_hostname=self.host)


def fetch_logo(uri):
    url=logo_url(uri)
    for _ in range(3):
        p=urlsplit(url)
        if p.scheme!='https' or p.username or p.password or p.port not in (None,443):raise ValueError('Unsafe redirect')
        addresses={item[4][0] for item in socket.getaddrinfo(p.hostname,443,type=socket.SOCK_STREAM)}
        if not addresses or not all(ipaddress.ip_address(a).is_global for a in addresses):raise ValueError('Nonpublic image host')
        # Pin the connection to the checked address, retaining hostname TLS/SNI.
        conn=_PinnedHTTPS(p.hostname,sorted(addresses)[0],6)
        try:
            conn.request('GET',p.path+('?' +p.query if p.query else ''),headers={'User-Agent':'Flytrade-Spectator/1','Accept':'image/png,image/jpeg,image/webp'})
            response=conn.getresponse()
            if response.status in (301,302,303,307,308):
                url=urljoin(url,response.getheader('Location',''));continue
            if response.status!=200:raise ValueError('Logo source unavailable')
            if int(response.getheader('Content-Length','0'))>MAX_IMAGE:raise ValueError('Image too large')
            data=response.read(MAX_IMAGE+1)
            if len(data)>MAX_IMAGE:raise ValueError('Image too large')
            return normalize_raster(data)
        finally:conn.close()
    raise ValueError('Too many image redirects')


def normalize_raster(data):
    from PIL import Image, UnidentifiedImageError
    try:
        image=Image.open(io.BytesIO(data),formats=['PNG','JPEG','WEBP'])
        if image.width*image.height>4*1024*1024 or max(image.size)>4096:
            raise ValueError('Oversized raster')
        image.seek(0);image.load();image=image.convert('RGBA')
        image.thumbnail((128,128),Image.Resampling.LANCZOS)
        out=io.BytesIO();image.save(out,format='PNG',optimize=True)
        return out.getvalue(),'image/png'
    except (OSError,UnidentifiedImageError,Image.DecompressionBombError) as exc:
        raise ValueError('Invalid raster') from exc


def raster_type(data):
    return normalize_raster(data)[1]


class IdentityResolver:
    def __init__(self,rpc_url,*,image_fetch=fetch_logo):
        p=urlsplit(rpc_url)
        if p.scheme!='http' or p.username or p.password or not ipaddress.ip_address(p.hostname).is_loopback:
            raise ValueError('Identity RPC must be a configured local node')
        self.rpc_url=rpc_url;self.image_fetch=image_fetch;self.opener=build_opener(ProxyHandler({}))

    def rpc(self,body):
        request=Request(self.rpc_url,data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
        with self.opener.open(request,timeout=3) as response:
            data=response.read(32769)
            if len(data)>32768:raise ValueError('Identity RPC response too large')
            return json.loads(data)

    def resolve(self,token):
        if not ADDRESS.fullmatch(token):raise ValueError('Invalid token address')
        base={'chain_id':CHAIN_ID,'address':token,'name':None,'symbol':None,'logo_uri':None,
              'source':'ERC20 name()/symbol() and PONS logo()','observed_at':int(time.time()),
              'observed_block':None,'status':'UNAVAILABLE','icon_status':'UNAVAILABLE'}
        chain=self.rpc({'jsonrpc':'2.0','id':1,'method':'eth_chainId','params':[]})
        if chain.get('result')!=hex(CHAIN_ID):raise ValueError('Identity chain mismatch')
        head=self.rpc({'jsonrpc':'2.0','id':2,'method':'eth_blockNumber','params':[]})['result']
        if not re.fullmatch(r'0x[0-9a-fA-F]{1,16}',head):raise ValueError('Invalid block')
        base['observed_block']=int(head,16)
        requests=[{'jsonrpc':'2.0','id':i,'method':'eth_call','params':[{'to':token,'data':selector,'gas':'0x30d40'},head]}
                  for i,selector in enumerate(SELECTORS.values(),10)]
        results=self.rpc(requests)
        if not isinstance(results,list):raise ValueError('Invalid metadata batch')
        by_id={r.get('id'):r for r in results if isinstance(r,dict)}
        for i,field in enumerate(SELECTORS,10):
            try:value=decode_string(by_id[i]['result'])
            except (ValueError,KeyError,UnicodeError):continue
            base['logo_uri' if field=='logo' else field]=clean_text(value,1024 if field=='logo' else 96 if field=='name' else 24) or None
        base['status']='READY' if base['name'] and base['symbol'] else 'PARTIAL' if base['name'] or base['symbol'] else 'UNAVAILABLE'
        image=mime=None
        if base['logo_uri']:
            try:image,mime=self.image_fetch(base['logo_uri']);base['icon_status']='READY'
            except (OSError,ValueError,http.client.HTTPException):base['icon_status']='UNAVAILABLE'
        return base,image,mime


class IdentityCache:
    def __init__(self,path,resolver,*,max_rows=5000,max_bytes=64*1024*1024,queue_size=512):
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(path,check_same_thread=False);self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS identities(token TEXT PRIMARY KEY,payload TEXT NOT NULL,image BLOB,mime TEXT,expires INTEGER NOT NULL,used INTEGER NOT NULL)');self.db.commit()
        self.lock=threading.RLock();self.resolver=resolver;self.max_rows=max_rows;self.max_bytes=max_bytes
        self.pending=set();self.queue=queue.Queue(maxsize=queue_size);self.stop=threading.Event();self.revision=0
        self.thread=threading.Thread(target=self._run,name='spectator-identities',daemon=True);self.thread.start()

    def lookup(self,tokens):
        output={};now=int(time.time())
        with self.lock:
            for token in sorted(set(tokens))[:512]:
                if not ADDRESS.fullmatch(token):continue
                token=token.lower();row=self.db.execute('SELECT payload,image IS NOT NULL,expires FROM identities WHERE token=?',(token,)).fetchone()
                if row:
                    item=json.loads(row[0]);item.pop('logo_uri',None);item['icon_url']=f'/api/token-icon/{CHAIN_ID}/{token}' if row[1] else None;output[token]=item
                    self.db.execute('UPDATE identities SET used=? WHERE token=?',(now,token))
                if (not row or row[2]<=now) and token not in self.pending and not self.queue.full():
                    self.pending.add(token);self.queue.put_nowait(token)
            self.db.commit()
        return output

    def put(self,token,payload,image=None,mime=None):
        with self.lock:
            now=int(time.time())
            old=self.db.execute('SELECT payload,image,mime FROM identities WHERE token=?',(token,)).fetchone()
            if old and payload.get('status')=='UNAVAILABLE':
                previous=json.loads(old[0])
                if previous.get('name') or previous.get('symbol'):
                    payload={**previous,'status':'STALE','last_checked_at':now};image,mime=old[1],old[2]
            elif old and not image and json.loads(old[0]).get('logo_uri')==payload.get('logo_uri') and old[1]:
                image,mime=old[1],old[2];payload={**payload,'icon_status':'CACHED'}
            ttl=7*86400 if payload.get('status')=='READY' and image else 3600 if payload.get('status')=='READY' else 300
            self.db.execute('INSERT OR REPLACE INTO identities VALUES(?,?,?,?,?,?)',(token,json.dumps(payload,ensure_ascii=False),image,mime,now+ttl,now))
            while True:
                count,size=self.db.execute('SELECT count(*),coalesce(sum(length(payload)+coalesce(length(image),0)),0) FROM identities').fetchone()
                if count<=self.max_rows and size<=self.max_bytes:break
                self.db.execute('DELETE FROM identities WHERE token=(SELECT token FROM identities ORDER BY used,token LIMIT 1)')
            self.db.commit();self.revision+=1

    def icon(self,token):
        with self.lock:row=self.db.execute('SELECT image,mime FROM identities WHERE token=?',(token.lower(),)).fetchone()
        return (row[0],row[1]) if row and row[0] else None

    def _run(self):
        while not self.stop.is_set():
            try:token=self.queue.get(timeout=.2)
            except queue.Empty:continue
            try:
                payload,image,mime=self.resolver.resolve(token);self.put(token,payload,image,mime)
            except Exception:
                self.put(token,{'chain_id':CHAIN_ID,'address':token,'name':None,'symbol':None,'status':'UNAVAILABLE','icon_status':'UNAVAILABLE','observed_at':int(time.time())})
            finally:
                with self.lock:self.pending.discard(token)
                self.queue.task_done()

    def close(self):
        self.stop.set();self.thread.join(timeout=20)
        if not self.thread.is_alive():
            with self.lock:self.db.close()


def tokens_in(value):
    tokens=set()
    def walk(item):
        if isinstance(item,dict):
            for key,child in item.items():
                if key in ('token','overtaken_token','overtaker','previous_leader') and isinstance(child,str) and ADDRESS.fullmatch(child):tokens.add(child.lower())
                elif isinstance(child,(dict,list)):walk(child)
        elif isinstance(item,list):
            for child in item:walk(child)
    walk(value);return tokens
