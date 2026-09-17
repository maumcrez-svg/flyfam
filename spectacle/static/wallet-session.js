// One account/session for Bag Room and claims. Never holds keys or sends transactions.
import {apiPath,siteAvailable,testHoldersMode,fixtureMode,fixtureGateway,walletProvider,setWalletProvider,storagePrefix} from './transport.js';

export const NETWORK={chainId:'0x1237',chainName:'Robinhood Chain',nativeCurrency:{name:'Ether',symbol:'ETH',decimals:18},rpcUrls:['https://rpc.mainnet.chain.robinhood.com'],blockExplorerUrls:['https://robinhoodchain.blockscout.com']};
export const shortAccount=w=>w?`${w.slice(0,6)}…${w.slice(-4)}`:'';
const account=a=>typeof a==='string'&&/^0x[0-9a-f]{40}$/i.test(a)?a.toLowerCase():null;
export function walletError(e){
 const code=Number(e?.code??e?.cause?.code);
 if(code===4001||code===5000)return 'Request canceled in your wallet. Nothing else was submitted. Try again when ready.';
 if(code===-32002)return 'A request is already open in your wallet. Open the wallet to approve or dismiss it.';
 if(code===4100)return 'Wallet access was revoked. Reconnect to continue.';
 if(code===4200||code===-32601)return 'This wallet does not support that action. Try another wallet or switch the network inside it.';
 if(code===4900||code===4901)return 'Your wallet is offline. Reopen it and reconnect.';
 if(e?.name==='TimeoutError'||e?.name==='AbortError'||e instanceof TypeError)return 'Connection interrupted. Check the bag receipt before retrying a submitted action.';
 return String(e?.message||'Wallet request failed. Please try again.').slice(0,240);
}
const subscribers=new Set(),providers=new Map();
let revision=0,bound=null,bindings=[],intent=0;
const state={wallet:null,chainId:null,authenticated:false,phase:'idle',error:'',notice:'',providerName:'',providerId:null};
const emit=()=>subscribers.forEach(fn=>fn({...state,revision}));
const preference=()=>{try{return localStorage.getItem(storagePrefix+'wallet.provider');}catch{return null;}};
const remember=id=>{try{id?localStorage.setItem(storagePrefix+'wallet.provider',id):localStorage.removeItem(storagePrefix+'wallet.provider');}catch{}};
function clearIdentity(message=''){revision++;intent++;state.wallet=null;state.chainId=null;state.authenticated=false;state.error='';state.notice=message;state.phase='idle';emit();}
function bind(provider){
 for(const [event,fn] of bindings)bound?.removeListener?.(event,fn);
 bindings=[];bound=provider;setWalletProvider(provider);
 const listen=(event,fn)=>{provider?.on?.(event,fn);bindings.push([event,fn]);};
 listen('accountsChanged',accounts=>{revision++;state.wallet=account(accounts?.[0]);state.authenticated=false;state.notice='Account changed. Verify this wallet to vote or chat.';state.error='';emit();});
 listen('chainChanged',chain=>{revision++;state.chainId=Number(chain);state.authenticated=false;state.notice=Number(chain)===4663?'Network ready. Verify this wallet to vote or chat.':'Switch to Robinhood Chain to sign.';state.error='';emit();});
 listen('disconnect',()=>{clearIdentity('Wallet disconnected. You can keep watching.');});
}
function addProvider(detail){
 if(!detail?.provider?.request||!detail.info||providers.size>=12)return;
 const info=detail.info,id=String(info.uuid||info.rdns||'').slice(0,120);if(!id||providers.has(id))return;
 if([...providers.values()].some(x=>x.provider===detail.provider))return;
 providers.set(id,{id,provider:detail.provider,name:String(info.name||'Browser wallet').slice(0,60),
  rdns:String(info.rdns||id).slice(0,120),icon:typeof info.icon==='string'&&info.icon.length<40000&&/^data:image\/(png|webp|svg\+xml)[;,]/.test(info.icon)?info.icon:null});emit();
}
function discover(){
 if(!siteAvailable)return;
 if(testHoldersMode||fixtureGateway){
  const p=walletProvider();if(p&&!providers.size)addProvider({provider:p,info:{uuid:'test-holder',name:'Test holder wallet',rdns:'fly.test'}});
 }else{
  window.dispatchEvent(new Event('eip6963:requestProvider'));
  if(window.ethereum&&!providers.size)addProvider({provider:window.ethereum,info:{uuid:'browser',name:'Browser wallet',rdns:'browser'}});
 }
}
if(siteAvailable&&!testHoldersMode&&!fixtureGateway)window.addEventListener('eip6963:announceProvider',e=>addProvider(e.detail));
function capture(){if(!bound||!state.wallet)throw Error('Connect a wallet first.');return {provider:bound,wallet:state.wallet,revision};}
function check(c){if(c.provider!==bound||c.wallet!==state.wallet||c.revision!==revision)throw Error('Wallet or network changed. Review this account before signing again.');}
async function confirmIdentity(c){
 check(c);const accounts=await c.provider.request({method:'eth_accounts'});check(c);
 const chain=Number(await c.provider.request({method:'eth_chainId'}));check(c);
 if(account(accounts?.[0])!==c.wallet){clearIdentity('Wallet account changed. Reconnect to continue.');throw Error('Wallet account changed. Reconnect to continue.');}
 if(chain!==4663){state.chainId=chain;state.authenticated=false;emit();throw Error('Switch to Robinhood Chain to sign.');}
}
async function request(path,body){const r=await fetch(apiPath(path),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(8000)});const d=await r.json();if(!r.ok)throw Error(d.error||'Signed action could not be recorded.');return d;}
async function signed(prepare,submit,{authenticate=false,label='Review the message in your wallet.'}={}){
 if(state.phase!=='idle')throw Error('Finish the request already open in your wallet first.');
 const c=capture(),ticket=++intent;state.phase='preparing';state.error='';state.notice=label;emit();
 try{
  await confirmIdentity(c);const typed=await prepare(c.wallet);check(c);
  if(account(typed.message?.wallet)!==c.wallet||Number(typed.domain?.chainId)!==4663)throw Error('Signature request does not match this wallet and network.');
  state.phase='signing';emit();
  const signature=await c.provider.request({method:'eth_signTypedData_v4',params:[c.wallet,JSON.stringify(typed)]});
  await confirmIdentity(c);state.phase='recording';emit();
  const result=await submit(typed,signature);check(c);
  if(authenticate){if(account(result.wallet)!==c.wallet||!result.authenticated)throw Error('Wallet verification was not confirmed.');state.authenticated=true;}
  state.notice=authenticate?'Signature verified. Checking this bag’s locked snapshot.':'Signed request recorded. Final results come from the server.';return result;
 }catch(e){if(ticket===intent)state.error=walletError(e);throw e;}
 finally{if(ticket===intent){state.phase='idle';emit();}}
}
export const walletSession={
 get:()=>({...state,revision}), providers:()=>[...providers.values()], discover,
 subscribe(fn){subscribers.add(fn);fn(this.get());return()=>subscribers.delete(fn);},
 async connect(id){
  if(!siteAvailable)throw Error('The lab connection is unavailable. Reload when it reconnects.');
  if(state.phase!=='idle')return;
  const selected=providers.get(id);if(!selected)throw Error('Wallet is no longer available. Refresh the list.');
  clearIdentity();bind(selected.provider);state.providerId=id;state.providerName=selected.name;
  const ticket=++intent;state.phase='connecting';state.error='';state.notice='Approve the connection in your wallet. No funds move.';emit();
  try{
   const accounts=await selected.provider.request({method:'eth_requestAccounts'});if(ticket!==intent)return;
   const address=account(accounts?.[0]);if(!address)throw Error('No account shared. Unlock your wallet and try again.');
   const chain=Number(await selected.provider.request({method:'eth_chainId'}));if(ticket!==intent)return;
   revision++;state.wallet=address;state.chainId=chain;state.notice=chain===4663?'Connected. Verify ownership to vote and chat.':'Connected on another network. Switch to Robinhood Chain.';remember(selected.rdns);
  }catch(e){if(ticket===intent)state.error=walletError(e);throw e;}finally{if(ticket===intent){state.phase='idle';emit();}}
 },
 async restore(){
  discover();const preferred=preference();const selected=[...providers.values()].find(p=>p.rdns===preferred);
  if(!selected||state.wallet||state.phase!=='idle')return;
  const ticket=++intent;bind(selected.provider);
  try{const accounts=await selected.provider.request({method:'eth_accounts'});const chain=Number(await selected.provider.request({method:'eth_chainId'}));if(ticket!==intent)return;
   state.wallet=account(accounts?.[0]);state.chainId=chain;state.providerId=selected.id;state.providerName=selected.name;state.notice=state.wallet?'Wallet reconnected. Verify ownership to vote and chat.':'';emit();
  }catch{} // Passive restoration never prompts and never authenticates.
 },
 async disconnect(){
  const old=bound,oldId=state.providerId;if(oldId==='walletconnect')providers.delete(oldId);clearIdentity('Disconnected from this site. Your wallet permissions remain under your control.');remember(null);
  for(const [event,fn] of bindings)old?.removeListener?.(event,fn);bindings=[];bound=null;setWalletProvider(null);state.providerId=null;state.providerName='';emit();
  if(old?.isWalletConnect)try{await old.disconnect();}catch{}
 },
 async switchNetwork(){
  if(!bound||state.phase!=='idle')return;const p=bound,ticket=++intent;
  state.phase='network';state.error='';state.notice='Approve Robinhood Chain in your wallet.';emit();
  try{
   try{await p.request({method:'wallet_switchEthereumChain',params:[{chainId:NETWORK.chainId}]});}
   catch(e){if(Number(e.code)!==4902)throw e;await p.request({method:'wallet_addEthereumChain',params:[NETWORK]});await p.request({method:'wallet_switchEthereumChain',params:[{chainId:NETWORK.chainId}]});}
   if(p!==bound||ticket!==intent)return;revision++;state.chainId=Number(await p.request({method:'eth_chainId'}));state.authenticated=false;
   if(state.chainId!==4663)throw Error('The wallet is still on another network. Switch to Robinhood Chain inside it.');state.notice='Robinhood Chain is ready. Verify your wallet to continue.';
  }catch(e){if(ticket===intent)state.error=walletError(e);throw e;}finally{if(ticket===intent){state.phase='idle';emit();}}
 },
 authenticate(){return signed(wallet=>request('/api/bags/challenge',{wallet,action:'AUTH',bag_id:'',round_id:0,choice:'',content:''}),
  (typed,signature)=>request('/api/bags/action',{nonce:typed.message.nonce,signature}),{authenticate:true,label:'Verify ownership. This signature cannot move funds.'});},
 signed, capture, check,
 addProvider,
 testMode:testHoldersMode||fixtureMode,
 available:siteAvailable,
};
discover();setTimeout(()=>walletSession.restore(),150);
