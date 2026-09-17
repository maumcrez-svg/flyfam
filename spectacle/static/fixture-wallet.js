// Explicit demo provider. Never replaces an installed real wallet.
let wallets=[],selected=0;
const listeners=new Map();
window.flyFixtureWallet={on(event,cb){if(!listeners.has(event))listeners.set(event,new Set());listeners.get(event).add(cb);},removeListener(event,cb){listeners.get(event)?.delete(cb);},async request({method,params}){
 if(!wallets.length){const r=await fetch('/fixture/demo/wallets');if(!r.ok)throw Error('Test wallet unavailable');wallets=(await r.json()).wallets;}
 if(method==='eth_requestAccounts'||method==='eth_accounts')return [wallets[selected]];
 if(method==='eth_chainId')return '0x1237';
 if(method==='eth_signTypedData_v4'){
  const r=await fetch('/fixture/demo/sign',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({wallet:params[0],typed:JSON.parse(params[1])})});
  if(!r.ok)throw Error('Fixture signature rejected');return (await r.json()).signature;
 }
 throw Error('This paper demo does not send wallet transactions.');
}};
const crew=document.createElement('div');crew.className='fixture-wallets';crew.setAttribute('aria-label','Choose an explicit test wallet');
for(let i=0;i<3;i++){
 const b=document.createElement('button');b.textContent=i===2?'NON-HOLDER':'TEST CREW '+(i+1);b.setAttribute('aria-pressed',String(i===0));
 b.onclick=()=>{selected=i;listeners.get('accountsChanged')?.forEach(fn=>fn(wallets.length?[wallets[selected]]:[]));crew.querySelectorAll('button').forEach(el=>el.setAttribute('aria-pressed',String(el===b)));};crew.append(b);
}
document.getElementById('fixture-banner').append(crew);
