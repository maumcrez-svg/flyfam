import {brand} from './brand.js';
import {walletSession as session,shortAccount,walletError} from './wallet-session.js';
import {testHoldersMode,fixtureMode} from './transport.js';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

export function mountHolderAccess(){
 const test=testHoldersMode||fixtureMode,button=document.createElement('button');button.id='holder-access-button';button.className='holder-access-button';button.setAttribute('aria-haspopup','dialog');
 document.querySelector('.header-right').prepend(button);
 const dialog=document.createElement('dialog');dialog.id='holder-access-dialog';dialog.setAttribute('aria-labelledby','holder-access-title');
 dialog.innerHTML=`<div class="holder-dialog-top"><span class="eyebrow">${test?'TEST HOLDER ACCESS':'HOLDER ACCESS'}</span><button id="holder-close" class="holder-close" aria-label="Close holder access">×</button></div><div class="holder-heading"><img src="${brand.avatar}" alt=""><div><h2 id="holder-access-title">TAKE YOUR SEAT.</h2><p>The fly picks. The fam decides.</p></div></div><div class="holder-steps" aria-label="Connection steps"><span data-step="connect">01 CONNECT</span><span data-step="verify">02 VERIFY</span><span data-step="crew">03 THE BAG</span></div><div id="holder-content"></div><p id="holder-feedback" class="holder-feedback" role="status" aria-live="polite"></p><div class="holder-signature-note"><span>↳</span><p>Connection shares your address. Votes and claims ask for a message signature.<br><b>No token approval. No transaction gas.</b></p></div>`;
 document.body.append(dialog);
 const content=dialog.querySelector('#holder-content'),feedback=dialog.querySelector('#holder-feedback');
 let eligibility=null,onClaims=null,desired=null,providerKey='',localMessage='',config=null,pairing=false,cancelPairing=null,qrGeneration=0;
 const open=purpose=>{desired=purpose||null;session.discover();render();if(!dialog.open)dialog.showModal();};
 const close=()=>dialog.close();button.onclick=()=>open();dialog.querySelector('#holder-close').onclick=close;
 dialog.addEventListener('click',e=>{if(e.target===dialog){const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)close();}});
 dialog.addEventListener('close',()=>{desired=null;qrGeneration++;if(pairing)cancelPairing?.();pairing=false;providerKey='';});
 async function run(fn){localMessage='';try{await fn();if(desired==='claims'&&session.get().wallet){close();onClaims?.();}}catch(e){localMessage=walletError(e);}render();}
 function render(){
  const s=session.get(),busy=s.phase!=='idle';
  button.textContent=s.wallet?`${test?'TEST · ':''}${shortAccount(s.wallet)}`:test?'TEST HOLDER →':'CONNECT WALLET →';button.dataset.connected=String(!!s.wallet);button.setAttribute('aria-label',s.wallet?'Open holder account '+shortAccount(s.wallet):test?'Connect a test holder wallet':'Connect wallet');
  dialog.querySelector('[data-step=connect]').dataset.active=String(!!s.wallet);
  dialog.querySelector('[data-step=verify]').dataset.active=String(s.authenticated);
  dialog.querySelector('[data-step=crew]').dataset.active=String(s.authenticated&&eligibility?.wallet===s.wallet&&eligibility?.eligible===true);
  const nextKey=[s.wallet,s.authenticated,s.chainId,s.providerName,session.providers().map(p=>p.id).join(','),!!config?.walletconnect_enabled,eligibility?.bag,eligibility?.wallet,eligibility?.eligible].join('|');
  if(!pairing&&nextKey!==providerKey){providerKey=nextKey;
   if(!session.available){content.innerHTML='<div class="holder-empty"><b>THE LAB IS RECONNECTING.</b><p>Wallet actions are paused until the site confirms its current mode.</p><button class="holder-primary" id="holder-reload">RELOAD THE LAB ↗</button></div>';content.querySelector('button').onclick=()=>location.reload();}
   else if(!s.wallet){
    content.innerHTML=`${test?'<p class="holder-test-note">TEST HOLDERS · PAPER ONLY<br>Your real wallet stays untouched. Choose a labeled test crew in the banner.</p>':''}<div id="holder-wallet-list" class="holder-wallet-list"></div><div id="holder-mobile-options"></div>`;
    const list=content.querySelector('#holder-wallet-list');
    for(const p of session.providers()){
     const row=document.createElement('button');row.className='holder-provider';row.dataset.walletId=p.id;
     const icon=document.createElement(p.icon?'img':'span');if(p.icon){icon.src=p.icon;icon.alt='';}else{icon.className='holder-provider-icon';icon.textContent=test?'T':p.name.slice(0,1).toUpperCase();}
     const label=document.createElement('span');label.textContent=p.name;const sub=document.createElement('small');sub.textContent=test?'ISOLATED TEST IDENTITY':'DETECTED IN THIS BROWSER';label.append(sub);
     const arrow=document.createElement('span');arrow.textContent='↗';row.append(icon,label,arrow);row.onclick=()=>run(()=>session.connect(p.id));list.append(row);
    }
    if(!session.providers().length)list.innerHTML='<div class="holder-empty"><b>NO WALLET DETECTED.</b><p>Open this page in your wallet’s browser, or enable a browser wallet extension.</p><button id="holder-rescan" class="holder-secondary">CHECK AGAIN ↻</button></div>';
    content.querySelector('#holder-rescan')?.addEventListener('click',()=>{session.discover();localMessage='Checked this browser for wallets.';render();});
    if(!test){const mobile=content.querySelector('#holder-mobile-options');mobile.innerHTML=config?.walletconnect_enabled?'<button id="holder-qr" class="holder-provider"><span class="holder-provider-icon">▦</span><span>WalletConnect<small>SCAN WITH YOUR MOBILE WALLET</small></span><span>↗</span></button>':'<p class="holder-mobile-note">On mobile? Open this site inside your wallet browser. QR connection is not enabled on this deployment.</p>';mobile.querySelector('#holder-qr')?.addEventListener('click',()=>run(connectQR));}
   }else{
    const matched=eligibility?.wallet===s.wallet,eligible=matched?eligibility.eligible:null;
    content.innerHTML=`${test?'<p class="holder-test-note">TEST HOLDER · NO REAL FUNDS</p>':''}<div class="holder-account"><span class="holder-account-icon">${esc(s.wallet.slice(2,4).toUpperCase())}</span><div><b>${esc(shortAccount(s.wallet))}</b><small>${esc(s.providerName)}</small></div><button id="holder-copy" class="holder-secondary" aria-label="Copy wallet address">COPY</button></div><p class="holder-full-address">${esc(s.wallet)}</p><div class="holder-facts"><div><span>NETWORK</span><b>${s.chainId===4663?'ROBINHOOD CHAIN':`WRONG NETWORK · ${s.chainId??'UNKNOWN'}`}</b></div><div><span>OWNERSHIP</span><b>${s.authenticated?'SIGNATURE VERIFIED':'SIGNATURE NEEDED'}</b></div><div><span>${eligibility?.bag?`BAG #${eligibility.number}`:'CURRENT BAG'}</span><b>${!eligibility?.bag?'WAITING FOR ENTRY':!matched?'CHECKING SNAPSHOT…':eligible===true?'CREW · LOCKED IN':eligible===false?'NOT IN THIS SNAPSHOT':'CHECKING SNAPSHOT…'}</b></div></div>${s.chainId!==4663?'<button id="holder-network" class="holder-primary">SWITCH TO ROBINHOOD CHAIN ↗</button>':!s.authenticated?'<button id="holder-verify" class="holder-primary">VERIFY WALLET · SIGN MESSAGE ↗</button>':'<button id="holder-enter" class="holder-primary">BACK TO THE BAG ↗</button>'}<p class="holder-rule">${eligible===false?'This wallet cannot vote in this bag. Eligibility was locked before entry; later purchases count for future bags.':'One eligible wallet = one vote. Profit shares follow token balances at the locked snapshot.'}</p><button id="holder-claims" class="holder-secondary holder-wide">YOUR BAGS / CLAIMS ↗</button><div class="holder-footer-actions"><button id="holder-change" class="holder-text">CHANGE WALLET</button><button id="holder-disconnect" class="holder-text">DISCONNECT FROM SITE</button></div>`;
    content.querySelector('#holder-copy').onclick=()=>run(async()=>{await navigator.clipboard.writeText(s.wallet);localMessage='Wallet address copied.';});
    content.querySelector('#holder-network')?.addEventListener('click',()=>run(()=>session.switchNetwork()));
    content.querySelector('#holder-verify')?.addEventListener('click',()=>run(()=>session.authenticate()));
    content.querySelector('#holder-enter')?.addEventListener('click',()=>{close();const target=document.querySelector('#bag-room:not([hidden])')||document.querySelector('#bag-community');target?.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion:reduce)').matches?'instant':'smooth'});});
    content.querySelector('#holder-claims').onclick=()=>{close();onClaims?.();};
    content.querySelector('#holder-change').onclick=()=>run(()=>session.disconnect());
    content.querySelector('#holder-disconnect').onclick=()=>run(()=>session.disconnect());
   }
  }
  content.querySelectorAll('button:not(#holder-disconnect):not(#holder-change)').forEach(b=>b.disabled=busy);
  const phases={connecting:'OPEN YOUR WALLET · APPROVE CONNECTION',preparing:'PREPARING YOUR SIGNATURE',signing:'CHECK YOUR WALLET · SIGN THE MESSAGE',recording:'SIGNATURE SENT · WAITING FOR SERVER',network:'CHECK YOUR WALLET · SWITCH NETWORK'};
  const ready=s.authenticated&&eligibility?.wallet===s.wallet&&typeof eligibility?.eligible==='boolean';
  const notice=ready?(eligibility.eligible?'CREW ACCESS READY. Your signed vote counts once per round.':'Wallet verified. This bag’s snapshot does not include this account.'):s.notice;
  feedback.textContent=localMessage||s.error||(busy?phases[s.phase]:notice)||'You can watch without connecting.';feedback.dataset.error=String(!!(localMessage||s.error));
  dialog.setAttribute('aria-busy',String(busy||pairing));
 }
 async function connectQR(){
  if(!config?.walletconnect_enabled)throw Error('QR connection is not enabled here.');
  const ticket=++qrGeneration;pairing=true;content.innerHTML='<p class="holder-rule">Opening a secure wallet connection…</p>';
  try{
   const {createWalletConnect}=await import('./walletconnect.js');if(ticket!==qrGeneration)return;
   const connector=await createWalletConnect(config);cancelPairing=connector.cancel;if(ticket!==qrGeneration){connector.cancel();return;}
   const detail=await connector.connect(uri=>{if(ticket!==qrGeneration)return null;content.innerHTML='<div class="holder-qr-stage"><p>SCAN WITH YOUR WALLET</p><canvas id="holder-qr-code"></canvas><p>Keep this window open while you approve the connection.</p><button class="holder-secondary" id="holder-copy-uri">COPY CONNECTION LINK</button></div>';content.querySelector('button').onclick=()=>navigator.clipboard.writeText(uri).then(()=>{localMessage='Wallet connection link copied.';render();});return content.querySelector('canvas');});
   if(ticket!==qrGeneration){connector.cancel();return;}pairing=false;providerKey='';session.addProvider(detail);await session.connect(detail.info.uuid);
  }finally{if(ticket===qrGeneration){pairing=false;providerKey='';render();}}
 }
 session.subscribe(render);
 if(!test)fetch('/api/wallet-config',{cache:'no-store'}).then(r=>r.ok?r.json():null).then(d=>{config=d;render();}).catch(()=>{});
 return {open,close,setClaims(fn){onClaims=fn;},updateBag(bag,wallet){eligibility=bag?{bag:bag.id,number:bag.number,wallet,eligible:bag.eligible}:null;render();}};
}
