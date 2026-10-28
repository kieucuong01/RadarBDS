const test=require('node:test');
const assert=require('node:assert/strict');
const hub=require('../../static/js/planning_hub.js');
const fs=require('node:fs');
const vm=require('node:vm');
const mapApi=require('../../static/js/main/listing_map.js');
test('planning entry opens the selected supported city and layer directly on Maps',()=>{
 const url=new URL(hub.mapHref('BẾN CÁT','detailed'),'https://radarbds.vn');
 assert.equal(url.origin,'https://radarbds.vn');assert.equal(url.pathname,'/');
 assert.equal(url.searchParams.get('tab'),'all');assert.equal(url.searchParams.get('map'),'1');
 assert.equal(url.searchParams.get('city'),'BẾN CÁT');assert.equal(url.searchParams.get('planning'),'detailed');
});

test('Tools opens Maps with existing filters and chosen layer, from either listing tab',async()=>{
 const source=fs.readFileSync('static/js/main/core.js','utf8');
 for(const initialTab of ['signals','all','market']){
  let tab=initialTab,captured,closed=0,switched=0;
  const menu={open:true};
  const ctx={URLSearchParams,currentFilters:'city=BẾN CÁT&ward=Mỹ Phước&date_range=7&price_max=3&area_min=90&property_type=dat_nen&page=2',
   document:{getElementById:()=>menu},activeTabId:()=>tab,closeToolsSheet:()=>closed++,
   switchTab:async value=>{tab=value;switched++;},warmListingMapAssets:async()=>{},
   window:{RadarListingMap:{open:async(snapshot,options)=>{captured={snapshot,options};}},location:{assign(){throw Error('Unexpected fallback');}}}};
  vm.createContext(ctx);
  const start=source.indexOf('function getListingMapFilterSnapshot()');
  vm.runInContext(source.slice(start,source.indexOf('window.openSignal =',start))+
   '\nwindow.openListingMap=lazyOpenListingMap;\n'+source.slice(source.indexOf('async function openPlanningMapFromTools()'),source.indexOf("document.addEventListener('click', function (event) {",source.indexOf('async function openPlanningMapFromTools()'))),ctx);
  await vm.runInContext('openPlanningMapFromTools()',ctx);
  const params=new URLSearchParams(captured.snapshot.query);
  for(const [key,value] of new URLSearchParams(ctx.currentFilters))if(key!=='page')assert.equal(params.get(key),value);
  assert.equal(params.has('page'),false);assert.equal(captured.options.planningTheme,'partition');
  assert.equal(captured.snapshot.mode,initialTab==='signals'?'signals':'all');
  assert.equal(menu.open,false);assert.equal(closed,1);assert.equal(switched,initialTab==='market'?1:0);
 }
});

test('closing a planning deep link removes presentation flags while retaining listing filters',()=>{
 const url=new URL(mapApi.urlWithoutMapFlag('https://radarbds.vn/?tab=all&map=1&planning=detailed&city=BẾN+CÁT&price_max=3'));
 assert.equal(url.searchParams.has('map'),false);assert.equal(url.searchParams.has('planning'),false);
 assert.equal(url.searchParams.get('city'),'BẾN CÁT');assert.equal(url.searchParams.get('price_max'),'3');
});
test('invalid planning choices use a supported city and partition rather than arbitrary URL input',()=>{
 const url=new URL(hub.mapHref('https://evil.invalid','district_landuse'),'https://radarbds.vn');
 assert.equal(url.searchParams.get('city'),'THỦ DẦU MỘT');assert.equal(url.searchParams.get('planning'),'partition');
 assert.equal(url.origin,'https://radarbds.vn');
});
