(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.RadarPlanningMeasure = api;
})(typeof window !== 'undefined' ? window : null, function () {
  'use strict';
  var R = 6371000, rad = Math.PI / 180;
  function valid(p) { return p && Number.isFinite(p.lat) && Number.isFinite(p.lng) && Math.abs(p.lat) <= 85.1 && Math.abs(p.lng) <= 180; }
  function distance(a, b) {
    var h = Math.sin((b.lat-a.lat)*rad/2)**2 + Math.cos(a.lat*rad)*Math.cos(b.lat*rad)*Math.sin((b.lng-a.lng)*rad/2)**2;
    return 2*R*Math.asin(Math.sqrt(Math.min(1, Math.max(0,h))));
  }
  function area(points) {
    if (points.length < 3 || !points.every(valid)) return 0;
    var sum = 0, base = Math.sin(points[0].lat*rad);
    points.forEach(function (a, i) {
      var b = points[(i+1)%points.length];
      // Subtract a common latitude term to retain precision for small parcels.
      sum += (b.lng-a.lng)*rad*(Math.sin(a.lat*rad)+Math.sin(b.lat*rad)-2*base);
    });
    return Math.abs(sum)*R*R/2;
  }
  function cross(a,b,c) { return (b.lng-a.lng)*(c.lat-a.lat)-(b.lat-a.lat)*(c.lng-a.lng); }
  function onSegment(a,b,p) {
    return Math.abs(cross(a,b,p)) < 1e-14 && p.lng >= Math.min(a.lng,b.lng)-1e-12 && p.lng <= Math.max(a.lng,b.lng)+1e-12
      && p.lat >= Math.min(a.lat,b.lat)-1e-12 && p.lat <= Math.max(a.lat,b.lat)+1e-12;
  }
  function intersects(a,b,c,d) {
    return (cross(a,b,c)*cross(a,b,d)<0 && cross(c,d,a)*cross(c,d,b)<0)
      || onSegment(a,b,c) || onSegment(a,b,d) || onSegment(c,d,a) || onSegment(c,d,b);
  }
  function canAdd(points, p) {
    if (!valid(p) || points.length >= 100 || points.some(function (q) { return distance(q,p)<0.1; })) return false;
    if (points.length < 2) return true;
    var last = points[points.length-1], previous = points[points.length-2];
    if (Math.abs(cross(previous,last,p))<1e-14 && (previous.lng-last.lng)*(p.lng-last.lng)+(previous.lat-last.lat)*(p.lat-last.lat)>0) return false;
    for (var i=0;i<points.length-2;i++) if (intersects(points[i],points[i+1],last,p)) return false;
    return true;
  }
  function validPolygon(points) {
    if (points.length<3 || !points.every(valid) || area(points)<0.01) return false;
    for (var i=0;i<points.length;i++) {
      var next=(i+1)%points.length;
      if (distance(points[i],points[next])<0.1) return false;
      for (var j=i+1;j<points.length;j++) {
        if (j===next || (j+1)%points.length===i) continue;
        if (intersects(points[i],points[next],points[j],points[(j+1)%points.length])) return false;
      }
    }
    return true;
  }
  function number(value) { return value.toLocaleString('vi-VN',{maximumFractionDigits:2}); }
  function formatDistance(value) { return value>=1000 ? number(value/1000)+' km' : number(value)+' m'; }
  function formatArea(value) { return number(value)+' m²'+(value>=10000 ? ' · '+number(value/10000)+' ha' : ''); }

  function mount(map, L, env, ui, actions) {
    var doc=env.document, container=map.getContainer(), points=[], active=false, closed=false, disposed=false;
    var previewPoint, frame, restoreDoubleClick=false;
    var drawingPane=map.createPane('planningDrawing'); drawingPane.style.zIndex='630';
    var labelPane=map.createPane('planningMeasureLabels'); labelPane.style.zIndex='660'; labelPane.style.pointerEvents='none';
    var renderer=L.svg({pane:'planningDrawing'}), drawing=L.layerGroup().addTo(map);
    function node(tag,parent,text) { var n=doc.createElement(tag); if(text) n.textContent=text; parent.appendChild(n); return n; }
    function button(parent,text,label) { var b=node('button',parent,text); b.type='button'; b.setAttribute('aria-label',label); return b; }
    var draw=button(actions,'✎ Vẽ ranh','Vẽ ranh đo khoảng cách và diện tích'); draw.setAttribute('aria-pressed','false');
    var clear=button(actions,'⌫ Xóa ranh','Xóa ranh đã vẽ'); clear.disabled=true;
    var result=node('section',ui.root); result.className='planning-measure-result'; result.hidden=true;
    result.setAttribute('aria-label','Kết quả đo ranh');
    var output=node('div',result); output.setAttribute('role','status'); output.setAttribute('aria-live','polite');
    var resultActions=node('div',result); resultActions.className='planning-measure-result-actions';
    var undo=button(resultActions,'Lùi điểm','Xóa điểm vừa vẽ');
    var finish=button(resultActions,'Khép ranh','Khép ranh và tính diện tích');
    var close=button(resultActions,'×','Ẩn kết quả đo');
    var note=node('p',result,'Số đo xấp xỉ theo bản đồ.');
    var preview=L.polyline([],{pane:'planningDrawing',renderer:renderer,color:'#08765b',weight:2,dashArray:'5 5',interactive:false}).addTo(map);
    var previewLabel=L.tooltip({pane:'planningMeasureLabels',permanent:true,direction:'center',className:'planning-measure-label'});
    function label(at,text,className) {
      return L.tooltip({pane:'planningMeasureLabels',permanent:true,direction:'center',className:className||'planning-measure-label'})
        .setLatLng(at).setContent(doc.createTextNode(text));
    }
    function updatePreview() {
      frame=null;
      if (!active || !previewPoint || !points.length || disposed) return;
      var a=points[points.length-1], b=previewPoint;
      preview.setLatLngs([a,b]);
      previewLabel.setLatLng([(a.lat+b.lat)/2,(a.lng+b.lng)/2]).setContent(doc.createTextNode(formatDistance(distance(a,b))));
      if (!map.hasLayer(previewLabel)) previewLabel.addTo(map);
    }
    function clearPreview() {
      if (frame) env.cancelAnimationFrame(frame); frame=null; previewPoint=null;
      preview.setLatLngs([]); if(map.hasLayer(previewLabel)) map.removeLayer(previewLabel);
    }
    function setActive(value) {
      if (active===value) return;
      active=value; container.classList.toggle('planning-is-drawing',active);
      draw.setAttribute('aria-pressed',String(active)); draw.textContent=active?'Dừng vẽ':'✎ Vẽ ranh';
      if(active) {
        restoreDoubleClick=map.doubleClickZoom.enabled(); map.doubleClickZoom.disable();
        map.fire('planning:drawing-start');
        ui.panels.forEach(function(p){p.open=false;}); container.focus({preventScroll:true});
      } else {
        clearPreview(); if(restoreDoubleClick) map.doubleClickZoom.enable();
      }
    }
    function redraw(message) {
      clearPreview(); drawing.clearLayers();
      clear.disabled=!points.length; undo.disabled=!points.length; finish.disabled=points.length<3;
      result.hidden=!active && !points.length; undo.hidden=finish.hidden=!active; close.hidden=active;
      if(points.length) {
        var opts={pane:'planningDrawing',renderer:renderer,color:'#08765b',weight:2.5,fillOpacity:.08,interactive:false};
        (closed?L.polygon(points,opts):L.polyline(points,opts)).addTo(drawing);
        var total=0, count=closed?points.length:points.length-1;
        for(var i=0;i<count;i++) {
          var a=points[i], b=points[(i+1)%points.length], length=distance(a,b); total+=length;
          label([(a.lat+b.lat)/2,(a.lng+b.lng)/2],formatDistance(length)).addTo(drawing);
        }
        points.forEach(function(p,i){
          var vertex=L.circleMarker(p,{pane:'planningDrawing',renderer:renderer,radius:i===0&&active?10:5,weight:2,
            color:'#08765b',fillColor:'#fff',fillOpacity:1,interactive:i===0&&active,bubblingMouseEvents:false}).addTo(drawing);
          if(i===0&&active) vertex.on('click',function(event){L.DomEvent.stopPropagation(event);complete();});
        });
        if(closed) {
          label(L.polygon(points).getBounds().getCenter(),formatArea(area(points)),'planning-measure-label planning-measure-area').addTo(drawing);
          output.textContent='Diện tích '+formatArea(area(points))+' · Chu vi '+formatDistance(total);
        } else output.textContent=points.length+' điểm · Tổng chiều dài '+formatDistance(total);
      } else output.textContent='Bấm lên bản đồ để đặt điểm đầu tiên.';
      if(message) note.textContent=message;
      else note.textContent=active?'Bấm điểm đầu hoặc Khép ranh để hoàn tất. Enter: đặt điểm giữa; Esc: dừng.':'Số đo xấp xỉ theo bản đồ.';
    }
    function add(p) {
      if(!active || disposed) return;
      if(points.length>=100) { note.textContent='Tối đa 100 điểm cho một ranh. Hãy khép ranh hoặc lùi điểm.'; return; }
      if(!canAdd(points,p)) { note.textContent='Điểm mới bị trùng hoặc làm các cạnh giao nhau. Hãy chọn vị trí khác.'; return; }
      points.push({lat:p.lat,lng:p.lng}); redraw();
    }
    function click(event) { if(active) add(event.latlng); }
    function move(event) {
      if(!active || !points.length) return;
      previewPoint=event.latlng; if(!frame) frame=env.requestAnimationFrame(updatePreview);
    }
    function complete() {
      if(!active || points.length<3) { note.textContent='Cần ít nhất 3 điểm để khép ranh.'; return; }
      if(!validPolygon(points)) { note.textContent='Ranh chưa hợp lệ: các cạnh giao nhau hoặc diện tích bằng 0. Hãy lùi điểm để sửa.'; return; }
      closed=true; setActive(false); redraw(); draw.focus({preventScroll:true});
    }
    function keydown(event) {
      if(!active) return;
      if(event.key==='Enter'&&event.target===container) { event.preventDefault(); event.stopPropagation(); add(map.getCenter()); }
      if(event.key==='Escape') { event.preventDefault(); event.stopPropagation(); setActive(false); redraw(); draw.focus({preventScroll:true}); }
    }
    function pause() { if(active) { setActive(false);redraw(); } }
    function panelChanged() { if(ui.panels.some(function(p){return p.open;})) pause(); }
    draw.addEventListener('click',function(){
      if(closed) { points=[]; closed=false; }
      setActive(!active); redraw();
    });
    clear.addEventListener('click',function(){setActive(false);points=[];closed=false;redraw();draw.focus({preventScroll:true});});
    undo.addEventListener('click',function(){points.pop();redraw();});
    finish.addEventListener('click',complete);
    close.addEventListener('click',function(){result.hidden=true;});
    container.addEventListener('keydown',keydown);
    ui.root.addEventListener('keydown',keydown);
    ui.panels.forEach(function(p){p.addEventListener('toggle',panelChanged);});
    map.on('click',click); map.on('mousemove',move); map.on('movestart',clearPreview);map.on('planning:panel-open',pause);
    return function(){
      if(disposed) return; disposed=true; setActive(false);clearPreview();
      map.off('click',click);map.off('mousemove',move);map.off('movestart',clearPreview);
      map.off('planning:panel-open',pause);ui.panels.forEach(function(p){p.removeEventListener('toggle',panelChanged);});
      container.removeEventListener('keydown',keydown);
      ui.root.removeEventListener('keydown',keydown);
      map.removeLayer(drawing);map.removeLayer(preview);renderer.remove(); result.remove();draw.remove();clear.remove();
    };
  }
  return {distance:distance,area:area,canAdd:canAdd,validPolygon:validPolygon,formatDistance:formatDistance,formatArea:formatArea,mount:mount};
});
