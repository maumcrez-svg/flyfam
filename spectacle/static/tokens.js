// Identity comes from the presentation service's chain-observed cache. Symbols
// are labels, never token IDs; addresses remain visible and authoritative.
const identities=new Map();
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const address=value=>typeof value==='string'?value:value?.token||value?.address||'';
export function rememberIdentities(rows={}){for(const [key,value]of Object.entries(rows)){identities.delete(key.toLowerCase());identities.set(key.toLowerCase(),value);}while(identities.size>1000)identities.delete(identities.keys().next().value);}
export function tokenData(value){const item=typeof value==='object'&&value?value:{token:value};const cached=identities.get(address(item).toLowerCase())||{};return {...cached,...item,token:address(item),name:item.name||cached.name,symbol:item.symbol||cached.symbol,icon_url:cached.icon_url||item.icon_url};}
export function tokenLabel(value){const t=tokenData(value);return t.symbol?`$${String(t.symbol).slice(0,24).replace(/^\$/,'')}`:t.name||'TOKEN';}
export const shortContract=value=>value?`${value.slice(0,7)}…${value.slice(-4)}`:'ADDRESS UNAVAILABLE';
export function iconURL(value){const url=tokenData(value).icon_url;return typeof url==='string'&&/^\/api\/token-icon\/4663\/0x[0-9a-f]{40}$/.test(url)?url:null;}
export function tokenIcon(value){const t=tokenData(value),url=iconURL(t),initial=String(t.symbol||t.name||'?').replace(/^\$/,'').slice(0,2);return `<span class="token-art" aria-label="${url?'Token icon':'Token icon unavailable'}"><span aria-hidden="true">${esc(initial)}</span>${url?`<img class="token-icon" src="${url}" alt="${esc(t.name||t.symbol||'Token')} icon" loading="eager" decoding="async" referrerpolicy="no-referrer">`:''}</span>`;}
export function tokenBadge(value,{contract=true}={}){const t=tokenData(value);return `<span class="token-identity">${tokenIcon(t)}<span class="token-words"><strong class="token-ticker">${esc(tokenLabel(t))}</strong><span class="token-full-name">${esc(t.name||'Name unavailable')}</span>${contract?`<span class="token-contract" title="${esc(t.token)}">${esc(shortContract(t.token))}</span>`:''}</span></span>`;}
document.addEventListener('error',event=>{if(event.target.matches?.('img.token-icon')){event.target.hidden=true;event.target.parentElement.setAttribute('aria-label','Token icon unavailable');}},true);
export async function drawTokenIcon(ctx,value,x,y,size){const url=iconURL(value);if(!url)return false;const img=new Image();img.src=url;try{await img.decode();ctx.save();ctx.beginPath();ctx.roundRect(x,y,size,size,6);ctx.clip();ctx.drawImage(img,x,y,size,size);ctx.restore();return true;}catch{return false;}}
