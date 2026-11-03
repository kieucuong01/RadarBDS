const test=require('node:test'),assert=require('node:assert/strict');
const api=require('../../static/js/main/planning_overlay.js');
const marks=require('../../static/js/main/planning_reference_branding.js');
test('reference labels require true viewport intersection, crop SVG size, retain opacity and clean listeners',()=>{
 const key='test-visible-label';marks[key]=[[[1000,1500],[1500,1000],[2000,1500],[1500,2000]]];
 let viewport={min:{x:1000,y:1000},max:{x:1100,y:1100}};
 const handlers=new Map(),attached=new Set(),created=[];
 const map={getPixelBounds:()=>viewport,getZoom:()=>11,on:(k,f)=>handlers.set(k,f),off:(k,f)=>{assert.equal(handlers.get(k),f);handlers.delete(k);},removeLayer:l=>attached.delete(l)};
 const events={},layer={options:{opacity:.5,pane:'planningPilot'},on:(k,f)=>events[k]=f,setOpacity(v){this.options.opacity=v;return this;}};
 const L={imageOverlay(url,bounds,options){const label={url,bounds,options,addTo(){attached.add(this);},setOpacity(v){this.options.opacity=v;}};created.push(label);return label;}};
 try{
  api.referenceBranding(layer,map,L,key);assert.equal(created.length,0,'Labels are lazy until the source is added');
  events.add();assert.equal(created.length,0,'A diagonal footprint bbox is insufficient');
  viewport={min:{x:1450,y:1450},max:{x:1550,y:1550}};handlers.get('moveend')();
  assert.equal(attached.size,1);assert.match(decodeURIComponent(created[0].url),/viewBox="322 322 356 356"/);
  assert.match(decodeURIComponent(created[0].url),/matrix\(/,'Original geographic rotation is retained');
  layer.setOpacity(.3);assert.equal(created[0].options.opacity,.3);
  viewport={min:{x:3000,y:3000},max:{x:3100,y:3100}};handlers.get('moveend')();assert.equal(attached.size,0);
  viewport={min:{x:1450,y:1450},max:{x:1550,y:1550}};handlers.get('moveend')();assert.equal(created.at(-1).options.opacity,.3);
  events.remove();assert.equal(attached.size,0);assert.equal(handlers.size,0);
  events.add();assert.equal(attached.size,1);events.remove();assert.equal(handlers.size,0);
 }finally{delete marks[key];}
});
