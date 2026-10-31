const test=require('node:test'),assert=require('node:assert/strict');
const tools=require('../../static/js/main/planning_parcel_tools.js');
const feature=(coordinates,area)=>({type:'Feature',geometry:{type:'Polygon',coordinates},properties:{area}});
const outer=[[106,11],[106.001,11],[106.001,11.001],[106,11.001],[106,11]];
test('parcel metrics retain actual edges, holes and the recorded parcel area',()=>{
 const m=tools.metrics(feature([outer],100));
 assert.equal(m.edges.length,4);assert.equal(m.area,100);assert.equal(m.areaSource,'recorded');
 assert(m.edges.every(x=>x.distance>100&&x.distance<112));
 assert(tools.contains(m.center,[outer]));assert.equal(m.outline.length,4);
 assert(Math.abs(m.center.lat-11.0005)<1e-9);assert(Math.abs(m.center.lng-106.0005)<1e-9);
 const hole=[[106.0004,11.0004],[106.0006,11.0004],[106.0006,11.0006],[106.0004,11.0006],[106.0004,11.0004]];
 const withHole=tools.metrics(feature([outer,hole]));
 assert(withHole.area<m.computedArea);assert.equal(withHole.areaSource,'geometry');
 assert(tools.contains(withHole.center,[outer,hole]),'Pin cannot be inside the hole');
});
test('multipart and concave parcels put their pin inside a real polygon',()=>{
 const concave=[[106,11],[106.003,11],[106.003,11.001],[106.001,11.001],[106.001,11.003],[106,11.003],[106,11]];
 const m=tools.metrics(feature([concave]));assert(tools.contains(m.center,[concave]));
 const parts={type:'Feature',properties:{},geometry:{type:'MultiPolygon',coordinates:[[outer],[concave.map(([x,y])=>[x+.01,y])]]}};
 const multi=tools.metrics(parts);assert(multi.area>m.area);assert.equal(multi.edges.length,10);
 assert(parts.geometry.coordinates.some(p=>tools.contains(multi.center,p)));
 assert.equal(tools.metrics(feature([[[NaN,11],[106,11],[106,12],[NaN,11]]])),null);
 assert.equal(tools.metrics(feature([])),null);
});
