(function(root,factory){var api=factory();if(typeof module==='object'&&module.exports)module.exports=api;if(root)root.RadarPlanningArea=api;})(typeof window!=='undefined'?window:null,function(){
  'use strict';
  function initial(provinces,region){
    if(!Array.isArray(provinces)||!provinces.length)return null;
    var requested=region==='dong-nai-expanded'?'dong-nai-legacy':region==='hcm-expanded'?'hcm-legacy':region;
    var province=provinces.find(function(p){return p.region_id===requested||(region==='con-dao'&&p.id==='brvt');})
      ||provinces.find(function(p){return p.id==='binh-duong';})||provinces[0];
    var district=region==='con-dao'?province.districts.find(function(d){return d.id==='con-dao';})
      :!region&&province.id==='binh-duong'?province.districts.find(function(d){return d.id==='718';}):null;
    return {province:province.id,district:district?district.id:'',region_id:province.region_id,
      bounds:district?district.bounds:province.bounds,max_zoom:district?13:11};
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
      onChange(p,{province:p.id,district:d?d.id:'',bounds:d?d.bounds:p.bounds,max_zoom:d?13:11});panel.open=false;});
    return panel;
  }
  return {initial:initial,mount:mount};
});
