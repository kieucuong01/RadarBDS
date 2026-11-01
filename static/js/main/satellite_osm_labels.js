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
  function majorRoad(z,feature){return ['motorway','trunk','primary','secondary','tertiary'].indexOf(feature.props.kind)>=0;}
  function guideRoad(z,feature){return majorRoad(z,feature)&&feature.props.kind!=='tertiary';}
  function roadLabel(properties){
    var name=String(properties.name||'').trim(),ref=String(properties.ref||'').trim();
    function compact(value){return value.toLowerCase().replace(/[^a-z0-9]/g,'');}
    if(ref&&/^(Quốc lộ|Đường tỉnh|Tỉnh lộ)\s+[\w.]+$/iu.test(name))return ref.replace(/\./g,'');
    return !name?ref:!ref||compact(name).indexOf(compact(ref))>=0?name:name+' · '+ref;
  }
  function overviewSymbolizer(P,text){
    var base=new P.CenteredTextSymbolizer(text);
    return {place:function(layout,geom,feature){
      var labels=base.place(layout,geom,feature);
      if(labels)labels.forEach(function(label){
        var key=String(feature.props.ref||feature.props.name||'').toLowerCase().replace(/^đường\s+/,'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/đ/g,'d').replace(/[^a-z0-9]/g,'');
        label.deduplicationKey='road-guide:'+key;label.deduplicationDistance=240;
      });
      return labels;
    }};
  }
  function prepareNames(data){
    var overview=[];
    ['street_labels','street_labels_points'].forEach(function(layer){
      (data.get(layer)||[]).forEach(function(feature){
        feature.props.radar_road_label=roadLabel(feature.props);
        if(layer!=='street_labels'||!guideRoad(0,feature)||!feature.props.radar_road_label||/^(Cầu|Vòng xoay|Nút giao|Hầm|Ngã)(\s|$)/iu.test(String(feature.props.name||'')))return;
        var path=feature.geom.reduce(function(best,line){return line.length>best.length?line:best;},[]);
        if(!path.length)return;
        var point=path[Math.floor(path.length/2)];
        overview.push({props:feature.props,geomType:1,geom:[[point]],numVertices:1,
          bbox:{minX:point.x,maxX:point.x,minY:point.y,maxY:point.y}});
      });
    });
    data.set('radar_major_labels',overview);
    return data;
  }
  function paintRules(P){
    function overview(z,feature){return z<15&&guideRoad(z,feature);}
    return [
      {dataLayer:'streets',maxzoom:15,filter:overview,symbolizer:new P.LineSymbolizer({color:'#fff',width:3.6,opacity:.65})},
      {dataLayer:'streets',maxzoom:15,filter:overview,symbolizer:new P.LineSymbolizer({color:'#dc5555',width:2,opacity:.9})}
    ];
  }
  function labelRules(P){
    var text={labelProps:['name'],font:'600 12px sans-serif',fill:'#fff',stroke:'#172b23',width:3};
    return [
      {dataLayer:'radar_major_labels',minzoom:9,maxzoom:15,filter:function(z,feature){return z<15&&guideRoad(z,feature);},symbolizer:overviewSymbolizer(P,Object.assign({},text,{font:'600 11px sans-serif',labelProps:['radar_road_label','name','ref']}))},
      {dataLayer:'street_labels_points',minzoom:6,maxzoom:10,filter:function(z,feature){return z<10&&guideRoad(z,feature);},symbolizer:new P.CenteredTextSymbolizer(Object.assign({},text,{labelProps:['ref','name'],font:'600 11px sans-serif'}))},
      {dataLayer:'street_labels',minzoom:15,filter:majorRoad,symbolizer:new P.LineLabelSymbolizer(Object.assign({repeatDistance:250,maxLabelChars:80},text))},
      {dataLayer:'street_labels',minzoom:15,filter:function(z,feature){return !majorRoad(z,feature);},symbolizer:new P.LineLabelSymbolizer(Object.assign({repeatDistance:180,maxLabelChars:80},text))},
      {dataLayer:'place_labels',minzoom:15,symbolizer:new P.CenteredTextSymbolizer(Object.assign({},text,{font:'600 13px sans-serif'}))},
      {dataLayer:'pois',minzoom:17,symbolizer:new P.CenteredTextSymbolizer(Object.assign({},text,{font:'11px sans-serif'}))}
    ];
  }
  function mount(L,map,satellite,notify){
    var vector,credit,pending=false,disposed=false,retryAt=0,reads=[],reading=0,nativeZoom,retries=new Set();
    function aborted(){var error=new Error('Map labels cancelled');error.name='AbortError';return error;}
    function busy(key,value){if(!disposed)map.fire('planning:busy',{key:key,busy:value,label:'Đang tải tên đường OSM…'});}
    function eligible(){return !disposed&&map.hasLayer(satellite);}
    function hide(){
      if(vector&&map.hasLayer(vector))map.removeLayer(vector);
      if(credit){credit.remove();credit=null;}
      busy('osm-labels',false);
    }
    function cancelReads(){
      var error=aborted();
      reads.splice(0).forEach(function(read){read.reject(error);});
      retries.forEach(function(retry){root.clearTimeout(retry.timer);retry.reject(error);});retries.clear();
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
      if(!eligible())return Promise.reject(aborted());
      if(nativeZoom!==coords.z){cancelReads();nativeZoom=coords.z;}
      function run(){
        return get(coords,size).catch(function(error){
          if(!/HTTP (502|503|504)$/.test(error.message)||!eligible())throw error;
          return new Promise(function(resolve,reject){
            var retry={reject:reject,timer:null};
            retry.timer=root.setTimeout(function(){retries.delete(retry);resolve();},/HTTP 503$/.test(error.message)?2000:400);retries.add(retry);
          }).then(function(){if(!eligible()||nativeZoom!==coords.z)throw aborted();return get(coords,size);});
        });
      }
      return new Promise(function(resolve,reject){reads.push({run:run,resolve:resolve,reject:reject});pump();});
    }
    function failed(error){
      if(disposed||error.name==='AbortError'||!map.hasLayer(satellite))return;
      if(Date.now()>=retryAt&&notify)notify('Một phần tên đường chưa tải được. Các vùng đã tải vẫn được giữ lại.');
      retryAt=Date.now()+30000;
    }
    function show(P){
      if(!eligible())return;
      if(!vector){
        vector=P.leafletLayer({url:'/api/map-labels/osm/{z}/{x}/{y}.mvt',
          maxDataZoom:14,levelDiff:0,minZoom:0,maxZoom:23,
          pane:'satelliteLabels',paintRules:paintRules(P),labelRules:labelRules(P),
          attribution:'&copy; OpenStreetMap contributors',updateWhenIdle:true,keepBuffer:1});
        // The pinned renderer settles failed reads internally; surface failures explicitly.
        vector.views.forEach(function(view){
          var source=view.tileCache.source,get=source.get.bind(source);
          source.get=function(coords,size){return queuedRead(get,coords,size).then(prepareNames).catch(function(error){failed(error);throw error;});};
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
      if(!eligible()){busy('osm-labels-library',false);hide();return;}
      if(!vector&&Date.now()<retryAt)return;
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
  return {mount:mount,labelRules:labelRules,paintRules:paintRules,roadLabel:roadLabel,prepareNames:prepareNames};
});
