import {brand} from './brand.js';
const images=new Map();
export function loadBrandImage(src){
 if(!images.has(src))images.set(src,new Promise((resolve,reject)=>{const i=new Image();i.onload=()=>resolve(i);i.onerror=()=>{images.delete(src);reject(Error('Brand artwork could not be loaded.'));};i.src=src;}));
 return images.get(src);
}
export function drawWordmark(ctx,x,y,size){
 ctx.save();ctx.font=`bold ${size}px Broadcast`;ctx.fillStyle='#f7f0d8';
 if(brand.displayName==='FLYFAM'){
  ctx.fillText('FLY',x,y);const offset=ctx.measureText('FLY').width;
  ctx.fillStyle=brand.inkAccent;ctx.fillText('FAM',x+offset,y);
 }else ctx.fillText(brand.displayName,x,y);
 ctx.restore();
}
export async function drawBrandCharacter(ctx,x,y,width,height){
 const art=await loadBrandImage(brand.artwork);
 // A viewport into the unchanged approved poster, excluding its lettering.
 // Original PNG stays byte-identical; this is composition in the share renderer.
 const sw=750,sh=830,scale=Math.min(width/sw,height/sh),w=sw*scale,h=sh*scale;
 ctx.drawImage(art,260,25,sw,sh,x+(width-w)/2,y+(height-h)/2,w,h);
}
export async function drawBrandBanner(canvas){
 await document.fonts.ready;
 const ctx=canvas.getContext('2d'),{width:w,height:h}=canvas;
 ctx.fillStyle='#10120e';ctx.fillRect(0,0,w,h);
 await drawBrandCharacter(ctx,w*.06,h*.04,w*.34,h*.92);
 const size=w*.089,x=w*.44;
 drawWordmark(ctx,x,h*.48,size);
 ctx.fillStyle='#f7f0d8';ctx.font=`${w*.018}px Telemetry`;
 ctx.fillText('THE FLY PICKS.',x,h*.65);
 ctx.fillStyle=brand.inkAccent;ctx.fillText('THE FAM DECIDES.',x,h*.75);
}
