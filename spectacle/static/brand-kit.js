import {brand} from './brand.js';
import {drawBrandBanner,loadBrandImage} from './brand-art.js';
const status=document.getElementById('brand-kit-status');
const banner=document.getElementById('brand-banner');
const ready=drawBrandBanner(banner);
ready.catch(()=>{status.textContent='The banner could not load. Reload to try again.';});
function save(canvas,filename){return new Promise((resolve,reject)=>canvas.toBlob(blob=>{if(!blob)return reject(Error('Image export unavailable.'));const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),5000);resolve();},'image/png'));}
async function run(button,task){button.disabled=true;status.textContent='PREPARING YOUR FILE…';try{await task();status.textContent='DOWNLOAD READY.';}catch(e){status.textContent=e.message||'Download unavailable. Try again.';}finally{button.disabled=false;}}
document.getElementById('download-banner').onclick=e=>run(e.currentTarget,async()=>{await ready;await save(banner,'flyfam-banner-1500x500.png');});
document.getElementById('download-avatar').onclick=e=>run(e.currentTarget,async()=>{const img=await loadBrandImage(brand.avatar);const c=document.createElement('canvas');c.width=c.height=512;c.getContext('2d').drawImage(img,0,0,512,512);await save(c,'flyfam-avatar-512.png');});
document.getElementById('copy-project-token').onclick=async()=>{try{await navigator.clipboard.writeText(brand.token.address);status.textContent='FLYFAM CONTRACT COPIED.';}catch{status.textContent='Copy unavailable. Select the address instead.';}};
