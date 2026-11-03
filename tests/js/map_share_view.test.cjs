const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const api=require('../../static/js/main/listing_map.js');
const source=fs.readFileSync('static/js/main/listing_map.js','utf8');
function fn(name){const a=source.indexOf('  function '+name+'(');return source.slice(a,source.indexOf('\n  function ',a+1));}

test('share URL restores a bounded view and rejects malformed coordinates',()=>{
 const href='https://radarbds.vn/?map=1#map=11.536,106.893,20&base=satellite&province=binh-phuoc&district=689&planning=partition&listings=0';
 assert.deepEqual(api.sharedMapView(href),{center:[11.536,106.893],zoom:20,base:'satellite',province:'binh-phuoc',district:'689',theme:'partition',listings:false});
 for(const value of ['NaN,106,18','91,106,18','11,181,18','11,106,24','11,,18','11,106'])assert.equal(api.sharedMapView('https://radarbds.vn/#map='+value),null);
 assert.equal(api.sharedMapView('https://radarbds.vn/#map=0,0,0').zoom,0);
 assert.equal(new URL(api.urlWithoutMapFlag(href)).hash,'');
});

test('moving Maps replaces the URL without new history entries and retains modal state',()=>{
 let url,entry;const ctx={URL,URLSearchParams,
 state:{open:true,snapshot:{mode:'all',query:'price_max=3'},map:{getCenter:()=>({lat:11.536,lng:106.893}),getZoom:()=>20},activeBaseLayer:'satellite',planningTheme:'partition',initialPlanningArea:{province:'binh-phuoc',district:'689'},listingsVisible:false},
 root:{location:{href:'https://radarbds.vn/?city=old'},history:{state:{signalModal:true},replaceState(s,_,u){entry=s;url=u;}}},
 buildMapShareUrl:api.buildMapShareUrl,sharedMapHistoryState:api.sharedMapHistoryState};
 vm.createContext(ctx);vm.runInContext(fn('syncMapUrl'),ctx);ctx.syncMapUrl();
 assert.equal(new URL(url).searchParams.get('map'),'1');assert.equal(new URL(url).searchParams.get('price_max'),'3');
 assert.equal(api.sharedMapView(url).province,'binh-phuoc');assert.equal(entry.signalModal,true);assert.equal(entry.radarListingMap,true);
 ctx.root.location.href=url;entry=null;ctx.syncMapUrl();
 assert.equal(entry,null,'Settled duplicate events must not rewrite an identical URL');
});

test('opening a shared non-Binh-Duong view restores its area, explicit visibility and default street',async()=>{
 const el={hidden:true,classList:{add(){},toggle(){}},setAttribute(){},focus(){}};
 const ctx={URLSearchParams,DIRECTORY_BATCH_SIZE:100,state:{open:false},VALID_PLANNING_THEMES:['partition'],
 normalizedSnapshot:x=>x,sharedMapView:api.sharedMapView,buildMapShareUrl:api.buildMapShareUrl,
 sharedMapHistoryState:api.sharedMapHistoryState,defaultBaseLayer:()=> 'street',element:()=>el,captureDashboardState(){},setMobileSheetExpanded(){},setFocusMode(){},syncAdminEditModeToggle(){},filterSummaryText:()=>'',emitTrack(){},startMapLoad:async()=>{},
 root:{document:{body:el},RADAR_LANDUSE_AREAS:[{id:'binh-phuoc',region_id:'binh-phuoc-legacy',bounds:[[11,106],[12,107]],districts:[{id:'689',bounds:[[11.5,106.8],[11.6,107]]}]}],location:{href:'https://radarbds.vn/?map=1#map=11.536,106.893,20&province=binh-phuoc&district=689&listings=0'},history:{state:{},replaceState(){}}}};
 vm.createContext(ctx);vm.runInContext(fn('open'),ctx);await ctx.open({mode:'all',query:''},{initialSharedOpen:true,locateArea:true,planningTheme:'partition'});
 assert.equal(ctx.state.locateOnOpen,false,'A shared view must never be replaced by geolocation');
 assert.equal(ctx.state.initialPlanningArea.province,'binh-phuoc');assert.equal(ctx.state.initialPlanningArea.district,'689');assert.equal(ctx.state.listingsVisible,false);assert.equal(ctx.state.sharedView.base,'street');
});

test('satellite overzooms available level 18 while street retains level 19',()=>{
 const layers=api.mapBaseLayers();assert.equal(layers.satellite.maxNativeZoom,18);assert.equal(layers.satellite.maxZoom,23);assert.equal(layers.street.maxNativeZoom,19);
});

test('selecting an unsupported listing province hides listings but never forces them on',()=>{
 const body=source.match(/onAreaChange: function \(area\) \{([\s\S]*?)\n        \},/)[1];
 const calls=[],ctx={state:{},setListingsVisible:v=>calls.push(v),syncMapUrl(){},setLocationButtonLoading(){}};
 vm.createContext(ctx);const change=vm.runInContext('(function(area){'+body+'})',ctx);
 change({province:'binh-phuoc'});assert.deepEqual(calls,[false]);
 change({province:'binh-duong'});assert.deepEqual(calls,[false]);assert.equal(ctx.state.initialPlanningArea.province,'binh-duong');
});
