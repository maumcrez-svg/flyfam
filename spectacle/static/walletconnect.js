import {brand} from './brand.js';
// Loaded only on explicit QR action, and only when the deployment has a public Project ID.
import {EthereumProvider,QRCode} from './vendor/walletconnect.js';
export async function createWalletConnect(config){
 if(!config.walletconnect_enabled||!/^[a-f0-9]{32}$/i.test(config.walletconnect_project_id||''))throw Error('QR connection is not enabled on this deployment.');
 const provider=await EthereumProvider.init({projectId:config.walletconnect_project_id,
  metadata:{name:brand.displayName,description:'Holder access to the FLYFAM Bag Room',url:location.origin,icons:[new URL(brand.avatar,location.origin).href]},
  showQrModal:false,telemetryEnabled:false,methods:[],events:[],optionalChains:[4663],optionalMethods:['eth_accounts','eth_requestAccounts','eth_signTypedData_v4','wallet_switchEthereumChain','wallet_addEthereumChain'],
  optionalEvents:['accountsChanged','chainChanged'],rpcMap:{4663:config.wallet_rpc},disableProviderPing:true});
 let canceled=false;
 return {cancel(){canceled=true;provider.disconnect().catch(()=>{});},async connect(show){
  provider.on('display_uri',uri=>{if(canceled)return;const canvas=show(uri);if(canvas)QRCode.toCanvas(canvas,uri,{width:280,margin:2,errorCorrectionLevel:'M'}).catch(()=>{});});
  await provider.connect();if(canceled){await provider.disconnect();throw Error('Wallet connection closed.');}
  return {provider,info:{uuid:'walletconnect',rdns:'org.walletconnect',name:provider.session?.peer?.metadata?.name||'WalletConnect'}};
 }};
}
