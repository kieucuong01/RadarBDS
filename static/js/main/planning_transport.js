(function(root,factory){var api=factory();if(typeof module==='object'&&module.exports)module.exports=api;if(root)root.RadarPlanningTransport=api;})(typeof window!=='undefined'?window:null,function(){
  'use strict';
  var cache=new WeakMap();
  var url='/static/data/planning_transport_roads.geojson?v=transport-gis-20261029';
  function valid(data){
    var vertices=0;
    return data&&data.type==='FeatureCollection'&&/^\d{4}-\d{2}-\d{2}$/.test(data.source_checked_on||'')
      &&data.source_url==='https://gisxaydung.tphcm.gov.vn/tracuuttqh'
      &&Array.isArray(data.features)&&data.features.length>0&&data.features.length<=200
      &&data.features.every(function(f){
        var p=f&&f.properties,g=f&&f.geometry;
        return f&&f.type==='Feature'&&p&&Number.isInteger(p.source_id)&&p.source_id>0
          &&typeof p.name==='string'&&p.name.length<=300&&typeof p.label==='string'&&p.label.length<=300
          &&typeof p.source_status==='string'&&p.source_status.length<=100
          &&(p.source_service==='GiaoThongHienTrang'&&((p.group==='corridor'&&p.source_layer===1)||(p.group==='ring'&&p.source_layer===2))
            ||p.source_service==='HTKT_QHCTP'&&p.source_layer===14&&['ring1_segments','ring2'].indexOf(p.group)>=0)
          &&g&&g.type==='MultiLineString'&&Array.isArray(g.coordinates)&&g.coordinates.length>0&&g.coordinates.length<=100
          &&g.coordinates.every(function(line){return Array.isArray(line)&&line.length>=2&&line.every(function(x){
            return ++vertices<=100000&&Array.isArray(x)&&x.length===2&&x.every(Number.isFinite)
              &&x[0]>=105&&x[0]<=108&&x[1]>=10&&x[1]<=12.3;
          });});
      });
  }
  function style(feature,amount){
    var p=feature.properties;
    return {color:p.group==='corridor'?'#ff5500':p.group==='ring1_segments'?'#60a5fa':p.group==='ring2'?'#22d3ee':'#00a884',
      weight:p.group==='corridor'?3:3.5,opacity:amount,fill:false,
      dashArray:p.source_status.indexOf('mở mới')>=0?'7 5':null,interactive:false};
  }
  function create(map,L,env,manifest,options){
    var active=false,amount=options.opacity,records=null,labels;
    var layer=L.geoJSON(null,{pane:options.pane,interactive:false,attribution:options.attribution,
      style:function(f){return style(f,amount);},onEachFeature:function(f,line){
        if(map.getZoom()<11||labels.has(f.properties.label))return;
        labels.add(f.properties.label);
        var text=env.document.createElement('span');text.textContent=f.properties.label;
        line.bindTooltip(text,{permanent:true,direction:'center',interactive:false,opacity:amount,className:'planning-transport-label'});
      }});
    layer.setOpacity=function(value){amount=value;layer.setStyle({opacity:amount});layer.eachLayer(function(line){var tip=line.getTooltip();if(tip)tip.setOpacity(amount);});};
    function render(){
      if(!active||!records)return;
      labels=new Set();layer.clearLayers();
      records.forEach(function(r){if(map.getBounds().intersects(r.bounds))layer.addData(r.feature);});
      layer.fire('load');
    }
    function accept(data){
      if(!valid(data))throw new Error('Invalid transport source');
      cache.set(env,data);
      records=data.features.map(function(f){
        var south=Infinity,west=Infinity,north=-Infinity,east=-Infinity;
        f.geometry.coordinates.forEach(function(line){line.forEach(function(p){south=Math.min(south,p[1]);north=Math.max(north,p[1]);west=Math.min(west,p[0]);east=Math.max(east,p[0]);});});
        return {feature:f,bounds:[[south,west],[north,east]]};
      });render();
    }
    layer.on('add',function(){
      active=true;map.on('moveend',render);
      if(records){render();return;}
      if(cache.has(env)){accept(cache.get(env));return;}
      env.fetch(url,{signal:options.signal}).then(function(r){if(!r.ok)throw new Error('Transport unavailable');return r.json();})
        .then(accept).catch(function(e){if(active&&e.name!=='AbortError')layer.fire('error');});
    });
    layer.on('remove',function(){active=false;map.off('moveend',render);});
    return layer;
  }
  return {valid:valid,style:style,create:create,url:url};
});
