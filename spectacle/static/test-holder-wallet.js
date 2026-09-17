// Explicit test-holder provider. It never replaces a real wallet or signs transactions.
let wallets=[],selected=0;const listeners=new Map();
window.flyTestHolderWallet={on(event,cb){if(!listeners.has(event))listeners.set(event,new Set());listeners.get(event).add(cb);},removeListener(event,cb){listeners.get(event)?.delete(cb);},async request({method,params}){
 if(!wallets.length){const r=await fetch('/api/test-holders/wallets');if(!r.ok)throw Error('Test holders are unavailable');wallets=(await r.json()).wallets;}
 if(method==='eth_requestAccounts'||method==='eth_accounts')return [wallets[selected]];
 if(method==='eth_chainId')return '0x1237';
 if(method==='eth_signTypedData_v4'){
  const typed=JSON.parse(params[1]);
  if(typed.domain.name!=='THE FLY BAG ROOM TEST HOLDERS')throw Error('Not a test-holder challenge');
  const r=await fetch('/api/test-holders/sign',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({nonce:typed.message.nonce})});
  if(!r.ok)throw Error('Test signature rejected');return (await r.json()).signature;
 }
 throw Error('Test holders cannot send transactions or claim real funds.');
}};
const controls=document.createElement('div');controls.className='fixture-wallets';
for(let i=0;i<3;i++){const b=document.createElement('button');b.textContent=i===2?'NON-HOLDER':'TEST CREW '+(i+1);b.setAttribute('aria-pressed',String(i===0));b.onclick=()=>{selected=i;listeners.get('accountsChanged')?.forEach(fn=>fn(wallets.length?[wallets[selected]]:[]));controls.querySelectorAll('button').forEach(el=>el.setAttribute('aria-pressed',String(el===b)));};controls.append(b);}
document.getElementById('fixture-banner').append(controls);
