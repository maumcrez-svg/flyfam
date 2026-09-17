import * as THREE from './vendor/three.module.js';
import {celebration} from './fly-emotes.js';

// Authored mascot performance. These poses are never measured neural/motor data.
const X=new THREE.Vector3(1,0,0),Y=new THREE.Vector3(0,1,0),Z=new THREE.Vector3(0,0,1);
const clamp=THREE.MathUtils.clamp;
const ease=x=>{x=clamp(x,0,1);return x*x*(3-2*x);};
const beat=(t,start,rise,fall)=>t<start?0:t<start+rise?ease((t-start)/rise):1-ease((t-start-rise)/fall);
const POSES={
 neutral:{},sniffing:{},focused:{focus:1},picked:{focus:1},
 holding:{focus:.35,energy:.3},position:{focus:.35,energy:.3},
 drawdown:{focus:.6,droop:.45,tilt:-.08},
 confused:{tilt:.23,focus:-.2},closed:{droop:.2},
 reward:{proud:1,energy:.6},punishment:{droop:1,tilt:-.15},
 dance:{dance:1,energy:.8},smoking:{focus:-.1,tilt:-.08},
};

// Exact critically damped response: time based, without overshoot or frame-rate
// dependent interpolation. State changes retain velocity instead of snapping.
class Spring {
 constructor(){this.value=0;this.velocity=0;}
 step(target,dt,speed,snap){
  if(snap){this.value=target;this.velocity=0;return target;}
  const delta=this.value-target,c=this.velocity+speed*delta,e=Math.exp(-speed*dt);
  this.value=target+(delta+c*dt)*e;this.velocity=(this.velocity-speed*c*dt)*e;
  return this.value;
 }
}

export function createMotion(pivot,bones,rest){
 pivot.updateMatrixWorld(true);
 const springs=new Map(),legs=[];
 let time=0,eventTime=0,state='sniffing',lastTargets={},maxContactError=0,reachClamps=0;
 const smooth=(key,target,dt,speed=10,snap=false)=>{
  if(!springs.has(key))springs.set(key,new Spring());
  return springs.get(key).step(target,dt,speed,snap);
 };
 const worldPosition=b=>b.getWorldPosition(new THREE.Vector3());
 for(const names of [
  ['FrontLeg_Upper_L','FrontLeg_Lower_L','FrontLeg_Foot_L','FrontLeg_Toe_L'],
  ['FrontLeg_Upper_R','FrontLeg_Lower_R','FrontLeg_Foot_R','FrontLeg_Toe_R'],
  ['Bone_009','Bone_008','Bone_007','Bone_006'],
  ['Bone_013','Bone_012','Bone_011','Bone_010'],
 ]){
  const [hip,knee,ankle,toe]=names.map(n=>bones.get(n));
  if(!hip||!knee||!ankle||!toe)throw new Error('Incomplete support chain');
  const h=worldPosition(hip),k=worldPosition(knee),a=worldPosition(ankle),direction=a.clone().sub(h).normalize();
  const pole=k.clone().sub(h).addScaledVector(direction,-k.clone().sub(h).dot(direction)).normalize();
  legs.push({hip,knee,ankle,toe,anchor:a,tip:worldPosition(toe),pole,
   lengthA:h.distanceTo(k),lengthB:k.distanceTo(a),orientation:ankle.getWorldQuaternion(new THREE.Quaternion())});
 }
 // Rotate in chamber axes; the imported bones have different local bases.
 function turn(name,axis,angle){
  if(!angle)return;const b=bones.get(name);if(!b)return;
  const parent=b.parent.getWorldQuaternion(new THREE.Quaternion());
  const localAxis=axis.clone().applyQuaternion(parent.invert());
  b.quaternion.premultiply(new THREE.Quaternion().setFromAxisAngle(localAxis,angle));b.updateWorldMatrix(false,true);
 }
 function aim(b,child,target){
  const origin=worldPosition(b),from=worldPosition(child).sub(origin).normalize(),to=target.clone().sub(origin).normalize();
  const rotation=new THREE.Quaternion().setFromUnitVectors(from,to);
  const orientation=b.getWorldQuaternion(new THREE.Quaternion()).premultiply(rotation);
  b.quaternion.copy(b.parent.getWorldQuaternion(new THREE.Quaternion()).invert().multiply(orientation));b.updateWorldMatrix(false,true);
 }
 function plant(leg){
  const h=worldPosition(leg.hip),delta=leg.anchor.clone().sub(h),raw=delta.length();
  const distance=clamp(raw,Math.abs(leg.lengthA-leg.lengthB)+1e-7,leg.lengthA+leg.lengthB-1e-7);
  if(Math.abs(distance-raw)>1e-6)reachClamps++;
  const direction=delta.normalize(),along=(leg.lengthA**2-leg.lengthB**2+distance**2)/(2*distance);
  const height=Math.sqrt(Math.max(0,leg.lengthA**2-along**2));
  const bend=leg.pole.clone().addScaledVector(direction,-leg.pole.dot(direction)).normalize();
  const knee=h.clone().addScaledVector(direction,along).addScaledVector(bend,height);
  aim(leg.hip,leg.knee,knee);aim(leg.knee,leg.ankle,leg.anchor);
  leg.ankle.quaternion.copy(leg.ankle.parent.getWorldQuaternion(new THREE.Quaternion()).invert().multiply(leg.orientation));
  leg.ankle.updateWorldMatrix(false,true);
  maxContactError=Math.max(maxContactError,worldPosition(leg.toe).distanceTo(leg.tip));
 }
 function reset(){
  for(const [name,b]of bones)b.quaternion.copy(rest.get(name));
  pivot.position.set(0,0,0);pivot.rotation.set(0,0,0);pivot.updateMatrixWorld(true);
 }
 function update(dt,{pose='sniffing',gaze=0,moving=true,debug=null}={}){
  dt=clamp(dt,0,.1);
  if(pose!==state){state=pose;eventTime=0;}
  if(moving){time+=dt;eventTime+=dt;}
  reset();maxContactError=0;reachClamps=0;
  if(debug){const b=bones.get(debug.name);if(b)b.quaternion.multiply(new THREE.Quaternion().setFromAxisAngle(debug.axis,debug.angle));pivot.updateMatrixWorld(true);return;}
  const p=POSES[pose]||{},t=time,snap=!moving;
  const cycle=t%5.4;
  // Dwell, glance, settle. The pauses make attention legible; no random twitch.
  const look=cycle<1.3?-.8:cycle<2.6?.72:cycle<4.1?-.35:.46;
  const hunt=pose==='sniffing'||pose==='neutral'||pose==='confused';
  const attention=clamp(gaze*.48+(hunt&&moving?look*.75:0),-1,1);
  const focus=p.focus||0,droop=p.droop||0,proud=p.proud||0,dance=p.dance||0;
  // A deliberately ridiculous mascot dance. The abdomen moves independently
  // of the chest; all four supporting feet still solve to the same anchors.
  const dancePhase=t*Math.PI*110/60;
  const groove=moving?Math.sin(dancePhase):0;
  const bounce=moving?Math.cos(dancePhase*2):0;
  const shift=moving?(ease((t%4.8-.35)/.55)-ease((t%4.8-2.7)/.55))*2-1:0;
  const breathing=moving?Math.sin(t*(2.1+(p.energy||0)*.5))*.004:0;
  const pick=moving&&(pose==='picked'||pose==='focused')?beat(eventTime,.035,.10,.30):0;
  const gather=moving&&pose==='reward'?beat(eventTime,0,.08,.15):0;
  const release=moving&&pose==='reward'?beat(eventTime,.075,.18,.55):0;
  const settle=moving&&pose==='punishment'?beat(eventTime,.025,.13,.45):0;
  const joy=moving&&pose==='reward'?celebration(eventTime):{envelope:0,laugh:0,shoulders:0};
  const target={
   x:shift*.018*(1-dance)+attention*.008+dance*groove*.016,
   y:-.064+breathing-droop*.009-gather*.012+release*.010-dance*.024+dance*bounce*.006-joy.laugh*.004,
   z:focus*.006,
   roll:-shift*.035*(1-dance)+(p.tilt||0)*.15-dance*groove*.035,
   pitch:focus*.018+droop*.018,
   yaw:attention*.070+dance*groove*.035,
   headYaw:attention*.55-dance*groove*.14,
   headPitch:focus*.14+droop*.22-proud*.075+pick*.10+settle*.045-release*.07+dance*(.035+bounce*.055)-joy.envelope*.16+joy.laugh*.085,
   headRoll:(p.tilt||0)+shift*.026*(1-dance)-proud*.04-dance*groove*.095+joy.shoulders*.035,
   arms:focus*.10+proud*.17+release*.50-droop*.065+pick*.18+dance*.31+joy.envelope*.14+joy.laugh*.09,
   hipRoll:dance*groove*.20,
   hipYaw:dance*(moving?Math.sin(dancePhase+.7):0)*.24,
   hipPitch:dance*bounce*.075,
   chestRoll:-dance*groove*.07+joy.shoulders*.055,
   chestPitch:-joy.envelope*.055+joy.laugh*.055,
   laughter:joy.laugh,
   armSwing:dance*groove*.15+joy.shoulders*.045,
  };
  const q={};for(const [key,value]of Object.entries(target))q[key]=smooth(key,value,dt,key.startsWith('head')?34:key==='arms'?26:18,snap);
  lastTargets=q;
  pivot.position.set(q.x,q.y,q.z);pivot.rotation.set(q.pitch,q.yaw,q.roll);pivot.updateMatrixWorld(true);
  turn('Bone_003',Z,q.hipRoll);turn('Bone_002',Y,q.hipYaw);turn('Bone_002',X,q.hipPitch);
  turn('Bone_004',Z,q.chestRoll);turn('Bone_004',X,q.chestPitch);
  turn('Bone_015',Y,q.headYaw);turn('Bone_015',X,q.headPitch);turn('Bone_015',Z,q.headRoll);
  // Short, distinct gestures with a clear stop; the torso follows the head.
  const finger=moving?beat(t%3.8,.65,.11,.34)*.16:0;
  turn('Bone_023',Z,-q.arms+q.armSwing);turn('Bone_019',Z,q.arms+q.armSwing);
  turn('Bone_022',X,finger+q.arms*.25+q.armSwing);turn('Bone_018',X,-finger*.55+q.arms*.22-q.armSwing);
  const sample=moving&&hunt?beat(t%2.6,.25,.09,.27):0;
  const follow=springs.get('headYaw')?.velocity||0;
  // Quiet independent antenna motion under every pose, including reactions.
  const feelerL=moving?Math.sin(t*1.85)*.035:0;
  const feelerR=moving?Math.sin(t*1.7+.9)*.030:0;
  turn('Bone_032',Z,smooth('antennaL',feelerL+sample*.13-follow*.012,dt,25,snap));
  turn('Bone_037',Z,smooth('antennaR',feelerR-sample*.10-follow*.010,dt,21,snap));
  turn('Bone_023',X,-sample*.12);turn('Bone_019',X,-sample*.075);
  turn('Bone_031',X,sample*.06);turn('Bone_036',X,sample*.04);
  // Continuous small wing beats. Shared time keeps phase through pose changes;
  // reduced motion and paused views retain the resting wings and antennae.
  const wing=moving?(1-Math.cos(t*Math.PI*2*2.2))*.035*(.9+Math.sin(t*.8)*.1)+release*.025:0;
  turn('Bone_025',Y,-wing);turn('Bone_027',Y,wing*.92);
  turn('Bone_025',Z,-wing*.45);turn('Bone_027',Z,wing*.42);
  for(const leg of legs)plant(leg);
  pivot.updateMatrixWorld(true);
 }
 return {update,reset,get time(){return time;},restart(){eventTime=0;},diagnostics(){return {time,eventTime,state,channels:{...lastTargets},maxContactError,reachClamps,
  feet:legs.map(l=>({name:l.toe.name,anchor:l.tip.toArray(),position:worldPosition(l.toe).toArray()}))};}};
}
