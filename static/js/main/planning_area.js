(function(root,factory){var api=factory();if(typeof module==='object'&&module.exports)module.exports=api;if(root)root.RadarPlanningArea=api;})(typeof window!=='undefined'?window:null,function(){
  'use strict';
  function coversProvince(item,province){
    if(!province)return true;
    if(item.theme==='land_use_2030')return (province.layer_ids||[]).indexOf(item.id)>=0;
    if(Array.isArray(item.coverage_provinces))return item.coverage_provinces.indexOf(province.id)>=0;
    var hcm=['binh-duong','hcm','brvt'];
    if(item.area_id==='hcm-expanded')return hcm.indexOf(province.id)>=0;
    if(item.area_id==='hcm-legacy')return province.id==='hcm'||item.theme==='transport'&&hcm.indexOf(province.id)>=0;
    if(item.area_id===province.region_id||item.area_id===province.id+'-legacy')return true;
    return province.id==='binh-duong'&&['Bến Cát','Thủ Dầu Một','Thuận An','Dĩ An','Tân Uyên','Bàu Bàng','Dầu Tiếng','Phú Giáo','Bắc Tân Uyên'].indexOf(item.city)>=0;
  }
  function initial(provinces,region){
    if(!Array.isArray(provinces)||!provinces.length)return null;
    var requested=region==='dong-nai-expanded'?'dong-nai-legacy':region==='hcm-expanded'?'hcm-legacy':region;
    var province=provinces.find(function(p){return p.region_id===requested||(region==='con-dao'&&p.id==='brvt');})
      ||provinces.find(function(p){return p.id==='binh-duong';})||provinces[0];
    var district=region==='con-dao'?province.districts.find(function(d){return d.id==='con-dao';})
      :!region&&province.id==='binh-duong'?province.districts.find(function(d){return d.id==='718';}):null;
    return {province:province.id,district:district?district.id:'',region_id:province.region_id,
      bounds:district?district.bounds:(province.focus_bounds||province.bounds),max_zoom:13,min_zoom:province.min_zoom||8};
  }
  function focus(map,L,area){
    if(area.district && (area.min_zoom||8)<=8){map.fitBounds(area.bounds,{maxZoom:area.max_zoom,padding:[24,24],animate:false});return;}
    var bounds=L.latLngBounds(area.bounds);
    // Fill the screen with the province centre instead of fitting every outer edge.
    var zoom=area.district?map.getBoundsZoom(bounds,false,[24,24])
      :Math.max(map.getBoundsZoom(bounds,true,[0,0]),map.getBoundsZoom(bounds,false,[0,0])+1);
    zoom=Math.min(13,Math.max(area.min_zoom||8,zoom));
    map.setView(bounds.getCenter(),zoom,{animate:false});
  }
  function mount(env,ui,provinces,selection,onChange){
    var doc=env.document;
    function node(tag,parent,text){var e=doc.createElement(tag);if(text)e.textContent=text;if(parent)parent.appendChild(e);return e;}
    var panel=node('details',ui.areaSlot);panel.className='planning-map-popover planning-area-menu';
    node('summary',panel,'Khu vực');ui.panels.push(panel);
    panel.addEventListener('toggle',function(){if(panel.open)ui.panels.forEach(function(p){if(p!==panel)p.open=false;});});
    var form=node('form',panel);form.className='planning-map-form';
    node('h3',form,'Khu vực quy hoạch · địa danh cũ');
    function field(title){var label=node('label',form,title),e=node('select',label);e.setAttribute('aria-label',title);return e;}
    var province=field('Tỉnh/TP (Cũ)'),district=field('Quận/Huyện (Cũ)');
    provinces.forEach(function(p){node('option',province,p.name).value=p.id;});province.value=selection.province;
    function selected(){return provinces.find(function(p){return p.id===province.value;});}
    function fillDistricts(value){district.replaceChildren();node('option',district,'Toàn tỉnh/thành phố').value='';
      selected().districts.forEach(function(d){node('option',district,d.name).value=d.id;});district.value=value||'';}
    fillDistricts(selection.district);
    province.addEventListener('change',function(){fillDistricts();});
    var submit=node('button',form,'Xem khu vực');submit.type='submit';
    node('p',form,'QH SDĐ 2030 chỉ tải tỉnh đang chọn. Khung nhìn huyện là tham khảo; bộ lọc tin rao được giữ riêng.');
    var source=node('a',form,'Khung huyện: GIS TP.HCM · geoBoundaries / OCHA ROAP · CC BY 3.0 IGO');
    source.href='https://www.geoboundaries.org/api/current/gbOpen/VNM/ADM2/';source.target='_blank';source.rel='noopener noreferrer';
    form.addEventListener('submit',function(e){e.preventDefault();var p=selected(),d=p.districts.find(function(item){return item.id===district.value;});
      onChange(p,{province:p.id,district:d?d.id:'',bounds:d?d.bounds:(p.focus_bounds||p.bounds),max_zoom:13,min_zoom:p.min_zoom||8});panel.open=false;});
    return panel;
  }
  return {initial:initial,mount:mount,focus:focus,coversProvince:coversProvince};
});
