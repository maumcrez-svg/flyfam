// Live and fixture data, cursors and links stay in separate namespaces.
const requestedFixture=new URLSearchParams(location.search).get('fixture')==='1';
let loadedSite=null;
for(let attempt=0;attempt<3&&!loadedSite;attempt++){
 try{const r=await fetch('/api/site',{cache:'no-store',signal:AbortSignal.timeout(5000)});if(r.ok)loadedSite=await r.json();}catch{}
 if(!loadedSite&&attempt<2)await new Promise(resolve=>setTimeout(resolve,800));
}
export const siteAvailable=loadedSite!==null;
export const site=loadedSite||{};
export const testHoldersMode=site.test_holders===true;
export const fixtureMode=requestedFixture&&!testHoldersMode;
export const fixtureGateway=fixtureMode&&site.fixture!==true;
export const apiPath=path=>fixtureGateway?'/fixture'+path:path;
export const pagePath=path=>fixtureMode?path+(path.includes('?')?'&':'?')+'fixture=1':path;
export const storagePrefix=fixtureMode?'fly.fixture.v2.':'fly.v2.';
let selectedProvider=null;
export const setWalletProvider=provider=>{selectedProvider=provider;};
export const walletProvider=()=>!siteAvailable?null:testHoldersMode?window.flyTestHolderWallet:fixtureGateway?window.flyFixtureWallet:selectedProvider||window.ethereum;
if(testHoldersMode){
 const banner=document.getElementById('fixture-banner');banner.hidden=false;
 banner.innerHTML='<strong>REAL PONS DATA · PAPER POSITION · TEST HOLDERS</strong><span>Votes control the real Fly paper position. No real holder claims.</span>';
 await import('./test-holder-wallet.js');
}
if(fixtureMode){
 document.body.classList.add('fixture-mode');
 const banner=document.getElementById('fixture-banner');
 banner.hidden=false;
 banner.innerHTML=`<strong>DEMO / TEST HOLDERS${fixtureGateway?' / PAPER':''}</strong><span>${fixtureGateway?'Scripted market. Signed test votes.':'Isolated test data.'} No real funds.</span><a href="/">BACK TO LIVE ↗</a>`;
 if(fixtureGateway&&site.fixture_enabled){await import('./fixture-wallet.js');}
}
