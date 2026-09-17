// Authored performance/audio timing, unrelated to trading or neural telemetry.
export const LAUGH_BEATS=[.58,.86,1.14,1.43,1.74];
const ease=x=>{x=Math.max(0,Math.min(1,x));return x*x*(3-2*x);};
const beat=(t,start,rise,fall)=>t<start?0:t<start+rise?ease((t-start)/rise):1-ease((t-start-rise)/fall);
export function celebration(t){
 const envelope=ease((t-.44)/.16)*(1-ease((t-1.94)/.28));
 let laugh=0,shoulders=0;
 for(let i=0;i<LAUGH_BEATS.length;i++){const pulse=beat(t,LAUGH_BEATS[i],.045,.15);laugh+=pulse;shoulders+=pulse*(i%2?1:-1);}
 return {envelope,laugh,shoulders};
}
let voices=new Set(),rewardPlays=0;
export function stopEmoteAudio(){for(const node of voices){try{node.stop();}catch{}}voices.clear();}
export function playRewardLaugh(ctx){
 // Five breathy, pitched "ha" syllables. Synthesized locally, no recordings,
 // voice service, runtime AI calls or additional audio downloads.
 stopEmoteAudio();rewardPlays++;const start=ctx.currentTime;
 const remember=(node,cleanup=[])=>{voices.add(node);node.onended=()=>{voices.delete(node);node.disconnect();for(const n of cleanup)n.disconnect();};};
 LAUGH_BEATS.forEach((at,i)=>{
  const t=start+at,duration=i===4?.25:.20,o=ctx.createOscillator(),volume=ctx.createGain(),cleanup=[volume];
  o.type='sawtooth';o.frequency.setValueAtTime([390,440,370,350,310][i],t);o.frequency.exponentialRampToValueAtTime([290,310,270,260,220][i],t+duration);
  volume.gain.setValueAtTime(0,t);volume.gain.linearRampToValueAtTime(.105,t+.026);volume.gain.exponentialRampToValueAtTime(.001,t+duration);volume.connect(ctx.destination);
  for(const [hz,q,gain]of [[820,1.5,.8],[1550,2.5,.42],[2800,3,.12]]){const formant=ctx.createBiquadFilter(),mix=ctx.createGain();formant.type='bandpass';formant.frequency.value=hz;formant.Q.value=q;mix.gain.value=gain;o.connect(formant).connect(mix).connect(volume);cleanup.push(formant,mix);}
  const breath=ctx.createBuffer(1,Math.ceil(ctx.sampleRate*.075),ctx.sampleRate),samples=breath.getChannelData(0);let seed=7109+i;
  for(let k=0;k<samples.length;k++){seed=(seed*1664525+1013904223)>>>0;samples[k]=(seed/2147483648-1)*.016*(1-k/samples.length);}
  const air=ctx.createBufferSource(),filter=ctx.createBiquadFilter();air.buffer=breath;filter.type='highpass';filter.frequency.value=1700;air.connect(filter).connect(ctx.destination);remember(air,[filter]);air.start(t-.012);
  remember(o,cleanup);o.start(t);o.stop(t+duration+.02);
 });
}
export function emoteAudioStatus(){return {activeSources:voices.size,rewardPlays};}
