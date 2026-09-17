import * as THREE from './vendor/three.module.js';
// Optional studio prop. It is not part of the mascot's permanent GLB or telemetry.
export function createFlyProps(pivot,bones){
 const cigarette=new THREE.Group();cigarette.name='Preview cigarette';
 const segment=(radius,length,color,y,emissive=0)=>{const mesh=new THREE.Mesh(new THREE.CylinderGeometry(radius,radius,length,10),new THREE.MeshStandardMaterial({color,roughness:.8,emissive,emissiveIntensity:.25}));mesh.position.y=y;cigarette.add(mesh);return mesh;};
 segment(.009,.024,0xb58b59,.010);segment(.009,.092,0xe4dfce,.068);const ember=segment(.0088,.005,0x70584b,.116,0xbc4415);
 // Seat the filter at the mouth corner, in the neck's local frame so it follows the head.
 cigarette.position.set(.055,.105,.335);cigarette.rotation.set(Math.PI/2+.12,0,.16);bones.get('Bone_015').add(cigarette);cigarette.visible=false;
 const geometry=new THREE.BufferGeometry(),positions=new Float32Array(14*3);geometry.setAttribute('position',new THREE.BufferAttribute(positions,3));
 const material=new THREE.LineBasicMaterial({color:0xaaa99d,transparent:true,opacity:.22,depthWrite:false}),wisp=new THREE.Line(geometry,material);wisp.frustumCulled=false;wisp.visible=false;pivot.add(wisp);
 const tip=new THREE.Vector3();
 return {update(pose,time,moving){const smoking=pose==='smoking';cigarette.visible=smoking;wisp.visible=smoking&&moving;if(!smoking)return;
  const puff=moving?Math.pow(Math.max(0,Math.sin(time*1.7)),5):0;ember.material.emissiveIntensity=.25+puff*.9;
  cigarette.updateWorldMatrix(true,true);ember.getWorldPosition(tip);pivot.worldToLocal(tip);
  for(let i=0;i<14;i++){const u=i/13;positions[i*3]=tip.x+Math.sin(u*7-time*1.8)*u*.023;positions[i*3+1]=tip.y+u*.20;positions[i*3+2]=tip.z+u*.035;}
  material.opacity=.12+puff*.19;geometry.attributes.position.needsUpdate=true;
 },diagnostics(){return {cigaretteVisible:cigarette.visible,smokeVisible:wisp.visible};}};
}
