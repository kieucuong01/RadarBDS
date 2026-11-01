const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('static/js/main/listing_map.js','utf8');
test('satellite names use only OSM above planning and below parcels',()=>{
 const pane={style:{}},L={},map={createPane(name){assert.equal(name,'satelliteLabels');return pane;}},satellite={};
 const calls=[],dispose=()=>{};
 const ctx={L,map,satellite,setStatus(){},root:{RadarSatelliteLabels:{mount(...args){calls.push(args);return dispose;}}}};
 const start=source.indexOf('  function bindSatelliteLabels(');
 vm.createContext(ctx);
 vm.runInContext(source.slice(start,source.indexOf('\n  function ',start+1))+'\nresult=bindSatelliteLabels(L,map,satellite);',ctx);
 assert.equal(ctx.result,dispose);assert.equal(calls.length,1);
 assert.equal(calls[0][0],L);assert.equal(calls[0][1],map);assert.equal(calls[0][2],satellite);
 assert.equal(pane.style.pointerEvents,'none');assert.ok(+pane.style.zIndex>400&&+pane.style.zIndex<410);
 for(const retired of ['World_Hybrid_Overlay','World_Transportation','World_Boundaries_and_Places'])assert.ok(!source.includes(retired));
});