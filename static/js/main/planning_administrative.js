(function(root,factory){var sources=typeof module==='object'&&module.exports?require('./planning_administrative_sources.js'):root&&root.RadarAdministrativeSources;var api=factory(sources);if(typeof module==='object'&&module.exports)module.exports=api;if(root)root.RadarAdministrativeBoundaries=api;})(typeof window!=='undefined'?window:null,function(datasets){
  'use strict';
  var cache=new WeakMap();
  function dataset(id){return datasets&&Object.hasOwn(datasets,id||'hcm-administrative-2025')?datasets[id||'hcm-administrative-2025']:null;}
  function validManifest(m){
    var d=m&&dataset(m.id);
    return !!d&&m.status==='reference_overlay'&&m.source_kind===d.kind&&m.render_mode==='geojson'
      &&m.geojson_url===d.url&&m.unit_count===d.count&&JSON.stringify(m.bounds)===JSON.stringify(d.bounds)
      &&typeof m.title==='string'&&typeof m.notice==='string';
  }
  function validCatalogItem(item){var d=item&&dataset(item.id);return !!d&&item.theme===d.theme&&item.source==='gis'&&item.source_url===d.source&&validManifest(item.manifest)&&item.manifest.id===item.id;}
  var palette=['#38bdf8','#fb7185','#a78bfa','#fbbf24','#34d399','#f472b6','#fb923c','#2dd4bf'];
  function pair(p){return Array.isArray(p)&&p.length===2&&p.every(Number.isFinite);}
  function bounds(b,id){var d=dataset(id);if(!d)return false;var l=d.limits;return Array.isArray(b)&&b.length===2&&b.every(pair)&&b[0][0]>=l[0]&&b[1][0]<=l[2]&&b[0][1]>=l[1]&&b[1][1]<=l[3]&&b[0][0]<b[1][0]&&b[0][1]<b[1][1];}
  function validFeature(f,expected,id){
    var d=dataset(id);if(!d)return false;var l=d.limits;
    var p=f&&f.properties,g=f&&f.geometry,vertices=0;
    if(!f||f.type!=='Feature'||!p||!/^[A-Z0-9]{5,8}$/.test(p.code||'')||!Number.isInteger(p.source_id)||p.source_id<1
      ||d.codes.indexOf(p.code)<0||typeof p.name!=='string'||!p.name.length||p.name.length>100||!bounds(p.bounds,id)||!pair(p.label)
      ||p.label[0]<p.bounds[0][0]||p.label[0]>p.bounds[1][0]||p.label[1]<p.bounds[0][1]||p.label[1]>p.bounds[1][1]
      ||!Number.isInteger(p.colour)||p.colour<0||p.colour>=palette.length||!g||['Polygon','MultiPolygon'].indexOf(g.type)<0)return false;
    if(expected&&(p.code!==expected.code||p.name!==expected.name||p.source_id!==expected.source_id||JSON.stringify(p.bounds)!==JSON.stringify(expected.bounds)))return false;
    function polygon(rings){return Array.isArray(rings)&&rings.length>0&&rings.length<=500&&rings.every(function(ring){
      return Array.isArray(ring)&&ring.length>=4&&ring.every(function(x){return ++vertices<=d.max_vertices&&pair(x)&&x[0]>=l[1]&&x[0]<=l[3]&&x[1]>=l[0]&&x[1]<=l[2];})
        &&ring[0][0]===ring[ring.length-1][0]&&ring[0][1]===ring[ring.length-1][1];
    });}
    return g.type==='Polygon'?polygon(g.coordinates):Array.isArray(g.coordinates)&&g.coordinates.length>0&&g.coordinates.length<=(d.max_polygons||500)&&g.coordinates.every(polygon);
  }
  function valid(data,id){
    var d=dataset(id);if(!d)return false;
    if(!data||data.type!=='FeatureCollection'||data.source_url!==d.source
      ||data.source_service!==d.service||data.detail_min_zoom!==13||data.overview_simplification_metres!==10
      ||!/^\d{4}-\d{2}-\d{2}$/.test(data.source_checked_on||'')||!Array.isArray(data.features)||data.features.length!==d.count)return false;
    var codes=new Set();return data.features.every(function(f){if(!validFeature(f,null,id)||codes.has(f.properties.code))return false;codes.add(f.properties.code);return true;});
  }
  function create(map,L,env,manifest,options){
    var id=manifest.id||'hcm-administrative-2025',d=dataset(id);if(!d)throw new Error('Unknown administrative dataset');
    var base=d.base,version=d.query,byDataset=cache.get(env);if(!byDataset){byDataset=new Map();cache.set(env,byDataset);}
    var shared=byDataset.get(id);if(!shared){shared={overview:null,details:new Map(),pending:new Set(),subscribers:new Set()};byDataset.set(id,shared);}
    var active=false,moving=false,amount=options.opacity,queue=[],pending=shared.pending,shown=[],rendered=new Map();
    var areas=L.geoJSON(null,{pane:'planningAdministrative',interactive:true,bubblingMouseEvents:false,onEachFeature:function(f,polygon){
      var p=f.properties,text=env.document.createElement('span');text.textContent=p.name+(p.district?' · '+p.district+' · '+p.former_province+' (cũ)':'');
      polygon.bindTooltip(text,{pane:'planningAdministrativeLabels',permanent:false,sticky:true,direction:'top',className:'planning-admin-tooltip'});
      polygon.on('click',function(){
        if(!active||map.getContainer().classList.contains('planning-is-drawing'))return;
        var zoom=Math.min(map.getMaxZoom(),Math.max(map.getZoom()+1,map.getBoundsZoom(p.bounds,false,[64,160])));
        map.setView(p.label,zoom);
      });
    },style:function(f){
      return {color:palette[f.properties.colour],weight:1.3,opacity:amount,fillColor:palette[f.properties.colour],fillOpacity:amount*.17,interactive:true};
    }}),group=L.layerGroup([areas]);
    group.options.attribution=options.attribution;
    group.setOpacity=function(value){amount=value;areas.setStyle({opacity:amount,fillOpacity:amount*.17});};
    function paint(refreshLabels){
      if(!active||moving||!shared.overview)return;
      shown=shared.overview.features.filter(function(f){return map.getBounds().intersects(f.properties.bounds);});
      var visible=new Set(shown.map(function(f){return f.properties.code;}));
      rendered.forEach(function(entry,code){if(!visible.has(code)){areas.removeLayer(entry.layer);rendered.delete(code);}});
      var detailed=map.getZoom()>=13;
      shown.forEach(function(f){
        var p=f.properties,feature=detailed&&shared.details.has(p.code)?shared.details.get(p.code):f,previous=rendered.get(p.code);
        if(!previous||previous.feature!==feature){
          if(previous)areas.removeLayer(previous.layer);
          areas.addData(feature);var children=areas.getLayers();
          rendered.set(p.code,{feature:feature,layer:children[children.length-1]});
        }

      });
      queue=detailed?shown.filter(function(f){return !shared.details.has(f.properties.code)&&!pending.has(f.properties.code);}):[];
      group.fire('load');pump();
    }
    function pump(){
      while(active&&!moving&&pending.size<4&&queue.length){
        (function(f){var code=f.properties.code;pending.add(code);
          env.fetch(base+code+'.json'+version,{signal:options.signal}).then(function(r){if(!r.ok)throw new Error('Administrative detail unavailable');return r.json();})
            .then(function(data){if(!validFeature(data,f.properties,id))throw new Error('Invalid administrative detail');shared.details.set(code,data);})
            .catch(function(e){if(active&&e.name!=='AbortError'&&map.getZoom()>=13&&shown.some(function(item){return item.properties.code===code;}))group.fire('error');})
            .finally(function(){pending.delete(code);shared.subscribers.forEach(function(render){render(false);});});
        })(queue.shift());
      }
    }
    function moveStart(){moving=true;queue=[];}
    function moveEnd(){moving=false;paint();}
    group.on('add',function(){
      active=true;moving=false;shared.subscribers.add(paint);map.on('movestart',moveStart);map.on('moveend',moveEnd);
      if(shared.overview){paint();return;}
      env.fetch(base+'overview.json'+version,{signal:options.signal}).then(function(r){if(!r.ok)throw new Error('Administrative boundaries unavailable');return r.json();})
        .then(function(data){if(!valid(data,id))throw new Error('Invalid administrative source');shared.overview=data;paint();})
        .catch(function(e){if(active&&e.name!=='AbortError')group.fire('error');});
    });
    group.on('remove',function(){active=false;queue=[];shared.subscribers.delete(paint);map.off('movestart',moveStart);map.off('moveend',moveEnd);});
    return group;
  }
  return {valid:valid,validFeature:validFeature,validManifest:validManifest,validCatalogItem:validCatalogItem,create:create};
});
