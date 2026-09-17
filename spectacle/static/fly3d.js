import * as THREE from './vendor/three.module.js';
import {GLTFLoader} from './vendor/GLTFLoader.js';
import {createMotion} from './fly-motion.js';
import {createFlyProps} from './fly-props.js';

// Character choreography only. No measured motor/neuron activity is inferred.
const X=new THREE.Vector3(1,0,0),Y=new THREE.Vector3(0,1,0),Z=new THREE.Vector3(0,0,1);
export function createFly(host,{url='/assets/the-fly.glb',poster,onReady=()=>{},onUnavailable=()=>{}}={}){
 let renderer;
 try{renderer=new THREE.WebGLRenderer({alpha:true,antialias:true,powerPreference:'low-power',preserveDrawingBuffer:true});}
 catch(error){host.dataset.state='unavailable';onUnavailable();return {ready:Promise.resolve(false),setState(){},setGaze(){},capture(){return poster;},diagnostics(){return {ready:false,error:String(error)}}};}
 renderer.setPixelRatio(Math.min(devicePixelRatio,1.5));renderer.setClearColor(0x000000,0);renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.35;host.append(renderer.domElement);renderer.domElement.setAttribute('aria-label','The Fly 3D mascot. Character animation, not measured motor activity.');renderer.domElement.setAttribute('role','img');
 const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(32,1,.05,30),pivot=new THREE.Group();scene.add(pivot);camera.position.set(2.2,1.4,5.1);camera.lookAt(0,.86,0);
 scene.add(new THREE.HemisphereLight(0xdfe9ec,0x292820,3.0));
 const light=(color,intensity,x,y,z)=>{const l=new THREE.DirectionalLight(color,intensity);l.position.set(x,y,z);scene.add(l);};
 light(0xffedd8,1.5,3,4,5);light(0xe1edff,.8,-4,2,2);light(0xc0e57c,1.2,-2,3,-3);
 // A small local reflection environment keeps the glossy eyes readable without
 // an external HDR fetch. It is lighting, not neural visualization.
 const makeEnvironment=()=>{const room=new THREE.Scene();room.background=new THREE.Color(0x5a6559);const addPanel=(x,y,z,w,h,color,intensity)=>{const mesh=new THREE.Mesh(new THREE.PlaneGeometry(w,h),new THREE.MeshBasicMaterial({color:new THREE.Color(color).multiplyScalar(intensity),side:THREE.DoubleSide}));mesh.position.set(x,y,z);mesh.lookAt(0,0,0);room.add(mesh);};addPanel(-3,2,3,2,3,0xffffff,4);addPanel(3,3,2,3,2,0xffedd5,4);addPanel(0,4,-2,4,2,0xcad5bd,2);
 const pmrem=new THREE.PMREMGenerator(renderer);const environment=pmrem.fromScene(room,0);scene.environment?.dispose();scene.environment=environment.texture;room.traverse(o=>{o.geometry?.dispose();o.material?.dispose()});pmrem.dispose();};makeEnvironment();
 const reduced=matchMedia('(prefers-reduced-motion: reduce)');const bones=new Map(),rest=new Map();let model,motion,props,previousReduced=reduced.matches,pose='sniffing',gaze=0,active=true,visible=true,loaded=false,lastFrame=0,debug=null,frames=0,dirty=true,initializing=null,contextGeneration=0,contextLosses=0;
 const size=()=>{dirty=true;const rect=host.getBoundingClientRect();if(!rect.width||!rect.height)return;renderer.setSize(rect.width,rect.height,false);camera.aspect=rect.width/rect.height;camera.zoom=rect.height<280?1.35:1;camera.updateProjectionMatrix();if(loaded)renderer.render(scene,camera);};const resize=new ResizeObserver(size);resize.observe(host);
 const intersection=new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;dirty=true;});intersection.observe(host);
 function animate(now){
  requestAnimationFrame(animate);
  if(!loaded||document.hidden||!visible){lastFrame=now;return;}
  if(now-lastFrame<1000/30)return;
  const dt=Math.min(.1,(now-lastFrame)/1000);lastFrame=now;
  const reduceNow=reduced.matches;if(reduceNow!==previousReduced){dirty=true;previousReduced=reduceNow;}
  const moving=active&&!reduceNow;if(!moving&&!dirty)return;dirty=false;
  motion.update(dt,{pose,gaze,moving,debug});props.update(debug?null:pose,motion.time,moving);renderer.render(scene,camera);frames++;
 }
 reduced.addEventListener('change',()=>{dirty=true;});
 requestAnimationFrame(animate);
 const unavailable=error=>{loaded=false;host.dataset.state='unavailable';host.dataset.error=String(error);renderer.domElement.hidden=true;onUnavailable();};
 // A browser may restart its GPU context during startup. Keep the poster visible
 // until a real mesh draw, and rebuild the generated lighting after restoration.
 renderer.domElement.addEventListener('webglcontextlost',event=>{event.preventDefault();contextGeneration++;contextLosses++;unavailable('Graphics context interrupted');});
 renderer.domElement.addEventListener('webglcontextrestored',()=>{makeEnvironment();dirty=true;if(model&&!initializing)initialize().catch(unavailable);});
 function initialize(){
  if(initializing)return initializing;
  initializing=(async()=>{
   const deadline=performance.now()+15000;let compiledGeneration=-1;
   let triangles=0;model.traverseVisible(o=>{if(o.isMesh)triangles+=(o.geometry.index?.count||o.geometry.attributes.position.count)/3;});
   while(performance.now()<deadline){
    if(renderer.getContext().isContextLost()){await new Promise(resolve=>setTimeout(resolve,50));continue;}
    if(compiledGeneration!==contextGeneration){const generation=contextGeneration;await renderer.compileAsync(scene,camera);if(generation!==contextGeneration)continue;compiledGeneration=generation;}
    size();renderer.render(scene,camera);
    if(!renderer.getContext().isContextLost()&&renderer.info.render.triangles>=triangles){loaded=true;dirty=true;renderer.domElement.hidden=false;host.dataset.state='ready';delete host.dataset.error;onReady();return true;}
    await new Promise(resolve=>setTimeout(resolve,50));
   }
   throw new Error('Character render did not initialize');
  })().finally(()=>{initializing=null;});
  return initializing;
 }
 const ready=new GLTFLoader().loadAsync(url).then(async gltf=>{
  model=gltf.scene;model.traverse(o=>{if(o.isBone){bones.set(o.name,o);rest.set(o.name,o.quaternion.clone());}if(o.isMesh){o.frustumCulled=false;o.material.envMapIntensity=1.25;}});pivot.add(model);model.updateMatrixWorld(true);
  for(const name of ['FrontLeg_Upper_L','FrontLeg_Lower_L','FrontLeg_Upper_R','FrontLeg_Lower_R'])if(!bones.has(name))throw new Error(`Required repaired bone missing: ${name}`);
  motion=createMotion(pivot,bones,rest);props=createFlyProps(pivot,bones);
  return initialize();
 }).catch(error=>{unavailable(error);console.error('Fly model unavailable',error);return false;});
 return {ready,setState(next,{fresh=true,restart=false}={}){if(restart&&pose===next){motion?.restart();dirty=true;}if(pose!==next){pose=next;dirty=true;}if(active!==fresh)dirty=true;active=fresh;},setGaze(rank){const next=THREE.MathUtils.clamp(rank,-1,1);if(next!==gaze)dirty=true;gaze=next;},capture(){if(!loaded)return poster;const oldSize=renderer.getSize(new THREE.Vector2()),aspect=camera.aspect,zoom=camera.zoom;renderer.setSize(640,640,false);camera.aspect=1;camera.zoom=1;camera.updateProjectionMatrix();renderer.render(scene,camera);const canvas=document.createElement('canvas');canvas.width=canvas.height=640;canvas.getContext('2d').drawImage(renderer.domElement,0,0,640,640);renderer.setSize(oldSize.x,oldSize.y,false);camera.aspect=aspect;camera.zoom=zoom;camera.updateProjectionMatrix();renderer.render(scene,camera);return canvas;},snapshot(){if(!loaded)return null;renderer.render(scene,camera);return renderer.domElement.toDataURL('image/png');},setDebugPose(name,angle=.35,axis='x'){dirty=true;debug=name?{name,angle,axis:axis==='z'?Z:axis==='y'?Y:X}:null;},setCamera(position,target){dirty=true;camera.position.fromArray(position);camera.lookAt(...target);},diagnostics(){return {ready:loaded,contextLosses,bones:[...bones.keys()],frames,drawCalls:renderer.info.render.calls,triangles:renderer.info.render.triangles,geometries:renderer.info.memory.geometries,textures:renderer.info.memory.textures,pose,motion:motion?.diagnostics(),props:props?.diagnostics(),reducedMotion:reduced.matches,cameraPosition:camera.position.toArray(),cameraQuaternion:camera.quaternion.toArray(),cameraAspect:camera.aspect,modelChildren:model?.children.map(x=>({name:x.name,visible:x.visible,position:x.position.toArray()})),canvas:[renderer.domElement.width,renderer.domElement.height]};}};
}
