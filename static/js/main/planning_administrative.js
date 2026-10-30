(function(root,factory){var api=factory();if(typeof module==='object'&&module.exports)module.exports=api;if(root)root.RadarAdministrativeBoundaries=api;})(typeof window!=='undefined'?window:null,function(){
  'use strict';
  var cache=new WeakMap(),base='/static/data/admin_hcm_2025/',version='?v=administrative-20261029';
  var palette=['#38bdf8','#fb7185','#a78bfa','#fbbf24','#34d399','#f472b6','#fb923c','#2dd4bf'];
  function pair(p){return Array.isArray(p)&&p.length===2&&p.every(Number.isFinite);}
  function bounds(b){return Array.isArray(b)&&b.length===2&&b.every(pair)&&b[0][0]>=8.5&&b[1][0]<=11.65&&b[0][1]>=106.25&&b[1][1]<=107.75&&b[0][0]<b[1][0]&&b[0][1]<b[1][1];}
  function validFeature(f,expected){
    var p=f&&f.properties,g=f&&f.geometry,vertices=0;
    if(!f||f.type!=='Feature'||!p||!/^\d{5}$/.test(p.code||'')||!Number.isInteger(p.source_id)||p.source_id<1
      ||typeof p.name!=='string'||!p.name.length||p.name.length>100||!bounds(p.bounds)||!pair(p.label)
      ||p.label[0]<p.bounds[0][0]||p.label[0]>p.bounds[1][0]||p.label[1]<p.bounds[0][1]||p.label[1]>p.bounds[1][1]
      ||!Number.isInteger(p.colour)||p.colour<0||p.colour>=palette.length||!g||['Polygon','MultiPolygon'].indexOf(g.type)<0)return false;
    if(expected&&(p.code!==expected.code||p.name!==expected.name||p.source_id!==expected.source_id||JSON.stringify(p.bounds)!==JSON.stringify(expected.bounds)))return false;
    function polygon(rings){return Array.isArray(rings)&&rings.length>0&&rings.length<=500&&rings.every(function(ring){
      return Array.isArray(ring)&&ring.length>=4&&ring.every(function(x){return ++vertices<=20000&&pair(x)&&x[0]>=106.25&&x[0]<=107.75&&x[1]>=8.5&&x[1]<=11.65;})
        &&ring[0][0]===ring[ring.length-1][0]&&ring[0][1]===ring[ring.length-1][1];
    });}
    return g.type==='Polygon'?polygon(g.coordinates):Array.isArray(g.coordinates)&&g.coordinates.length>0&&g.coordinates.length<=500&&g.coordinates.every(polygon);
  }
  function valid(data){
    if(!data||data.type!=='FeatureCollection'||data.source_url!=='https://gisxaydung.tphcm.gov.vn/tracuuttqh'
      ||data.source_service!=='HanhChinhXa/FeatureServer/0'||data.detail_min_zoom!==13||data.overview_simplification_metres!==10
      ||!/^\d{4}-\d{2}-\d{2}$/.test(data.source_checked_on||'')||!Array.isArray(data.features)||data.features.length!==168)return false;
    var codes=new Set();return data.features.every(function(f){if(!validFeature(f)||codes.has(f.properties.code))return false;codes.add(f.properties.code);return true;});
  }
  function create(map,L,env,manifest,options){
    var shared=cache.get(env);if(!shared){shared={overview:null,details:new Map(),pending:new Set(),subscribers:new Set()};cache.set(env,shared);}
    var active=false,amount=options.opacity,queue=[],pending=shared.pending,shown=[],rendered=new Map();
    var areas=L.geoJSON(null,{pane:'planningAdministrative',interactive:false,style:function(f){
      return {color:palette[f.properties.colour],weight:1.3,opacity:amount,fillColor:palette[f.properties.colour],fillOpacity:amount*.17,interactive:false};
    }}),labels=L.layerGroup(),group=L.layerGroup([areas,labels]);
    group.options.attribution=options.attribution;
    group.setOpacity=function(value){amount=value;areas.setStyle({opacity:amount,fillOpacity:amount*.17});labels.eachLayer(function(m){m.setOpacity(amount);});};
    function paint(refreshLabels){
      if(!active||!shared.overview)return;
      shown=shared.overview.features.filter(function(f){return map.getBounds().intersects(f.properties.bounds);});
      var visible=new Set(shown.map(function(f){return f.properties.code;}));
      rendered.forEach(function(entry,code){if(!visible.has(code)){areas.removeLayer(entry.layer);rendered.delete(code);}});
      if(refreshLabels!==false)labels.clearLayers();
      var occupied=[],size=map.getSize(),detailed=map.getZoom()>=13;
      shown.forEach(function(f){
        var p=f.properties,feature=detailed&&shared.details.has(p.code)?shared.details.get(p.code):f,previous=rendered.get(p.code);
        if(!previous||previous.feature!==feature){
          if(previous)areas.removeLayer(previous.layer);
          areas.addData(feature);var children=areas.getLayers();
          rendered.set(p.code,{feature:feature,layer:children[children.length-1]});
        }
        if(refreshLabels===false||map.getZoom()<9)return;
        var pt=map.latLngToContainerPoint(p.label);
        if(pt.x<12||pt.y<12||pt.x>size.x-12||pt.y>size.y-12||occupied.some(function(o){return Math.abs(o.x-pt.x)<112&&Math.abs(o.y-pt.y)<32;}))return;
        occupied.push(pt);var text=env.document.createElement('span');text.textContent=p.name;text.style.borderColor=palette[p.colour];
        var icon=L.divIcon({html:text,iconSize:null,className:'planning-admin-label-marker'});
        L.marker(p.label,{icon:icon,pane:'planningAdministrativeLabels',interactive:false,keyboard:false,opacity:amount}).addTo(labels);
      });
      queue=detailed?shown.filter(function(f){return !shared.details.has(f.properties.code)&&!pending.has(f.properties.code);}):[];
      group.fire('load');pump();
    }
    function pump(){
      while(active&&pending.size<4&&queue.length){
        (function(f){var code=f.properties.code;pending.add(code);
          env.fetch(base+code+'.json'+version,{signal:options.signal}).then(function(r){if(!r.ok)throw new Error('Administrative detail unavailable');return r.json();})
            .then(function(data){if(!validFeature(data,f.properties))throw new Error('Invalid administrative detail');shared.details.set(code,data);})
            .catch(function(e){if(active&&e.name!=='AbortError'&&map.getZoom()>=13&&shown.some(function(item){return item.properties.code===code;}))group.fire('error');})
            .finally(function(){pending.delete(code);shared.subscribers.forEach(function(render){render(false);});});
        })(queue.shift());
      }
    }
    group.on('add',function(){
      active=true;shared.subscribers.add(paint);map.on('moveend',paint);
      if(shared.overview){paint();return;}
      env.fetch(base+'overview.json'+version,{signal:options.signal}).then(function(r){if(!r.ok)throw new Error('Administrative boundaries unavailable');return r.json();})
        .then(function(data){if(!valid(data))throw new Error('Invalid administrative source');shared.overview=data;paint();})
        .catch(function(e){if(active&&e.name!=='AbortError')group.fire('error');});
    });
    group.on('remove',function(){active=false;queue=[];shared.subscribers.delete(paint);map.off('moveend',paint);});
    return group;
  }
  return {valid:valid,validFeature:validFeature,create:create};
});
