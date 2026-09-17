import json
import threading
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import pytest
from eth_account.messages import encode_typed_data
from flytrade.product.api import SpectatorServer
from flytrade.product.history import ProductHistory
from .test_room import setup,W


def test_signed_http_boundary_origin_nonce_and_no_trade_endpoint(setup,tmp_path):
    room,_,_,bag=setup
    history=ProductHistory(tmp_path/'product.sqlite');history.close()
    server=SpectatorServer(('127.0.0.1',0),database=tmp_path/'product.sqlite',bag_room=room)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    url='http://127.0.0.1:'+str(server.server_port)
    def request(path,body=None,origin=None,method=None):
        req=Request(url+path,data=json.dumps(body).encode() if body is not None else None,
                    headers={'Content-Type':'application/json','Origin':origin or room.config.origin},method=method)
        try:
            with urlopen(req,timeout=3) as r:return r.status,json.load(r)
        except HTTPError as e:return e.code,json.load(e)
    try:
        body={'wallet':W[0].address,'bag_id':bag,'round_id':1,'action':'VOTE','choice':'HOLD'}
        assert request('/api/bags/challenge',body,origin='https://hostile.example')[0]==403
        status,message=request('/api/bags/challenge',body);assert status==200
        sig=W[0].sign_message(encode_typed_data(full_message=message)).signature.hex()
        action={'nonce':message['message']['nonce'],'signature':sig}
        assert request('/api/bags/action',action)[0]==200
        assert request('/api/bags/action',action)[0]==400
        status,snapshot=request('/api/bags?wallet='+W[0].address)
        assert snapshot['bag']['round']['my_vote']=='HOLD'
        assert request('/api/buy',{})[0]==405
        assert request('/api/bags/finalize',{})[0]==404
        assert request('/api/bags/action',action,method='PUT')[0]==405
        assert request('/api/bags?id=../../secret')[0]==400
    finally:server.shutdown();server.server_close();thread.join(3)
