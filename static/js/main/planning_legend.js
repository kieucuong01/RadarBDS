(function (root, factory) {
  var api=factory();
  if(typeof module==='object'&&module.exports) module.exports=api;
  if(root) root.RadarPlanningLegend=api;
})(typeof window!=='undefined'?window:null,function(){
  'use strict';
  var services={partition:['SuDungDat_QHPK_HCM_V2','QHXD_SDD_2025_QHPK_V3'],
    urban_general:['SuDungDat_QHC_HCM','QHXD_SDD_2025_QHCDT'],detailed:['SuDungDat_QHCT_HCM','QHXD_SDD_2025_QHCT']};
  function valid(data) {
    return data && typeof data.captured_at==='string' && Number.isFinite(Date.parse(data.captured_at)) && Array.isArray(data.groups) && data.groups.length>0 && data.groups.length<=12
      && data.groups.every(function(g){
        if(!g||typeof g.source_url!=='string') return false;
        var source=g.source_url.match(/^https:\/\/api-gisxaydung\.tphcm\.gov\.vn\/arcgis\/rest\/services\/HCM\/([A-Za-z0-9_]+)\/MapServer\/[012]$/);
        return ['land_codes','partition','urban_general','detailed'].indexOf(g.theme)>=0 && typeof g.title==='string' && g.title.length<=100
          && (g.theme==='land_codes' ? g.source_url==='https://congbaocdn.chinhphu.vn/CongBaoCP/VanBan/2024/7/42595/51505-1-2024991-99208-2024-tt-btnmt.pdf#page=81'
            : source && services[g.theme].indexOf(source[1])>=0)
          && Array.isArray(g.rows) && g.rows.length<=200 && g.rows.every(function(r){
            return r && typeof r.code==='string' && r.code.length<=100 && typeof r.label==='string' && r.label.length<=160
              && typeof r.image==='string' && r.image.length<=8192 && /^data:image\/png;base64,iVBORw0KGgo[A-Za-z0-9+/=]+$/.test(r.image);
          });
      });
  }
  function normalize(text) { return text.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/đ/g,'d'); }
  function mount(map,L,env,ui,actions,context) {
    var doc=env.document, data, pending=false, disposed=false, controller=new env.AbortController();
    function node(tag,parent,text) {var n=doc.createElement(tag);if(text) n.textContent=text;if(parent) parent.appendChild(n);return n;}
    var button=node('button',actions,'▦ Ký hiệu đất');button.type='button';button.setAttribute('aria-label','Bảng ký hiệu các loại đất');
    button.setAttribute('aria-expanded','false');button.setAttribute('aria-controls','planningLandLegend');
    var panel=node('section',ui.root);panel.id='planningLandLegend';panel.className='planning-land-legend';panel.hidden=true;
    panel.setAttribute('role','dialog');panel.setAttribute('aria-label','Bảng ký hiệu các loại đất');
    var header=node('div',panel);header.className='planning-legend-heading';node('h3',header,'Ký hiệu các loại đất');
    var close=node('button',header,'×');close.type='button';close.setAttribute('aria-label','Đóng bảng ký hiệu');
    var type=node('select',panel);type.setAttribute('aria-label','Lớp bản đồ trong bảng ký hiệu');
    [['land_codes','Mã đất thông dụng · ONT/ODT/CLN'],['partition','Quy hoạch phân khu'],['urban_general','Quy hoạch chung đô thị'],['detailed','Quy hoạch chi tiết'],['all','Tất cả ký hiệu']]
      .forEach(function(option){node('option',type,option[1]).value=option[0];});
    var documentOptions=[];
    var search=node('input',panel);search.type='search';search.placeholder='Tìm mã hoặc loại đất…';search.maxLength=100;
    search.setAttribute('aria-label','Tìm ký hiệu hoặc loại đất');
    var notice=node('p',panel);notice.className='planning-legend-note';
    var status=node('p',panel);status.setAttribute('role','status');status.setAttribute('aria-live','polite');
    var retry=node('button',panel,'Thử tải lại');retry.type='button';retry.hidden=true;
    var body=node('div',panel);body.className='planning-legend-tables';
    function render() {
      body.replaceChildren();
      var current=context(), documentId=type.value.indexOf('doc:')===0?type.value.slice(4):null;
      search.disabled=Boolean(documentId);retry.hidden=true;
      if(documentId) {
        var item=(current.documents||[]).find(function(x){return x.id===documentId;});
        if(!item) {status.textContent='Chưa có chú giải bản vẽ này.';return;}
        notice.textContent='Chú giải nguyên bản của hồ sơ đã chọn.';status.textContent=item.name;
        var img=node('img',body);img.className='planning-document-legend';img.alt='Chú giải bản vẽ '+item.name;
        img.src=current.assetBase+item.id+'/legend.webp';
        var link=node('a',body,'Mở hồ sơ gốc');link.href=item.source_url;link.target='_blank';link.rel='noopener noreferrer';
        return;
      }
      notice.textContent=(current.source==='document'?'Đang chọn bản vẽ/PDF; bảng dưới là ký hiệu GIS. ':'')
        +'Mẫu màu và gạch/sọc lấy từ GIS. Cùng mã có thể có màu khác giữa các nguồn; màu trên bản đồ thay đổi theo độ hiển thị.';
      if(type.value==='land_codes') notice.textContent='Mã và màu tham chiếu theo bảng hiện trạng sử dụng đất TT 08/2024. Với từng đồ án, hãy đối chiếu chú giải riêng của lớp GIS hoặc bản vẽ.';
      if(!data) {status.textContent=pending?'Đang tải bảng ký hiệu…':'Chưa tải được bảng ký hiệu.';retry.hidden=pending;return;}
      var query=normalize((search.value||'').trim()),count=0;
      data.groups.filter(function(g){return type.value==='all'||g.theme===type.value;}).forEach(function(g){
        var rows=g.rows.filter(function(r){return normalize(r.code+' '+r.label).includes(query);});
        if(!rows.length) return;count+=rows.length;
        node('h4',body,g.title);
        var table=node('table',body);var head=node('tr',node('thead',table));
        ['Ký hiệu','Mẫu','Loại đất'].forEach(function(text){var th=node('th',head,text);th.scope='col';});
        var tbody=node('tbody',table);
        rows.forEach(function(r){
          var tr=node('tr',tbody);node('td',tr,r.code);
          var swatch=node('img',node('td',tr));swatch.alt='';swatch.width=swatch.height=28;swatch.src=r.image;
          node('td',tr,r.label);
        });
        var source=node('a',body,g.theme==='land_codes'?'Nguồn bảng mã · Công báo':'Mở cổng GIS nguồn');
        source.href=g.theme==='land_codes'?g.source_url:'https://gisxaydung.tphcm.gov.vn/tracuuttqh';source.target='_blank';source.rel='noopener noreferrer';
      });
      status.textContent=count?count+' ký hiệu · '+new Date(data.captured_at).toLocaleDateString('vi-VN',{timeZone:'Asia/Ho_Chi_Minh'}):'Không tìm thấy ký hiệu phù hợp.';
    }
    function load() {
      if(data||pending||disposed) return;pending=true;render();
      env.fetch('/static/data/planning_symbols.json?v=planning-tools-20261029',{signal:controller.signal}).then(function(r){if(!r.ok) throw new Error('Symbols unavailable');return r.json();})
        .then(function(value){if(!disposed){if(!valid(value)) throw new Error('Invalid symbols');data=value;}})
        .catch(function(error){if(error.name!=='AbortError'&&!disposed) data=null;})
        .finally(function(){pending=false;if(!disposed&&!panel.hidden) render();});
    }
    function hide(focus) {panel.hidden=true;button.setAttribute('aria-expanded','false');if(focus) button.focus({preventScroll:true});}
    button.addEventListener('click',function(){
      if(!panel.hidden) {hide(false);return;}
      map.fire('planning:panel-open');
      ui.panels.forEach(function(p){p.open=false;});
      documentOptions.forEach(function(o){o.remove();});documentOptions=[];
      var current=context();(current.documents||[]).forEach(function(item){var o=node('option',type,'Bản vẽ · '+item.name);o.value='doc:'+item.id;documentOptions.push(o);});
      type.value=current.active&&['partition','urban_general','detailed'].indexOf(current.theme)>=0?current.theme:'land_codes';
      if(current.source==='document'&&current.selectedDocument) type.value='doc:'+current.selectedDocument;
      search.value='';panel.hidden=false;button.setAttribute('aria-expanded','true');render();load();search.focus({preventScroll:true});
    });
    close.addEventListener('click',function(){hide(true);});retry.addEventListener('click',load);
    type.addEventListener('change',render);search.addEventListener('input',render);
    panel.addEventListener('keydown',function(event){if(event.key==='Escape'){event.preventDefault();event.stopPropagation();hide(true);}});
    function outside(event){if(!panel.hidden&&!panel.contains(event.target)&&!button.contains(event.target)) hide(false);}
    doc.addEventListener('pointerdown',outside);
    return function(){disposed=true;controller.abort();doc.removeEventListener('pointerdown',outside);panel.remove();button.remove();};
  }
  return {mount:mount,valid:valid,normalize:normalize};
});
