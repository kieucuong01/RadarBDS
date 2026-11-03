(function(root,factory){var api=factory();if(typeof module==='object'&&module.exports)module.exports=api;if(root)root.RadarParcelCells=api;})(typeof window!=='undefined'?window:null,function(){
  'use strict';
  function keys(bounds,z){
    var n=Math.pow(2,z);
    function x(lng){return Math.floor((lng+180)/360*n);}
    function y(lat){var r=lat*Math.PI/180;return Math.floor((1-Math.asinh(Math.tan(r))/Math.PI)/2*n);}
    var west=x(bounds.getWest()),east=x(bounds.getEast()),north=y(bounds.getNorth()),south=y(bounds.getSouth()),result=[];
    if((east-west+1)*(south-north+1)>36)return result;
    for(var row=north;row<=south;row++)for(var col=west;col<=east;col++)result.push(col+'/'+row);
    return result;
  }
  function mount(map,L,env,options){
    var cache=new Map(),bytes=0,requests=new Map(),wanted=new Set(),features=new Map(),active=true,disposed=false,retries=new Map(),attempts=new Map();
    var group=L.layerGroup().addTo(map),renderer=L.canvas({pane:'planningParcels',padding:.1}),frame,run=0,queue=[],incomplete=false,failed=false;
    var underneath=null,hoverFrame;
    function forwardHover(event){
      if(!env.document||!renderer._container)return;
      var original=event,canvas=renderer._container;
      if(original.target!==canvas)return;
      cancel(hoverFrame);
      hoverFrame=raf(function(){
      if(disposed||!active)return;
      var target=env.document.elementsFromPoint(original.clientX,original.clientY).find(function(el){return el!==canvas&&map._targets&&map._targets[L.stamp(el)];});
      if(renderer._hoveredLayer){
        var covered=target&&map._targets&&map._targets[L.stamp(target)];
        if(covered&&covered.closeTooltip)covered.closeTooltip();
        target=null;
      }
      function send(el,type){if(el)el.dispatchEvent(new env.MouseEvent(type,{bubbles:true,clientX:original.clientX,clientY:original.clientY}));}
      if(underneath!==target){
        send(underneath,'mouseout');
        var oldLayer=underneath&&map._targets&&map._targets[L.stamp(underneath)];
        if(oldLayer&&oldLayer.closeTooltip)oldLayer.closeTooltip();
        send(target,'mouseover');underneath=target;
      }
      send(target,'mousemove');
      });
    }
    if(renderer.on)renderer.on('add',function(){renderer._container.addEventListener('mousemove',forwardHover);});
    var raf=env.requestAnimationFrame?env.requestAnimationFrame.bind(env):function(fn){return env.setTimeout(fn,0);};
    var cancel=env.cancelAnimationFrame?env.cancelAnimationFrame.bind(env):env.clearTimeout.bind(env);
    var selectionRequest,selectionSeq=0,originals=new Map();
    function cancelSelection(){++selectionSeq;if(selectionRequest)selectionRequest.abort();selectionRequest=null;}
    function pick(feature){
      cancelSelection();
      if(!feature.display_only||!options.featureTemplate){options.select(feature);return;}
      if(originals.has(feature.id)){options.select(originals.get(feature.id));return;}
      options.select(feature);
      var seq=++selectionSeq,request=new env.AbortController();selectionRequest=request;
      env.fetch(options.featureTemplate.replace('{id}',String(feature.id)),{signal:request.signal})
        .then(function(response){if(!response.ok)throw new Error('Original unavailable');return response.json();})
        .then(function(original){if(disposed||seq!==selectionSeq||request.signal.aborted)return;
          if(original.type!=='Feature'||original.id!==feature.id||original.display_only)throw new Error('Invalid original');
          originals.set(original.id,original);while(originals.size>32)originals.delete(originals.keys().next().value);
          options.select(original);
        }).catch(function(error){if(!disposed&&error.name!=='AbortError')status('Đã chọn thửa; chưa tải được hình học gốc để đo cạnh.',false);});
    }
    function status(message,busy){if(!disposed)options.status(message,busy);}
    function draw(){
      if(!active||disposed)return;
      var sequence=++run;cancel(frame);
      var desired=new Map(),truncated=false;
      var view=map.getBounds();
      wanted.forEach(function(key){var entry=cache.get(key);if(!entry)return;truncated=truncated||entry.data.truncated;entry.rows.forEach(function(row){
        var b=row.bounds;if(b[0]>view.getEast()||b[2]<view.getWest()||b[1]>view.getNorth()||b[3]<view.getSouth())return;
        if(desired.size<4000)desired.set(row.feature.id,row.feature);else truncated=true;
      });});
      incomplete=truncated;
      features.forEach(function(layer,id){if(!desired.has(id)){group.removeLayer(layer);features.delete(id);}});
      var additions=Array.from(desired.values()).filter(function(f){return !features.has(f.id);}),offset=0;
      function chunk(){
        if(disposed||sequence!==run||!active)return;
        var end=Math.min(offset+75,additions.length);
        for(;offset<end;offset++){
          var f=additions[offset];
          var layer=L.geoJSON(f,{pane:'planningParcels',renderer:renderer,smoothFactor:2,
            style:{color:'#334155',weight:.7,opacity:.28,fillOpacity:0},
            onEachFeature:function(feature,polygon){
              if(polygon.bindTooltip){var p=feature.properties||{};polygon.bindTooltip('Tờ '+(p.sheet==null?'—':p.sheet)+' · Thửa '+(p.parcel==null?'—':p.parcel),{sticky:true});}
              polygon.on('click',function(event){L.DomEvent.stopPropagation(event);pick(feature);});}});
          group.addLayer(layer);features.set(f.id,layer);
        }
        if(offset<additions.length)frame=raf(chunk);
        else status(features.size+' ranh trong vùng xem'+(failed?' · Một phần ranh chưa tải được.':truncated?' · Phóng gần để xem đủ ranh.':''),requests.size>0||queue.length>0);
      }
      chunk();
    }
    function put(key,data){
      var size=JSON.stringify(data).length*2,old=cache.get(key);if(old){bytes-=old.size;cache.delete(key);}
      cache.forEach(function(entry,id){if((cache.size>=32||bytes+size>8_000_000)&&!wanted.has(id)){cache.delete(id);bytes-=entry.size;}});
      if(bytes+size>8_000_000)throw new Error('Parcel view too dense');
      var rows=data.features.map(function(f){
        var bounds=[Infinity,Infinity,-Infinity,-Infinity];
        function walk(points){if(!Array.isArray(points))return;if(typeof points[0]==='number'){
          bounds[0]=Math.min(bounds[0],points[0]);bounds[1]=Math.min(bounds[1],points[1]);bounds[2]=Math.max(bounds[2],points[0]);bounds[3]=Math.max(bounds[3],points[1]);
        }else points.forEach(walk);}
        walk(f.geometry.coordinates);return {feature:f,bounds:bounds};
      });
      cache.delete(key);cache.set(key,{data:data,rows:rows,size:size,expires:Date.now()+180000});bytes+=size;
    }
    function baseKey(key){return key.split('/').slice(0,2).join('/');}
    function relevant(key){return wanted.has(baseKey(key));}
    function pump(){
      if(!active||disposed)return;
      while(requests.size<2&&queue.length){
        var key=queue.shift();if(!relevant(key)||requests.has(key))continue;
        var controller=new env.AbortController();requests.set(key,controller);
        (function(cell,request){
          var parts=cell.split('/'),base=baseKey(cell),live=parts[2]==='live',url=(live?options.liveTemplate:options.template).replace('{x}',parts[0]).replace('{y}',parts[1]);
          env.fetch(url,{signal:request.signal,credentials:'omit'}).then(function(response){if(!response.ok){var error=new Error('Cell unavailable');error.status=response.status;throw error;}return response.json();})
            .then(function(data){if(disposed||request.signal.aborted)return;if(data.type!=='FeatureCollection'||!Array.isArray(data.features)||data.features.length>1500)throw new Error('Invalid cell');if(live){
                var old=cache.get(base);if(!old)return;
                var merged=new Map(old.data.features.map(function(f){return [f.id,f];}));data.features.forEach(function(f){merged.set(f.id,f);});
                data={type:'FeatureCollection',features:Array.from(merged.values()),truncated:old.data.truncated||data.truncated,needs_live:false};
              }
              put(base,data);if(relevant(cell))draw();
              if(!live&&data.needs_live&&options.liveTemplate&&relevant(cell))queue.push(base+'/live');})
            .catch(function(error){if(!disposed&&error.name!=='AbortError'){
              if(error.status===503&&relevant(cell)&&!attempts.has(cell)){
                attempts.set(cell,1);retries.set(cell,env.setTimeout(function(){retries.delete(cell);if(!disposed&&active&&relevant(cell)){queue.push(cell);pump();}},2000));
              }else{failed=true;var cached=cache.get(base);if(live&&cached)cached.retryAt=Date.now()+30000;status('Một phần ranh chưa tải được. Các ranh đã tải vẫn được giữ lại.',false);}
            }})
            .finally(function(){if(requests.get(cell)===request)requests.delete(cell);pump();if(!disposed&&!requests.size&&!queue.length)status(features.size+' ranh trong vùng xem'+(failed?' · Một phần ranh chưa tải được.':incomplete?' · Phóng gần để xem đủ ranh.':''),false);});
        })(key,controller);
      }
    }
    function update(){
      if(disposed)return;
      active=options.enabled();
      failed=false;
      var cells=active?keys(map.getBounds(),options.zoom):[];
      wanted=new Set(cells);
      retries.forEach(function(timer,key){if(!relevant(key)){env.clearTimeout(timer);retries.delete(key);attempts.delete(key);}});
      attempts.forEach(function(value,key){if(!relevant(key))attempts.delete(key);});
      requests.forEach(function(request,key){if(!relevant(key)){request.abort();requests.delete(key);}});
      queue=[];
      if(!active){cancel(frame);++run;features.clear();group.clearLayers();status('Phóng to hoặc bật ranh thửa để xem.',false);return;}
      cells.forEach(function(key){var entry=cache.get(key);if(entry&&entry.expires>Date.now()){
        cache.delete(key);cache.set(key,entry);
        if(entry.retryAt>Date.now())failed=true;
        else if(entry.data.needs_live&&options.liveTemplate&&!requests.has(key+'/live')&&!retries.has(key+'/live'))queue.push(key+'/live');
      }else if(!requests.has(key)&&!retries.has(key))queue.push(key);});
      draw();pump();
      if(!cells.length)status('Vùng xem quá rộng; phóng gần để xem ranh thửa.',false);
    }
    return {update:update,pause:function(){active=false;++run;cancel(frame);},cancelSelection:cancelSelection,dispose:function(){disposed=true;active=false;if(renderer._container)renderer._container.removeEventListener('mousemove',forwardHover);cancel(hoverFrame);underneath=null;++run;cancelSelection();originals.clear();cancel(frame);requests.forEach(function(r){r.abort();});retries.forEach(function(t){env.clearTimeout(t);});retries.clear();requests.clear();queue=[];cache.clear();features.clear();map.removeLayer(group);map.removeLayer(renderer);}};
  }
  return {keys:keys,mount:mount};
});
