const test=require('node:test'),assert=require('node:assert/strict');
const api=require('../../static/js/main/planning_overlay.js');
const registry=require('../../static/js/main/planning_reference_branding.js');
const layers=require('../../config/planning_landuse_2030.json').layers;

test('every registered 2030 source has a reviewed branding entry',()=>{
 for(const item of layers){
  const source=item.manifest.tile_template;
  assert(Object.hasOwn(registry,source),item.id+' was not audited');
  assert.deepEqual(api.referenceAnnotations(source),registry[source]);
 }
 assert.deepEqual(api.referenceAnnotations('https://unknown.example/{z}/{x}/{y}.png'),[]);
});

test('new province logo masks track their world position across zoom levels',()=>{
 const source=layers.find(x=>x.id==='an-giang-land-use-2030-reference').manifest.tile_template;
 const rings=api.referenceAnnotations(source);assert(rings.length>=3);
 for(const [template,marks] of Object.entries(registry))for(const ring of marks){
  assert.equal(ring.length,4);
  assert(ring.every(p=>p.length===2&&p.every(Number.isFinite)));
  for(const z of [8,11,16,23]){
   const scale=2**(z-11),p=ring.reduce((a,b)=>[a[0]+b[0]/4,a[1]+b[1]/4],[0,0]);
   const coords={z,x:Math.floor(p[0]*scale/256),y:Math.floor(p[1]*scale/256)};
   assert(api.referenceClipPath(template,coords));
  }
 }
});
