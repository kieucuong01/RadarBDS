(function(root,factory){var api=factory();if(typeof module==='object'&&module.exports)module.exports=api;if(root)root.RadarCornerSaved=api;})(typeof window!=='undefined'?window:null,function(){
  'use strict';
  var key='radar.saved-corners.v1';
  function valid(row){return row&&typeof row.name==='string'&&row.name.trim().length>0&&row.name.length<=80
    &&['wgs84','vn2000'].includes(row.system)&&typeof row.crs==='string'&&row.crs.length<=30
    &&typeof row.corners==='string'&&row.corners.length<=12000&&row.corners.split(/\r?\n/).filter(function(s){return s.trim();}).length>=3
    &&row.corners.split(/\r?\n/).filter(function(s){return s.trim();}).length<=101;}
  function read(storage){try{var raw=storage.getItem(key);if(!raw)return [];if(raw.length>300000)return [];
    var rows=JSON.parse(raw);return Array.isArray(rows)&&rows.length<=20&&rows.every(valid)?rows:[];}catch(_){return [];}}
  function mount(env,host,options){
    var doc=env.document;
    function node(tag,text){var el=doc.createElement(tag);if(text)el.textContent=text;host.appendChild(el);return el;}
    node('p','Lưu tối đa 20 ranh trên trình duyệt này. Xóa dữ liệu trình duyệt sẽ mất bản lưu; không đồng bộ tài khoản.');
    var name=node('input');name.type='text';name.maxLength=80;name.placeholder='Tên ranh, ví dụ Lô đất Tân An';name.setAttribute('aria-label','Tên ranh lưu');
    var save=node('button','Lưu ranh đã kiểm tra');save.type='button';
    var list=node('select');list.setAttribute('aria-label','Ranh đã lưu');
    var open=node('button','Mở ranh đã lưu'),remove=node('button','Xóa bản lưu');open.type=remove.type='button';
    var status=node('p');status.setAttribute('role','status');
    function storage(){try{return env.localStorage;}catch(_){return null;}}
    function render(){list.replaceChildren();var first=doc.createElement('option');first.textContent='Chọn ranh đã lưu';first.value='';list.appendChild(first);
      read(storage()).forEach(function(row,i){var el=doc.createElement('option');el.textContent=row.name;el.value=String(i);list.appendChild(el);});}
    function persist(rows){try{storage().setItem(key,JSON.stringify(rows));render();return true;}catch(_){status.textContent='Không lưu được. Trình duyệt có thể chặn lưu trữ hoặc đã hết dung lượng.';return false;}}
    save.addEventListener('click',function(){var data=options.validated();if(!data){status.textContent='Bấm Xem ranh từ tọa độ để kiểm tra trước khi lưu; nếu sửa số cần kiểm tra lại.';return;}
      var row=Object.assign({},data,{name:name.value.trim()});if(!valid(row)){status.textContent='Nhập tên ranh, tối đa 80 ký tự.';return;}
      var rows=read(storage());if(rows.length>=20){status.textContent='Đã đủ 20 ranh. Xóa bớt bản lưu trước khi thêm.';return;}
      rows.push(row);if(persist(rows))status.textContent='Đã lưu ranh trên trình duyệt này.';});
    open.addEventListener('click',function(){var rows=read(storage()),row=list.value===''?null:rows[Number(list.value)];if(!valid(row)){status.textContent='Chọn một ranh để mở.';return;}name.value=row.name;options.open(row);});
    remove.addEventListener('click',function(){var rows=read(storage());if(list.value===''||!rows[Number(list.value)])return;rows.splice(Number(list.value),1);if(persist(rows))status.textContent='Đã xóa bản lưu; ranh đang xem vẫn giữ nguyên.';});
    try{render();}catch(_){status.textContent='Trình duyệt không cho phép lưu ranh.';}
  }
  return {valid:valid,read:read,mount:mount};
});
