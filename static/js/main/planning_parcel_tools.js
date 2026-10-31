(function(root,factory){
  var measure=typeof module==='object'&&module.exports?require('./planning_measure.js'):root&&root.RadarPlanningMeasure;
  var api=factory(measure);if(typeof module==='object'&&module.exports)module.exports=api;if(root)root.RadarParcelTools=api;
})(typeof window!=='undefined'?window:null,function(measure){
  'use strict';
  function point(p){return Array.isArray(p)?{lat:p[1],lng:p[0]}:p;}
  function inside(p,ring){
    p=point(p);var hit=false;
    for(var i=0,j=ring.length-1;i<ring.length;j=i++){
      var a=ring[i],b=ring[j];
      if((a[1]>p.lat)!==(b[1]>p.lat)&&p.lng<(b[0]-a[0])*(p.lat-a[1])/(b[1]-a[1])+a[0])hit=!hit;
    }
    return hit;
  }
  function contains(p,rings){return inside(p,rings[0])&&!rings.slice(1).some(function(r){return inside(p,r);});}
  function interior(rings){
    var outer=rings[0],xs=outer.map(function(p){return p[0];}),ys=outer.map(function(p){return p[1];});
    var low=Math.min.apply(null,ys),high=Math.max.apply(null,ys),best,width=0;
    var middle={lat:(low+high)/2,lng:(Math.min.apply(null,xs)+Math.max.apply(null,xs))/2};
    if(contains(middle,rings))return middle;
    // A scanline midpoint stays inside concave polygons and outside holes.
    for(var scan=1;scan<=31;scan++){
      var y=low+(high-low)*scan/32,cuts=[];
      rings.forEach(function(ring){for(var i=1;i<ring.length;i++){
        var a=ring[i-1],b=ring[i];if((a[1]>y)!==(b[1]>y))cuts.push(a[0]+(b[0]-a[0])*(y-a[1])/(b[1]-a[1]));
      }});
      cuts.sort(function(a,b){return a-b;});
      for(var j=1;j<cuts.length;j++){
        var p={lat:y,lng:(cuts[j-1]+cuts[j])/2},span=cuts[j]-cuts[j-1];
        if(span>width&&contains(p,rings)){best=p;width=span;}
      }
    }
    return best||null;
  }
  function metrics(feature){
    var g=feature&&feature.geometry;if(!g||!measure||['Polygon','MultiPolygon'].indexOf(g.type)<0)return null;
    var polygons=g.type==='Polygon'?[g.coordinates]:g.coordinates,vertices=0;
    if(!Array.isArray(polygons)||!polygons.length||polygons.length>500)return null;
    if(!polygons.every(function(rings){return Array.isArray(rings)&&rings.length>0&&rings.length<=200&&rings.every(function(r){
      return Array.isArray(r)&&r.length>=4&&r.every(function(p){return ++vertices<=20000&&Array.isArray(p)&&p.length>=2&&Number.isFinite(p[0])&&Number.isFinite(p[1])&&Math.abs(p[0])<=180&&Math.abs(p[1])<85;})
        &&r[0][0]===r[r.length-1][0]&&r[0][1]===r[r.length-1][1];
    });}))return null;
    var edges=[],total=0,largest,largestArea=-1;
    polygons.forEach(function(rings){
      var value=measure.area(rings[0].slice(0,-1).map(point))-rings.slice(1).reduce(function(sum,r){return sum+measure.area(r.slice(0,-1).map(point));},0);
      total+=Math.max(0,value);if(value>largestArea){largest=rings;largestArea=value;}
      rings.forEach(function(r){for(var i=1;i<r.length;i++){
        var a=point(r[i-1]),b=point(r[i]),length=measure.distance(a,b);
        if(length>.01)edges.push({a:a,b:b,at:{lat:(a.lat+b.lat)/2,lng:(a.lng+b.lng)/2},distance:length});
      }});
    });
    var center=interior(largest);if(!center||!total)return null;
    var recorded=feature.properties&&feature.properties.area,hasArea=Number.isFinite(recorded)&&recorded>0;
    return {edges:edges,center:center,outline:largest[0].slice(0,-1).map(point),computedArea:total,area:hasArea?recorded:total,areaSource:hasArea?'recorded':'geometry'};
  }
  function directions(center){return 'https://www.google.com/maps/dir/?api=1&destination='+encodeURIComponent(center.lat+','+center.lng)+'&travelmode=driving';}
  function mount(map,L,env){
    var group=L.layerGroup().addTo(map),selected=null,disposed=false;
    ['planningParcelDimensions','planningParcelPin'].forEach(function(name,index){var pane=map.createPane(name);pane.style.zIndex=String(423+index);pane.style.pointerEvents='none';});
    function marker(at,html,className,size,anchor,pane){return L.marker(at,{pane:pane||'planningParcelDimensions',interactive:false,keyboard:false,
      icon:L.divIcon({className:className,html:html,iconSize:size,iconAnchor:anchor})}).addTo(group);}
    function render(){
      group.clearLayers();if(!selected||disposed)return;
      var m=selected;
      m.edges.filter(function(e){var a=map.latLngToContainerPoint(e.a),b=map.latLngToContainerPoint(e.b);return m.edges.length<=30||Math.hypot(b.x-a.x,b.y-a.y)>=35;})
        .sort(function(a,b){return b.distance-a.distance;}).slice(0,250).forEach(function(e){
          var a=map.latLngToContainerPoint(e.a),b=map.latLngToContainerPoint(e.b),angle=Math.atan2(b.y-a.y,b.x-a.x)*180/Math.PI;
          if(angle>90)angle-=180;if(angle<-90)angle+=180;
          marker(e.at,'<span style="transform:rotate('+angle+'deg)">'+measure.formatDistance(e.distance)+'</span>','parcel-edge-label',[90,18],[45,9]);
        });
      marker(m.center,'<span>'+measure.formatArea(m.area)+'</span>','parcel-center-area',[170,24],[85,-8]);
      marker(m.center,'<svg viewBox="0 0 40 52" aria-hidden="true"><path d="M20 50C16 42 2 29 2 20a18 18 0 1 1 36 0c0 9-14 22-18 30Z" fill="#11755b" stroke="white" stroke-width="2.5"/><circle cx="20" cy="20" r="11" fill="white"/><path d="M13 25V15h7a4 4 0 0 1 0 8h-7m7 0 6 5" fill="none" stroke="#11755b" stroke-width="3"/></svg>','parcel-radar-pin',[36,48],[18,48],'planningParcelPin');
    }
    map.on('zoomend',render);
    return {show:function(feature){selected=metrics(feature);render();return selected;},clear:function(){selected=null;group.clearLayers();},
      dispose:function(){disposed=true;map.off('zoomend',render);map.removeLayer(group);}};
  }
  return {metrics:metrics,contains:contains,directions:directions,mount:mount};
});
