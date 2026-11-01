(function(root,factory){
  var api=factory(root);
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.RadarSatelliteLabels=api;
})(typeof window!=='undefined'?window:null,function(root){
  'use strict';
  var libraryPromise;
  function loadLibrary(){
    if(root.protomapsL)return Promise.resolve(root.protomapsL);
    if(libraryPromise)return libraryPromise;
    libraryPromise=new Promise(function(resolve,reject){
      var script=root.document.createElement('script');
      script.src='/static/vendor/protomaps-leaflet-4.0.1.js';script.async=true;
      script.onload=function(){if(root.protomapsL)resolve(root.protomapsL);else reject(new Error('OSM renderer unavailable'));};
      script.onerror=function(){script.remove();libraryPromise=null;reject(new Error('OSM renderer unavailable'));};
      root.document.head.appendChild(script);
    });
    return libraryPromise;
  }
  function labelRules(P){
    var text={labelProps:['name'],font:'600 12px sans-serif',fill:'#fff',stroke:'#172b23',width:3};
    function major(z,feature){return ['motorway','trunk','primary','secondary','tertiary'].indexOf(feature.props.kind)>=0;}
    return [
      {dataLayer:'street_labels',minzoom:9,filter:major,symbolizer:new P.LineLabelSymbolizer(Object.assign({repeatDistance:250,maxLabelChars:80},text))},
      {dataLayer:'street_labels',minzoom:15,filter:function(z,feature){return !major(z,feature);},symbolizer:new P.LineLabelSymbolizer(Object.assign({repeatDistance:180,maxLabelChars:80},text))},
      {dataLayer:'place_labels',minzoom:3,symbolizer:new P.CenteredTextSymbolizer(Object.assign({},text,{font:'600 13px sans-serif'}))},
      {dataLayer:'pois',minzoom:17,symbolizer:new P.CenteredTextSymbolizer(Object.assign({},text,{font:'11px sans-serif'}))}
    ];
  }
  function mount(L,map,satellite,notify){
    var vector,credit,pending=false,disposed=false,retryAt=0,reads=[],reading=0;
    function busy(key,value){if(!disposed)map.fire('planning:busy',{key:key,busy:value,label:'Đang tải tên đường OSM…'});}
    function eligible(){return !disposed&&map.hasLayer(satellite);}
    function hide(){
      if(vector&&map.hasLayer(vector))map.removeLayer(vector);
      if(credit){credit.remove();credit=null;}
      busy('osm-labels',false);
    }
    function cancelReads(){
      var error=new Error('Map labels cancelled');error.name='AbortError';
      reads.splice(0).forEach(function(read){read.reject(error);});
      if(vector)vector.views.forEach(function(view){
        var source=view.tileCache.source;
        source.zoomaborts.forEach(function(item){item.controller.abort();});source.zoomaborts=[];
      });
    }
    function pump(){
      while(reading<2&&reads.length){
        var read=reads.shift();reading++;
        read.run().then(read.resolve,read.reject).finally(function(){reading--;pump();});
      }
    }
    function queuedRead(get,coords,size){
      if(!eligible()){var error=new Error('Map labels cancelled');error.name='AbortError';return Promise.reject(error);}
      return new Promise(function(resolve,reject){reads.push({run:function(){return get(coords,size);},resolve:resolve,reject:reject});pump();});
    }
    function failed(error){
      if(disposed||error.name==='AbortError'||!map.hasLayer(satellite))return;
      retryAt=Date.now()+30000;hide();
      if(notify)notify('Tên đường OSM chưa tải được. Kéo hoặc zoom lại sau ít giây để thử lại.');
    }
    function show(P){
      if(!eligible())return;
      if(!vector){
        vector=P.leafletLayer({url:'/api/map-labels/osm/{z}/{x}/{y}.mvt',
          maxDataZoom:14,levelDiff:0,minZoom:0,maxZoom:23,
          pane:'satelliteLabels',paintRules:[],labelRules:labelRules(P),
          attribution:'&copy; OpenStreetMap contributors',updateWhenIdle:true,keepBuffer:1});
        // The pinned renderer settles failed reads internally; surface failures explicitly.
        vector.views.forEach(function(view){
          var source=view.tileCache.source,get=source.get.bind(source);
          source.get=function(coords,size){return queuedRead(get,coords,size).catch(function(error){failed(error);throw error;});};
        });
        vector.on('loading',function(){busy('osm-labels',true);});
        vector.on('load',function(){busy('osm-labels',false);});
        vector.on('remove',function(){cancelReads();busy('osm-labels',false);});
      }
      if(!map.hasLayer(vector))vector.addTo(map);
      if(!credit){
        credit=L.control({position:'bottomright'});
        credit.onAdd=function(){
          var link=L.DomUtil.create('a','radar-osm-credit');
          link.href='https://www.openstreetmap.org/copyright';link.target='_blank';link.rel='noopener';
          link.textContent='© OpenStreetMap';link.title='Nguồn tên đường và địa danh';
          L.DomEvent.disableClickPropagation(link);return link;
        };
        credit.addTo(map);
      }
    }
    function sync(){
      if(!eligible()||Date.now()<retryAt){busy('osm-labels-library',false);hide();return;}
      if(pending)return;
      if(vector){show();return;}
      pending=true;busy('osm-labels-library',true);
      loadLibrary().then(show).catch(failed).finally(function(){pending=false;busy('osm-labels-library',false);});
    }
    function dispose(){
      busy('osm-labels-library',false);hide();disposed=true;
      satellite.off('add',sync);satellite.off('remove',sync);map.off('zoomend',sync);map.off('unload',dispose);
    }
    satellite.on('add',sync);satellite.on('remove',sync);map.on('zoomend',sync);map.on('unload',dispose);
    return dispose;
  }
  return {mount:mount,labelRules:labelRules};
});
