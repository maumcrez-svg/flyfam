import {walletSession, walletError} from './wallet-session.js';
import {mountHolderAccess} from './holder-access.js';
import {mountPayouts} from './payouts.js';
import {apiPath,pagePath,fixtureMode,site} from './transport.js';
import {tokenLabel} from './tokens.js';
const $=id=>document.getElementById(id), short=w=>w?`${w.slice(0,6)}…${w.slice(-4)}`:'', esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const wei=n=>{try{const v=BigInt(n),a=v<0n?-v:v;return `${v<0n?'−':''}${a/10n**18n}.${(a%10n**18n).toString().padStart(18,'0').slice(0,6)} ETH`;}catch{return 'unavailable';}};
const time=s=>`${Math.floor(s/60).toString().padStart(2,'0')}:${Math.floor(s%60).toString().padStart(2,'0')}`;
export function createBagRoom({getMode,onMoment}){
 let data=null,wallet=null,authenticated=false,cursor=0,first=true,busy=false,received=0,selected=null,previousChat='',pollError=false,refreshBusy=false,dataWallet=null;
 const panel=document.createElement('section');panel.id='bag-room';panel.hidden=true;
 panel.innerHTML=`<div class="bag-kicker"><span id="bag-number">BAG ROOM</span><span id="bag-status"></span></div><p id="bag-fixture" class="bag-fixture" hidden>LOCAL DEMO · FIXTURE TOKEN + TEST WALLETS · PAPER</p><div id="bag-moment" class="bag-moment" aria-live="polite">THE FLY PICKS. THE CREW DECIDES.</div><div class="bag-round"><span id="bag-round-label">SNAPSHOT PENDING</span><strong id="bag-clock">—</strong></div><p id="bag-autoexit" class="bag-fine" role="status" hidden></p><div id="bag-voting"><h3 class="sr-only">HOLD THE BAG?</h3><div class="bag-buttons"><button id="bag-hold">HOLD <strong id="bag-hold-count">0</strong></button><button id="bag-exit">EXIT <strong id="bag-exit-count">0</strong></button></div><div class="bag-vote-bar"><i id="bag-hold-bar"></i></div><div id="bag-counts" class="bag-counts">Waiting for eligibility</div></div><button id="bag-connect" class="text-button">CONNECT WALLET →</button><button id="bag-my-claims" class="text-button">YOUR BAG ALLOCATIONS →</button><p id="bag-eligibility" class="bag-fine"></p><p id="bag-message" class="bag-fine" role="status"></p><details class="crew-chat"><summary class="bag-kicker"><span>CREW CHAT ↗</span><span id="bag-chat-count">0 MESSAGES</span></summary><div id="bag-chat" role="log" aria-label="Bag crew chat"></div><form id="bag-chat-form"><label class="sr-only" for="bag-chat-input">Message the crew</label><input id="bag-chat-input" maxlength="400" placeholder="Say it to the crew…" autocomplete="off"><button id="bag-chat-send" type="submit">SEND ↗</button></form></details><details class="bag-proof-details"><summary>SNAPSHOT / SIGNED VOTE RECEIPT</summary><p id="bag-proof" class="bag-fine"></p><a id="bag-audit" target="_blank" rel="noopener">AUDIT JOURNAL ↗</a></details>`;
 document.querySelector('#position-panel .chart-label').before(panel);
 const lower=document.createElement('section');lower.id='bag-community';lower.hidden=true;
 lower.innerHTML=`<div class="bag-community-heading"><div><span class="eyebrow">THE CREW'S PUBLIC RECORD</span><h2>EVERY BAG LEAVES A RECEIPT.</h2></div><div class="bag-vault"><span>PAPER COMMUNITY VAULT</span><strong id="bag-vault-value">0 ETH</strong><small>Realized profit reserved. No claims enabled.</small></div></div><div class="bag-community-grid"><div><h3>CLOSED BAGS</h3><div id="bag-history"></div><button id="bag-live" class="text-button" hidden>BACK TO LIVE BAG →</button></div><div><h3>CREW PARTICIPATION</h3><p class="bag-fine">Participation counts. Not a profitability ranking.</p><div id="bag-leaderboard"></div></div></div>`;
 document.querySelector('#economics').before(lower);
 lower.querySelector('.bag-community-heading').append($('bag-my-claims'));
 lower.insertAdjacentHTML('afterbegin','<div id="bag-access" class="bag-access"><div><span class="eyebrow" id="bag-access-state">HOLDER ACCESS</span><h2>THE FLY PICKS.<br>THE CREW DECIDES.</h2><p id="bag-access-copy">Connecting to the Bag Room.</p></div><div class="bag-access-rules"><span><b>01</b> SNAPSHOT LOCKS THE CREW</span><span><b>02</b> ONE WALLET. ONE VOTE.</span><span><b>03</b> PROFIT FOLLOWS SNAPSHOT BALANCES</span><a id="bag-demo-link" class="solid-button" href="/?fixture=1">TRY THE BAG ROOM DEMO ↗</a></div></div><p id="bag-access-message" class="bag-fine" role="status"></p>');
 $('bag-demo-link').hidden=!site.fixture_enabled||fixtureMode;
 const accessLink=document.querySelector('[data-bag-access]');
 if(accessLink)accessLink.onclick=e=>{e.preventDefault();(panel.hidden?lower:panel).scrollIntoView({behavior:'smooth'});};
 const receipt=document.createElement('dialog');receipt.id='bag-receipt-dialog';receipt.innerHTML='<button id="bag-receipt-close" class="text-button">CLOSE RECEIPT ×</button><div id="bag-receipt-body"></div>';document.body.append(receipt);$('bag-receipt-close').onclick=()=>receipt.close();
 const access=mountHolderAccess();
 const say=s=>{$('bag-message').textContent=s;if(panel.hidden){$('bag-access-message').textContent=s;}};
 async function request(path,body){const res=await fetch(apiPath(path),{cache:'no-store',signal:AbortSignal.timeout(8000),...(body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})});const d=await res.json();if(!res.ok)throw Error(d.error||'Bag Room unavailable');return d;}
 function current(){return data?.bag;}
 async function sign(action,choice='',content=''){
  const b=current();
  return walletSession.signed(wallet=>request('/api/bags/challenge',{wallet,action,bag_id:b?.id,round_id:action==='VOTE'?b?.round?.number:0,choice,content}),
   (typed,signature)=>request('/api/bags/action',{nonce:typed.message.nonce,signature}));
 }
 async function action(task){if(busy)return;busy=true;render();try{await task();say('SIGNED ACTION RECORDED.');await refresh();}catch(e){say(walletError(e));}finally{busy=false;render();}}
 $('bag-connect').onclick=()=>access.open();
 for(const choice of ['HOLD','EXIT'])$(`bag-${choice.toLowerCase()}`).onclick=()=>action(async()=>{await sign('VOTE',choice);});
 $('bag-chat-form').onsubmit=e=>{e.preventDefault();const content=$('bag-chat-input').value;action(async()=>{await sign('CHAT','',content);$('bag-chat-input').value='';});};
 const openClaims=mountPayouts(receipt,access);
 access.setClaims(()=>openClaims().catch(e=>say(walletError(e))));
 $('bag-my-claims').onclick=()=>openClaims().catch(e=>say(walletError(e)));
 $('bag-live').onclick=()=>{selected=null;refresh();};
 function clock(){const b=current();if(!b||panel.hidden)return;const now=(data.server_time||0)+(Date.now()-received)/1000,r=b.round;
  $('bag-clock').textContent=r?.status==='OPEN'?time(Math.max(0,r.closes_at-now)):b.status==='CLOSED'?'CLOSED':'PENDING';
  $('bag-clock').classList.toggle('urgent',r?.status==='OPEN'&&r.closes_at-now<8);
  if(r?.status==='OPEN'&&now>=r.closes_at){$('bag-hold').disabled=true;$('bag-exit').disabled=true;}
 }
 function render(){
  const b=current(),replay=getMode()!=='LIVE',session=walletSession.get(),working=busy||session.phase!=='idle';
  access.updateBag(b?{...b,eligible:pollError?null:b.eligible}:null,dataWallet);panel.hidden=!data?.configured||!b||replay;lower.hidden=false;
  const configured=!!data?.configured;
  $('bag-access').hidden=configured&&!!b;
  lower.querySelector('.bag-community-grid').hidden=!configured;
  lower.querySelector('.bag-vault').hidden=!configured;
  lower.querySelector('.bag-community-heading h2').textContent=configured?'EVERY BAG LEAVES A RECEIPT.':'YOUR SHARE STARTS WITH A SNAPSHOT.';
  $('bag-access-state').textContent=pollError?'HOLDER ACCESS UNAVAILABLE':configured?'WAITING FOR THE NEXT FLY ENTRY':data?'PROJECT TOKEN NOT LAUNCHED':'CONNECTING';
  $('bag-access-copy').textContent=pollError?'The Bag Room connection is unavailable. No cached votes are treated as current.':configured?'The next confirmed fly entry opens the next room. Eligibility is locked before publication.':'The live Fly is trading in paper. Real holders activate after the project token is configured. Claims require realized profit confirmed in the Holder Payout Wallet.';
  $('bag-my-claims').disabled=working||pollError||!data;
  document.body.classList.toggle('in-bag',!panel.hidden&&b.status!=='CLOSED');
  if(!b||panel.hidden)return;
  const testHolders=b.entry.holder_source==='FIXTURE'&&b.entry.bag_position_source==='REAL_WORKER';
  $('bag-fixture').hidden=!data.fixture&&!testHolders;
  $('bag-fixture').textContent=testHolders?'REAL PONS DATA · PAPER POSITION · TEST HOLDERS':`LOCAL DEMO · FIXTURE TOKEN + TEST WALLETS · ${b.entry.execution==='LIVE'?'LOCAL TEST TRANSACTIONS':'PAPER'}`;
  const healthy=!pollError&&data.heartbeat?.status==='READY'&&data.server_time-data.heartbeat.ts<15;
  $('bag-number').textContent=`BAG #${String(b.number).padStart(4,'0')} · ${selected?'RECEIPT':'BAG ROOM'}`;
  $('bag-status').textContent=!healthy?'ROOM OFFLINE':b.status==='OPEN'?'LIVE':b.status.replaceAll('_',' ');
  const r=b.round,total=r?.votes_cast||0,eligible=b.snapshot?.eligible_wallet_count||0;
  const auto=b.auto_exit,policy=auto?.policy,autoReason={
   AUTO_EXIT_TAKE_PROFIT:'PROFIT TARGET',AUTO_EXIT_STOP_LOSS:'LOSS LIMIT',AUTO_EXIT_INACTIVE:'NO MARKET TRADES',
   AUTO_EXIT_MAX_HOLD:'MAXIMUM HOLD WITHOUT COMMUNITY ACTION'
  };
  $('bag-autoexit').hidden=!auto;
  if(auto){
   const label=auto.status==='ARMED'?'AUTO EXIT ARMED':auto.status==='VOTE_PENDING'?'VOTE RECEIVED · AUTO EXIT PAUSED':auto.status==='CLOSED'?'AUTO EXIT POLICY':auto.status==='EXIT_PENDING'?'EXIT IN PROGRESS':`COMMUNITY CONTROL · ${auto.empty_rounds}/${policy.empty_rounds} EMPTY ROUNDS`;
   const holds=`${policy.min_hold_seconds!=null?` · NOT BEFORE ${policy.min_hold_seconds}s HELD`:''}${policy.max_hold_seconds!=null?` · ${policy.max_hold_seconds}s MAX WITHOUT A HOLD VOTE`:''}`;
   $('bag-autoexit').textContent=`${label} · +${policy.profit_bps/100}% / −${policy.loss_bps/100}% ${policy.return_basis==='GROSS'?'GROSS':'NET'} · ${policy.idle_seconds}s WITHOUT TRADES${holds}${auto.status==='ARMED'&&auto.observation_status!=='FRESH'?' · WAITING FOR FRESH QUOTE':''}`;
  }
  $('bag-round-label').textContent=b.status.startsWith('EXIT')?'EXIT REQUESTED':b.status==='SNAPSHOT_PENDING'?'LOCKING FINALIZED HOLDERS':r?`HOLD THE BAG? · ROUND ${String(r.number).padStart(2,'0')}`:'NO ROUND';
  $('bag-voting').hidden=b.status==='CLOSED';
  $('bag-hold-count').textContent=r?.hold||0;$('bag-exit-count').textContent=r?.exit||0;
  $('bag-hold-bar').style.width=total?`${(r.hold/total)*100}%`:'0%';
  $('bag-counts').textContent=`${total} / ${eligible} ELIGIBLE HOLDERS VOTED · ${(r?.participation_pct||0).toFixed(1)}% PARTICIPATION${total?` · HOLD ${Math.round(r.hold/total*100)}% / EXIT ${Math.round(r.exit/total*100)}%`:''}`;
  for(const choice of ['HOLD','EXIT']){const el=$(`bag-${choice.toLowerCase()}`);el.disabled=working||!healthy||!authenticated||dataWallet!==wallet||!b.eligible||b.status!=='OPEN'||r?.status!=='OPEN';el.setAttribute('aria-pressed',String(r?.my_vote===choice));}
  $('bag-connect').textContent=wallet?`${short(wallet)} · ${authenticated?'VERIFIED ✓':session.chainId!==4663?'SWITCH NETWORK':'VERIFY WALLET'} →`:'CONNECT WALLET →';$('bag-connect').disabled=false;
  $('bag-eligibility').textContent=wallet?(dataWallet!==wallet?'CHECKING THIS WALLET’S SNAPSHOT…':b.eligible?'CREW · Your eligibility is locked for this bag.':'NOT ELIGIBLE TO VOTE IN THIS BAG · Buyers after the snapshot join future bags. You can still talk in the crew chat.'):testHolders?'Connect a labeled test wallet. It controls this real PAPER position.':'Read along. Connect to check your locked eligibility.';
  $('bag-chat-input').disabled=working||!healthy||!authenticated||dataWallet!==wallet||b.status==='CLOSED';$('bag-chat-send').disabled=$('bag-chat-input').disabled;
  const chatKey=JSON.stringify(data.chat);
  if(previousChat!==chatKey){previousChat=chatKey;$('bag-chat').innerHTML=data.chat.length?data.chat.map(m=>`<p><b>${esc(short(m.wallet))} <i${m.holder?'':' class="chat-visitor"'}>${m.holder?'CREW':'VISITOR'}</i></b><span>${esc(m.message)}</span></p>`).join(''):'<p class="bag-fine">No messages yet. Everyone reads; any verified wallet writes. Only locked holders vote.</p>';$('bag-chat').scrollTop=$('bag-chat').scrollHeight;}
  $('bag-chat-count').textContent=`${b.chat_count} MESSAGES`;
  $('bag-proof').textContent=b.snapshot?`BLOCK ${b.snapshot.snapshot_block} · ${b.snapshot.snapshot_block_hash}\n${b.snapshot.snapshot_hash}\nEligibility stays fixed after sale. Votes may be replaced until the round closes. A tie exits; ${auto?`${policy.empty_rounds} empty rounds arm auto exit.`:'no votes holds.'}`:'Waiting for a verified finalized block strictly before entry.';
  $('bag-audit').href=apiPath(`/api/bags/audit?id=${encodeURIComponent(b.id)}`);
  if(b.status==='CLOSED')$('bag-moment').textContent=`CLOSED · ${wei(b.result.net_pnl_wei)} NET ${b.entry.execution||'PAPER'} · ${wei(b.result.vault_credit_wei)} RESERVED`;
  else if(b.status.startsWith('EXIT'))$('bag-moment').textContent=`${b.exit_intent?.source==='AUTO_EXIT'?`AUTO EXIT · ${autoReason[b.exit_intent.reason]||'POLICY'}`:'COMMUNITY CHOSE EXIT'} · ${b.exit_intent?.status==='SELLING'?'AWAITING CONFIRMED CLOSE':'EXECUTION PENDING'}${b.exit_intent?.detail?' · '+b.exit_intent.detail.replaceAll('_',' '):''}`;
  else if(auto?.status==='ARMED')$('bag-moment').textContent='NO VOTES. AUTO EXIT IS WATCHING THE BAG.';
  else if(r?.my_vote)$('bag-moment').textContent=`YOU CHOSE ${r.my_vote}. THE ROUND IS STILL OPEN.`;
  else $('bag-moment').textContent=b.status==='OPEN'?`${eligible} ${testHolders?'TEST HOLDERS':'HOLDERS'} LOCKED IN. THE EXIT IS YOURS.`:'SNAPSHOT VERIFICATION IN PROGRESS.';
  const liveMoney=b.entry.execution==='LIVE';
  $('bag-vault-value').textContent=liveMoney?'BAG-SPECIFIC CLAIMS':wei(data.vault.balance_wei);
  document.querySelector('.bag-vault>span').textContent=liveMoney?'HOLDER DISTRIBUTIONS':testHolders?'PAPER RESERVE · TEST HOLDERS':'PAPER COMMUNITY VAULT';
  document.querySelector('.bag-vault>small').textContent=liveMoney?'Only funded distributions can be claimed. Open Your Bag Allocations.':'Realized profit reserved. No claims enabled.';
  $('bag-history').innerHTML=data.history.length?data.history.map(h=>`<button class="bag-receipt" data-bag="${esc(h.id)}"><span>BAG #${String(h.number).padStart(4,'0')} · CLOSED ${h.result.execution||'PAPER'}</span><b>${esc(tokenLabel({token:h.token}))}</b><strong>${wei(h.result.net_pnl_wei)}</strong><small>${wei(h.result.vault_credit_wei)} VAULTED · VIEW RECEIPT ↗</small></button>`).join(''):'<p class="bag-fine">The first confirmed close becomes a permanent bag receipt.</p>';
  $('bag-history').querySelectorAll('[data-bag]').forEach(el=>el.onclick=()=>{openReceipt(el.dataset.bag);});
  $('bag-live').hidden=!selected;
  $('bag-leaderboard').innerHTML=data.leaderboard.length?data.leaderboard.map((w,i)=>`<div class="crew-row"><b>${String(i+1).padStart(2,'0')}</b><span>${esc(short(w.wallet))}<small>${w.bags_participated} BAGS · ${w.votes_cast} ROUND VOTES · STREAK ${w.participation_streak}<br>${w.hold_votes} HOLD / ${w.exit_votes} EXIT</small></span></div>`).join(''):'<p class="bag-fine">Only real signed participation will appear here.</p>';
  clock();
 }
 async function openReceipt(id){try{const d=await request(`/api/bags?id=${encodeURIComponent(id)}`),b=d.bag;const r=b.result;$('bag-receipt-body').innerHTML=`<p class="bag-fixture">${b.entry.holder_source==='FIXTURE'&&b.entry.bag_position_source==='REAL_WORKER'?'REAL PONS / TEST HOLDERS · ':d.fixture?'LOCAL FIXTURE DEMO · ':''}CLOSED ${b.entry.execution||'PAPER'} BAG</p><h2>BAG #${String(b.number).padStart(4,'0')} · ${esc(tokenLabel({token:b.token}))}</h2><p class="bag-fine">${esc(b.token)}</p><strong class="receipt-pnl">${wei(r?.net_pnl_wei)} NET</strong><p>${wei(r?.vault_credit_wei)} ${b.entry.execution==='LIVE'?'HOLDER PROFIT · FUNDING/CLAIMS IN YOUR BAGS':'RESERVED IN THE PAPER COMMUNITY VAULT'}</p><p class="bag-fine">ENTRY VALUE ${wei(String(Math.round((b.entry.size_eth||0)*1e18)))} · ${new Date(b.opened_at*1000).toLocaleString()}<br>${b.snapshot?.eligible_wallet_count||0} LOCKED HOLDERS · ${b.round_count} ROUNDS · ${b.chat_count} CHAT MESSAGES<br>EXIT: ${esc(r?.auto_exit_reason||r?.close?.close_reason||b.status)}</p>${b.entry.execution!=='LIVE'?`<h3>WHO GOT WHAT — PAPER</h3><p class="bag-fine">ENTRY PRINCIPAL ${wei(r?.entry_principal_wei)}<br>NET EXIT PROCEEDS ${wei(r?.exit_proceeds_wei)}<br>MODELED COSTS ${wei(r?.costs_wei)}<br>PRINCIPAL RETURNED ${wei(r?.principal_returned_wei)}<br>NET RESULT ${wei(r?.net_pnl_wei)}<br>PAPER HOLDER RESERVE ${wei(r?.vault_credit_wei)}<br>REAL CLAIMABLE: NONE</p>`:''}${b.entry.execution==='LIVE'?`<h3>WHO GOT WHAT</h3><p>ENTRY PRINCIPAL ${wei(r.entry_principal)}<br>NET EXIT ${wei(r.net_exit_proceeds)}<br>RETURNED TO FLY ${wei(r.principal_returned_to_fly)}<br>HOLDER PROFIT ${wei(r.holder_profit)}</p><p class="bag-fine">Integer amounts from finalized receipts. Funding and claims have separate on-chain confirmations.</p>`:''}<h3>COMMUNITY VOTE TIMELINE</h3>${b.rounds.slice().reverse().map(x=>`<div class="crew-row"><b>${String(x.number).padStart(2,'0')}</b><span>${esc(x.result?.decision||x.status)}<small>${x.hold} HOLD / ${x.exit} EXIT</small></span></div>`).join('')}<p class="bag-fine">${b.round_count>b.rounds.length?'Latest 100 rounds shown; the full signed history is in the paginated audit.':''}</p><a href="${pagePath(`/episode/${encodeURIComponent(b.episode_id)}`)}">REPLAY FLY EPISODE ↗</a> · <a href="${apiPath(`/api/bags/audit?id=${encodeURIComponent(b.id)}`)}">SIGNED AUDIT ↗</a><button id="bag-copy-receipt" class="text-button">COPY BAG LINK ↗</button>`;receipt.showModal();$('bag-copy-receipt').onclick=()=>navigator.clipboard.writeText(location.origin+pagePath(`/?bag=${encodeURIComponent(b.id)}`));}catch(e){say(e.message);}}
 const requestedBag=new URLSearchParams(location.search).get('bag');if(requestedBag)openReceipt(requestedBag);
 async function refresh(){if(refreshBusy)return;refreshBusy=true;try{const askedWallet=wallet;const q=new URLSearchParams({after:String(cursor)});if(wallet)q.set('wallet',wallet);if(selected)q.set('id',selected);const d=await request(`/api/bags?${q}`);if(askedWallet!==wallet)return;received=Date.now();pollError=false;data=d;dataWallet=askedWallet;
   if(!first&&getMode()==='LIVE')for(const e of d.events||[]){if(e.bag_id!==d.bag?.id)continue;if(['VOTE_CAST','VOTE_REPLACED','CHAT_MESSAGE'].includes(e.kind)){panel.classList.remove('bag-pulse');void panel.offsetWidth;panel.classList.add('bag-pulse');}if(['COMMUNITY_HOLD','COMMUNITY_EXIT','AUTO_EXIT_TRIGGERED','BAG_CLOSED'].includes(e.kind))onMoment(e.kind);}
   cursor=d.next_after??cursor;if(first)cursor=d.seq||cursor;first=false;render();
  }catch{pollError=true;say('Connection lost. Cached votes are not current. Reconnecting…');render();}finally{refreshBusy=false;}}
 walletSession.subscribe(s=>{const changed=wallet!==s.wallet;wallet=s.wallet;authenticated=s.authenticated;render();if(changed)refresh();});
 refresh();setInterval(refresh,1200);setInterval(()=>{renderVisibility();clock();},1000);
 function renderVisibility(){if(getMode()!=='LIVE'){panel.hidden=true;document.body.classList.remove('in-bag');}else if(data?.bag&&data.configured)panel.hidden=false;}
 return {current:()=>data?.bag,serverNow:()=>data?.server_time?data.server_time+(Date.now()-received)/1000:null,render};
}
