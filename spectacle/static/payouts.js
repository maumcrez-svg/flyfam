import {apiPath} from './transport.js';
import {walletSession,walletError} from './wallet-session.js';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=n=>{try{let v=BigInt(n),a=v<0n?-v:v;return `${v<0n?'−':''}${a/10n**18n}.${(a%10n**18n).toString().padStart(18,'0').slice(0,8)} ETH`;}catch{return 'UNAVAILABLE';}};
const explorer='https://robinhoodchain.blockscout.com';
function proof(hash,fixture,type='tx'){
 if(!hash)return '';
 if(fixture)return `<span class="bag-fine payout-hash">LOCAL ANVIL ${type.toUpperCase()} ${esc(hash)}</span>`;
 const valid=type==='tx'?/^0x[0-9a-fA-F]{64}$/:/^0x[0-9a-fA-F]{40}$/;
 return valid.test(hash)?`<a class="payout-hash" href="${explorer}/${type}/${hash}" target="_blank" rel="noopener noreferrer">${type==='tx'?'TX':'PAYOUT WALLET'} ${esc(hash)} ↗</a>`:'';
}
async function request(path,body){const r=await fetch(apiPath(path),{cache:'no-store',signal:AbortSignal.timeout(8000),...(body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})});const data=await r.json();if(!r.ok)throw Error(data.error||'Payout unavailable');return data;}

export function mountPayouts(dialog,access){
 const surface=document.createElement('section');surface.id='holder-payouts';surface.hidden=true;surface.className='bag-community';
 document.querySelector('#economics').before(surface);
 async function refreshSummary(){try{const s=await request('/api/vault/summary');surface.hidden=!s.configured;if(!s.configured)return;
  surface.innerHTML=`<span class="eyebrow">${s.fixture?'FIXTURE · LOCAL ANVIL · TEST FUNDS':'COMMUNITY VAULT'}</span><h2>HOLDER PAYOUT WALLET.</h2>${proof(s.payout_wallet,s.fixture,'address')}<div class="payout-totals"><div>FUNDED<strong>${money(s.funded)}</strong></div><div>PAID<strong>${money(s.paid)}</strong></div><div>UNCLAIMED<strong>${money(s.unclaimed)}</strong></div></div><p class="bag-fine">Realized bag profit only. Gas reserve is separate. ${esc(s.reconciliation?.status||'RECONCILING')}</p>${s.distributions.map(d=>`<details><summary>BAG #${d.number} · ${esc(d.status)} · ${money(d.realized_holder_profit)} TO HOLDERS</summary><p class="bag-fine">SNAPSHOT BLOCK ${d.snapshot_block}<br>ALLOCATED ${money(d.allocated)}<br>PAID ${money(d.paid)}<br>UNCLAIMED ${money(d.unclaimed)}<br>CLAIM DEADLINE ${d.deadline?new Date(d.deadline*1000).toLocaleString():'AWAITING FUNDING'}</p>${proof(d.funding_transaction,d.fixture)}${d.sweep_transaction?`<p>UNCLAIMED RETURNED TO FLY</p>${proof(d.sweep_transaction,d.fixture)}`:''}</details>`).join('')}`;
 }catch{surface.dataset.status='unavailable';surface.querySelector('.bag-fine')?.replaceChildren(document.createTextNode('Payout data unavailable. These are the last confirmed totals.'));}}
 refreshSummary();setInterval(()=>{if(!document.hidden)refreshSummary();},10000);
 let timer=null,activeWallet=null,loading=false,notice='',activeRevision=null,claimView=0;
 walletSession.subscribe(s=>{if(activeWallet&&(s.wallet!==activeWallet||s.revision!==activeRevision)){clearTimeout(timer);claimView++;loading=false;activeWallet=null;notice='';if(dialog.open)dialog.close();}});
 dialog.addEventListener('close',()=>{clearTimeout(timer);claimView++;loading=false;activeWallet=null;});
 async function renderClaims(){
  const wallet=activeWallet,ticket=claimView;if(!wallet||loading)return;loading=true;
  try{
   const d=await request(`/api/claims/${encodeURIComponent(wallet)}`);if(ticket!==claimView||wallet!==activeWallet)return;
   document.getElementById('bag-receipt-body').innerHTML=`<span class="eyebrow">HOLDER PAYOUTS</span><h2>YOUR BAGS</h2><p class="bag-fine">ACCOUNT ${esc(wallet)}</p>${notice?`<p class="bag-fine payout-notice" role="status">${esc(notice)}</p>`:''}<p class="bag-fine">Your share follows your balance at the snapshot. Voting is not required. Sign to claim; you pay no gas.</p>${d.claims.map((c,i)=>`<article class="bag-receipt"><span>BAG #${c.number} · ${c.fixture?'FIXTURE / LOCAL TEST FUNDS · ':''}${c.status==='CONFIRMED'?'PAID':esc(c.status)}</span><strong>YOUR SHARE ${money(c.allocation.amount)}</strong><small>SNAPSHOT BALANCE ${esc(c.allocation.snapshot_balance)} BASE UNITS<br>ECONOMIC SHARE ${esc(c.economic_share_percent??'—')}%<br>NET PROFIT TO HOLDERS ${money(c.funded_amount)}<br>DEADLINE ${c.deadline?new Date(c.deadline*1000).toLocaleString():'AWAITING FUNDING'}</small>${proof(c.payout_wallet,c.fixture,'address')}${c.transaction_hash?proof(c.transaction_hash,c.fixture):''}${c.sweep_transaction?`<p>UNCLAIMED RETURNED TO FLY</p>${proof(c.sweep_transaction,c.fixture)}`:''}<button class="text-button" data-payout-claim="${i}" ${c.mode==='PAYOUT_WALLET'&&c.claimable?'':'disabled'}>${c.status==='CONFIRMED'?'PAID':c.status==='PENDING'?'PENDING · AWAITING RECEIPT':c.status==='EXPIRED'?'EXPIRED':'CLAIM · SIGN ONLY'}</button>${c.payment?.error?`<small>${esc(c.payment.error)}</small>`:''}</article>`).join('')}${d.claims.length?'':'<p>No funded holder allocations for this wallet. PAPER results and TEST HOLDERS do not create real-money claims.</p>'}`;
   document.querySelectorAll('[data-payout-claim]').forEach(button=>button.onclick=async()=>{
    if(ticket!==claimView)return;clearTimeout(timer);loading=true;notice='';button.disabled=true;
    try{
     const c=d.claims[Number(button.dataset.payoutClaim)];
     if(walletSession.get().chainId!==4663){dialog.close();access.open('claims');return;}
     const path=`/api/claims/${encodeURIComponent(c.bag_id)}`;
     const result=await walletSession.signed(async current=>{
      if(current!==wallet)throw Error('Wallet changed. Reopen your allocations.');
      button.textContent='CHECK YOUR WALLET · SIGN MESSAGE';
      return (await request(path,{wallet:current})).typed_data;
     },async(typed,signature)=>{
      button.textContent='REQUEST SENT · WAITING FOR SERVER';
      return request(path,{nonce:typed.message.nonce,signature});
     });
     button.textContent=result.status==='CONFIRMED'?'PAID':'PENDING · AWAITING RECEIPT';
    }catch(e){if(ticket===claimView)notice=walletError(e);}
    finally{if(ticket===claimView){loading=false;if(activeWallet)await renderClaims().catch(()=>{});}}
   });
   if(d.claims.some(c=>c.status==='PENDING'))timer=setTimeout(()=>renderClaims().catch(()=>{}),2000);
  }catch(e){if(ticket===claimView&&activeWallet){const body=document.getElementById('bag-receipt-body');body.textContent='PAYOUT DATA UNAVAILABLE. Reopen to retry.';throw e;}}finally{if(ticket===claimView)loading=false;}
 }
 return async()=>{
  const s=walletSession.get();if(!s.wallet){access.open('claims');return;}
  claimView++;loading=false;activeWallet=s.wallet;activeRevision=s.revision;notice='';
  clearTimeout(timer);document.getElementById('bag-receipt-body').textContent='LOADING YOUR BAGS…';if(!dialog.open)dialog.showModal();await renderClaims();
 };
}
