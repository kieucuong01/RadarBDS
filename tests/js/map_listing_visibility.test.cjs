const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('static/js/main/listing_map.js','utf8');
function functions(...names){return 'var sharedMapView=()=>null,buildMapShareUrl=(_,href)=>href,syncMapUrl=()=>{};\n'+names.map(name=>{
 const start=source.indexOf('  function '+name+'(');
 assert.ok(start>=0,'Missing '+name);
 return source.slice(start,source.indexOf('\n  function ',start+1));
}).join('\n');}

test('base map selector stays compact on phones and desktop',()=>{
 const calls=[];
 const ctx={state:{mediaQuery:{matches:true},baseLayerControl:{collapse(){calls.push('collapse');},expand(){calls.push('expand');}}}};
 ctx.URLSearchParams=URLSearchParams;vm.createContext(ctx);vm.runInContext(functions('syncBaseLayerControl'),ctx);
 ctx.syncBaseLayerControl();ctx.state.mediaQuery.matches=false;ctx.syncBaseLayerControl();
 ctx.state.baseLayerControl=null;ctx.syncBaseLayerControl();
 assert.deepEqual(calls,['collapse','collapse']);
});

test('fullscreen filter button opens desktop sidebar and delegates mobile sheet',()=>{
 const classes=new Set(),calls=[];
 const ctx={state:{focusMode:true,map:{invalidateSize(){calls.push('resize');}}},
  root:{innerWidth:1200,document:{body:{classList:{toggle(name){classes.has(name)?classes.delete(name):classes.add(name);}}}},
   toggleMenu(){calls.push('sheet');},setTimeout(fn){fn();}}};
 ctx.URLSearchParams=URLSearchParams;vm.createContext(ctx);vm.runInContext(functions('toggleFilters'),ctx);
 ctx.toggleFilters();assert.ok(classes.has('listing-map-filter-open'));
 ctx.toggleFilters();assert.equal(classes.size,0);
 ctx.root.innerWidth=390;ctx.toggleFilters();assert.ok(calls.includes('sheet'));
});

test('Maps defaults to land use 2030 on street while explicit planning entries retain their theme',async()=>{
 for(const theme of [null,'partition','urban_general','detailed','land_use_2030','urban_vision_100','transport','administrative','administrative_legacy','invalid']){
  let focus;
  const el={hidden:true,classList:{add(){},toggle(){}},setAttribute(){},focus(){}};
  const ctx={state:{open:false},VALID_PLANNING_THEMES:['partition','urban_general','detailed','land_use_2030','urban_vision_100','transport','administrative','administrative_legacy'],
   normalizedSnapshot:x=>x,element:()=>el,captureDashboardState(){},setMobileSheetExpanded(){},
   setFocusMode:value=>{focus=value;},syncAdminEditModeToggle(){},filterSummaryText:()=>'',emitTrack(){},defaultBaseLayer:theme=>theme==='administrative'?'street':'satellite',
   root:{document:{body:el},RADAR_PLANNING_REGIONS:[{id:'dong-nai-expanded',bounds:[[10.49,106.39],[12.33,107.6]],max_zoom:10}],history:{pushState(){}},location:{href:'https://radarbds.vn/'}},
   DIRECTORY_BATCH_SIZE:100,startMapLoad:async()=>{}};
  ctx.URLSearchParams=URLSearchParams;vm.createContext(ctx);vm.runInContext(functions('open'),ctx);
  await ctx.open({mode:'all',query:'price_max=3'},{planningTheme:theme,planningRegion:'dong-nai-expanded'});
  const planning=ctx.VALID_PLANNING_THEMES.includes(theme);
  assert.equal(ctx.state.listingsVisible,!planning);assert.equal(focus,true);
  assert.equal(ctx.state.planningTheme,planning?theme:'land_use_2030');
  assert.equal(ctx.state.initialRegion?.id,'dong-nai-expanded');
 }
});

test('planning region opens from its public display bounds without using listing geography',async()=>{
 const bounds=[[10.49,106.39],[12.33,107.6]];let initialized;
 const ctx={AbortController,mapLoadSequence:0,state:{open:true,initialRegion:{bounds}},
  loadLeaflet:async()=>({}),fetchJson(){throw Error('Must not use Binh Duong listing bounds for Dong Nai');},
  initMap:(L,b)=>{initialized=b;},renderMapScopeControls(){},requestSummary:async()=>{},setStatus(){},setPanelView(){}};
 ctx.URLSearchParams=URLSearchParams;vm.createContext(ctx);vm.runInContext(functions('startMapLoad'),ctx);
 await ctx.startMapLoad({mode:'all',query:'city=BẾN CÁT'});
 assert.deepEqual(initialized,bounds);
});

test('hiding cancels pending listing work and showing reloads the current viewport once',()=>{
 let summaryAborts=0,itemAborts=0,clears=0,closed=0,reloaded=0,cancelled=0,labels=0,resized=0;const busyTasks=[];
 const classes=new Set();
 const ctx={state:{open:true,listingsVisible:true,summaryController:{abort(){summaryAborts++;}},
  itemController:{abort(){itemAborts++;}},markerLayer:{clearLayers(){clears++;}},
  map:{fire(name,event){busyTasks.push(event);},invalidateSize(options){assert.equal(options.pan,false);resized++;}},
  workspace:{classList:{toggle(name,value){if(value)classes.add(name);else classes.delete(name);}}}},
  summarySequence:0,itemSequence:0,cancelMarkerRender(){cancelled++;},clearMarkerLabels(){labels++;},
  closePreview(){closed++;},requestSummary(){reloaded++;return Promise.resolve();},
  setPanelView(){},setStatus(){},root:{clearTimeout(){}},setMobileSheetExpanded(){}};
 ctx.URLSearchParams=URLSearchParams;vm.createContext(ctx);vm.runInContext(functions('setListingsVisible','requestSummary','setMapTask'),ctx);
 // The visibility setter calls the real loader; observe its current-view lookup instead of fetching.
 ctx.currentViewSnapshot=()=>{reloaded++;return null;};ctx.state.snapshot={mode:'all',query:'price_max=3'};
 assert.equal(ctx.setListingsVisible(false),false);
 assert.equal(summaryAborts,1);assert.equal(itemAborts,1);assert.equal(clears,1);
 assert(busyTasks.some(t=>t.key==='listings'&&t.busy===false),'Hiding listings clears the cancelled request spinner');
 assert.equal(cancelled,1);assert.equal(labels,1);assert.equal(closed,1);
 assert.ok(classes.has('listings-hidden'));
 ctx.requestSummary();assert.equal(reloaded,0,'Hidden Maps must not request listings when moved or refreshed');
 ctx.setListingsVisible(false);assert.equal(summaryAborts,1,'Repeated hiding is idempotent');
 assert.equal(ctx.setListingsVisible(true),true);assert.equal(reloaded,1);
 assert.equal(resized,1,'Read the current map size before loading the newly visible listings');
 assert.equal(classes.has('listings-hidden'),false);
});

test('a listing response arriving after hiding cannot restore markers or cards',async()=>{
 let deliver,rendered=0;
 const ctx={AbortController,state:{open:true,listingsVisible:true,snapshot:{mode:'all'},markerLayer:{clearLayers(){}}},
  summarySequence:0,itemSequence:0,currentViewSnapshot:()=>({mode:'all',query:'price_max=3'}),
  buildSummaryUrl:()=>'/api/map-listings?scope=viewport&price_max=3',
  fetchJson:()=>new Promise(resolve=>{deliver=resolve;}),setStatus(){},
  renderSummary(){rendered++;},cancelMarkerRender(){},clearMarkerLabels(){},closePreview(){},
  setMobileSheetExpanded(){},setPanelView(){},root:{clearTimeout(){}}};
 ctx.URLSearchParams=URLSearchParams;vm.createContext(ctx);vm.runInContext(functions('requestSummary','setListingsVisible','setMapTask'),ctx);
 const pending=ctx.requestSummary();ctx.setListingsVisible(false);
 deliver({locations:[{lat:11,lng:106.6}],recent:{items:[{id:1}]}});await pending;
 assert.equal(rendered,0);assert.equal(ctx.state.recentPayload,null);
});

test('all entries default to street',()=>{
 const ctx={};ctx.URLSearchParams=URLSearchParams;vm.createContext(ctx);vm.runInContext(functions('defaultBaseLayer'),ctx);
 assert.equal(ctx.defaultBaseLayer('administrative'),'street');
 assert.equal(ctx.defaultBaseLayer('administrative_legacy'),'street');
 for(const theme of [null,'land_use_2030','transport','partition'])assert.equal(ctx.defaultBaseLayer(theme),'street');
});
test('ordinary Maps opens Thu Dau Mot while retaining the frozen listing filters',async()=>{
 const el={hidden:true,classList:{add(){},toggle(){}},setAttribute(){},focus(){}};
 const snapshot={mode:'all',query:'city=BẾN CÁT&price_max=3&date_range=1w'};
 const ctx={state:{open:false},VALID_PLANNING_THEMES:['land_use_2030'],normalizedSnapshot:x=>x,element:()=>el,
  captureDashboardState(){},setMobileSheetExpanded(){},setFocusMode(){},syncAdminEditModeToggle(){},filterSummaryText:()=>'',emitTrack(){},defaultBaseLayer:()=> 'satellite',
  root:{document:{body:el},RadarPlanningArea:require('../../static/js/main/planning_area.js'),
   RADAR_LANDUSE_AREAS:require('../../config/planning_landuse_areas.json').provinces,RADAR_PLANNING_REGIONS:[],history:{pushState(){}},location:{href:'https://radarbds.vn/'}},
  DIRECTORY_BATCH_SIZE:100,startMapLoad:async()=>{}};
 ctx.URLSearchParams=URLSearchParams;vm.createContext(ctx);vm.runInContext(functions('open'),ctx);await ctx.open(snapshot,{});
 assert.equal(ctx.state.initialPlanningArea.province,'binh-duong');assert.equal(ctx.state.initialPlanningArea.district,'718');
 assert.equal(ctx.state.initialRegion.id,'binh-duong-legacy');assert.equal(ctx.state.snapshot.query,snapshot.query);
 ctx.state.open=false;await ctx.open({...snapshot,query:snapshot.query+'&ward=Tân An'},{});
 assert.equal(ctx.state.initialRegion,null,'A selected ward must not use the default city/province frame');
});

test('multi-listing marker opens its rail and clears loading after items arrive',async()=>{
 let resolve;const tasks=[],views=[],classes=new Set();
 const ctx={AbortController,itemSequence:0,state:{open:true,listingsVisible:true,snapshot:{mode:'all'},map:{fire() {},invalidateSize(){}},workspace:{classList:{toggle(k,v){v?classes.add(k):classes.delete(k);}}}},
 closePreview(){},isSingleListingGroup:g=>g.listing_count===1,adminEditTargetKind:()=>null,setMobileSheetExpanded(){},
 setPanelView:(...args)=>views.push(args),buildItemsUrl:()=>'/api/map-listing-items',emitTrack(){},
 fetchJson:()=>new Promise(r=>resolve=r),groupSelectionOutcome:()=>({kind:'items'}),setMapTask:(...args)=>tasks.push(args)};
 vm.createContext(ctx);vm.runInContext(functions('setGroupPanelOpen','selectGroup'),ctx);
 ctx.selectGroup({listing_count:3,location_key:'a'});assert(classes.has('has-group-panel'));
 assert.equal(views[0][0],'items-loading');assert.equal(tasks[0][1],true);
 resolve({items:[{id:1}]});await new Promise(r=>setImmediate(r));
 assert.equal(views.at(-1)[0],'items');assert.equal(tasks.at(-1)[1],false);
 ctx.setGroupPanelOpen(false);assert(!classes.has('has-group-panel'));
});


test('single ward opening zooms closer without changing the selected center',()=>{
 let view;const center={lat:11.02,lng:106.6};
 const ctx={URLSearchParams,state:{initialBounds:[[11,106.5],[11.1,106.7]],entrySnapshot:{query:'ward=Tân An'},
 map:{getBoundsZoom:()=>13,setView:(...args)=>view=args}},root:{}};
 vm.createContext(ctx);vm.runInContext(functions('frameOpeningArea'),ctx);
 ctx.frameOpeningArea({latLngBounds:()=>({getCenter:()=>center})});
 assert.equal(view[0],center);assert.equal(view[1],15);
});
