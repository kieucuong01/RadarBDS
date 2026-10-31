const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
const catalog=require('../../config/planning_administrative.json');
const api=require('../../static/js/main/planning_administrative.js');
const overlay=require('../../static/js/main/planning_overlay.js');
const area=require('../../static/js/main/planning_area.js');
const provinces=require('../../config/planning_landuse_areas.json').provinces;

test('34 new administrative provinces cover each former province exactly once',()=>{
 assert.equal(catalog.layers.length,34);
 assert.equal(catalog.layers.reduce((n,x)=>n+x.manifest.unit_count,0),3321);
 for(const province of provinces)assert.equal(catalog.layers.filter(x=>area.coversProvince(x,province)).length,1,province.id);
 assert(overlay.validCatalog(catalog));
});

test('national sources retain per-province geometry and manifest validation',()=>{
 for(const item of catalog.layers){
  assert(overlay.validManifest(item.manifest),item.id);
  const file=item.manifest.geojson_url.split('?')[0].slice(1);
  const data=JSON.parse(fs.readFileSync(file,'utf8'));assert(api.valid(data,item.id),item.id);
  for(const f of data.features){
   const full=JSON.parse(fs.readFileSync(file.replace('overview.json',f.properties.code+'.json'),'utf8'));
   assert(api.validFeature(full,f.properties,item.id),item.id+'/'+f.properties.code);
  }
  assert(!api.valid({...data,features:data.features.slice(1)},item.id));
  assert(!overlay.validManifest({...item.manifest,geojson_url:'/static/unknown.json'}));
  assert(!overlay.validCatalog({layers:[{...item,source_url:'https://unknown.example/'}]}));
 }
 assert(!api.valid({},'vn-99-administrative-2025'));
});
