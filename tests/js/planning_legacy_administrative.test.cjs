const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
const api=require('../../static/js/main/planning_administrative.js');
const overlay=require('../../static/js/main/planning_overlay.js');
const area=require('../../static/js/main/planning_area.js');

test('old boundaries are a separate 63-province, commune-level snapshot',()=>{
 const catalog=require('../../config/planning_administrative_legacy.json');
 const provinces=require('../../config/planning_landuse_areas.json').provinces;
 assert.equal(catalog.layers.length,63);
 assert.equal(catalog.layers.reduce((n,x)=>n+x.manifest.unit_count,0),10038);
 assert(overlay.validCatalog(catalog));
 for(const province of provinces){
  const matches=catalog.layers.filter(x=>area.coversProvince(x,province));assert.equal(matches.length,1,province.id);
  const item=matches[0];assert.equal(item.theme,'administrative_legacy');
  assert(!overlay.validCatalog({layers:[{...item,theme:'administrative'}]}),'Old and new boundaries cannot be relabelled as one another');
  const file=item.manifest.geojson_url.split('?')[0].slice(1),data=JSON.parse(fs.readFileSync(file,'utf8'));
  assert(api.valid(data,item.id),item.id);
  for(const feature of data.features){
   assert(feature.properties.district&&feature.properties.former_province);
   assert(api.validFeature(JSON.parse(fs.readFileSync(file.replace('overview.json',feature.properties.code+'.json'),'utf8')),feature.properties,item.id));
  }
 }
});

test('both boundary buttons have explicit old/new labels and links accept the legacy theme',()=>{
 const source=fs.readFileSync('static/js/main/planning_overlay.js','utf8');
 assert(source.includes("short: 'Địa giới (mới)'"));assert(source.includes("short: 'Địa giới (cũ)'"));
 const sourceMap=fs.readFileSync('static/js/main/listing_map.js','utf8');
 const vm=require('node:vm'),ctx={};vm.createContext(ctx);
 const start=sourceMap.indexOf('  function defaultBaseLayer(');
 vm.runInContext(sourceMap.slice(start,sourceMap.indexOf('\n  function ',start+1)),ctx);
 assert.equal(ctx.defaultBaseLayer('administrative_legacy'),'street');
});
