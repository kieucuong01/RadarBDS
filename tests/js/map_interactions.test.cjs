const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const mapApi = require('../../static/js/main/listing_map.js');
const source = fs.readFileSync('static/js/main/listing_map.js','utf8');

// The real observer callback must track every actual container size, without panning.
let resized, disconnected=false;
const container={clientWidth:600,clientHeight:700};
const calls=[];
const dispose=mapApi.observeMapSize({getContainer:()=>container,invalidateSize:o=>calls.push(o)}, {
  ResizeObserver:class {constructor(fn){resized=fn;} observe(node){assert.equal(node,container);} disconnect(){disconnected=true;}}
});
resized();assert.equal(calls.length,0);
container.clientWidth=880;resized();assert.deepEqual(calls,[{pan:false}]);
container.clientWidth=620;resized();assert.equal(calls.length,2);
container.clientWidth=0;resized();assert.equal(calls.length,2);
dispose();assert.equal(disconnected,true);
container.clientWidth=900;resized();assert.equal(calls.length,2,'Closed Maps must not invalidate a removed map');

// Invoke the actual click handler; getCurrentPosition is the browser permission entry point.
let requested=0, denied, loading, feedback;
const locationContext={state:{locationRequestId:0,open:true,map:{}},
  root:{navigator:{geolocation:{getCurrentPosition(ok,error,options){requested++;denied=error;assert.equal(options.enableHighAccuracy,true);}}}},
  setLocationButtonLoading:v=>{loading=v;},showMapFeedback:message=>{feedback=message;},
  isCurrentLocationCallback:mapApi.isCurrentLocationCallback,geolocationErrorMessage:mapApi.geolocationErrorMessage};
vm.createContext(locationContext);
vm.runInContext(source.slice(source.indexOf('  function requestUserLocation()'),source.indexOf('  function copyShareUrl('))+'\nrequestUserLocation();',locationContext);
assert.equal(requested,1);assert.equal(loading,true);assert.match(feedback,/Cho phép/);
denied({code:1});assert.equal(loading,false);assert.match(feedback,/cài đặt trang web/);

// Exercise the real modal history helpers against a map entry and the Back result.
const modalSource=fs.readFileSync('static/js/main/modal.js','utf8');
const modal={style:{display:'flex'},dataset:{listingId:'42'}};
const entries=[{radarListingMap:true}],urls=['https://example.test/?tab=all'];
const location={href:urls[0],search:'?tab=all'};
const history={get state(){return entries.at(-1);},pushState(state,title,url){entries.push(state);urls.push(new URL(url,location.href).href);location.href=urls.at(-1);location.search=new URL(location.href).search;},
  back(){entries.pop();urls.pop();location.href=urls.at(-1);location.search=new URL(location.href).search;}};
const ctx={document:{getElementById:()=>modal},window:{history,location,setTimeout(){}},history,URL,URLSearchParams,setSignalModalOpen(){}};
vm.createContext(ctx);
vm.runInContext(modalSource.slice(modalSource.indexOf('let signalModalHistoryManaged'),modalSource.indexOf('function propertyTypeLabel'))+'\n_pushSignalModalHistory(42);',ctx);
assert.equal(history.state.radarListingMap,true);
assert.equal(history.state.signalModal,true);
vm.runInContext('_closeSignalModalViaHistory();',ctx);
assert.deepEqual(history.state,{radarListingMap:true});
assert.equal(mapApi.shouldCloseMapOnPopstate({state:history.state},true),false);
assert.equal(location.search,'?tab=all');
console.log('Map interactions: resize, permission request, denial feedback and modal return passed');
