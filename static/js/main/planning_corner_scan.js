(function(root,factory){var api=factory();if(typeof module==='object'&&module.exports)module.exports=api;if(root)root.RadarCornerScan=api;})(typeof window!=='undefined'?window:null,function(){
  'use strict';
  function validFile(file){return Boolean(file&&['image/jpeg','image/png','image/webp'].includes(file.type)&&file.size>0&&file.size<=12000000);}
  function normalizedCrop(a,b){return {x:Math.max(0,Math.min(a.x,b.x)),y:Math.max(0,Math.min(a.y,b.y)),w:Math.min(1,Math.abs(b.x-a.x)),h:Math.min(1,Math.abs(b.y-a.y))};}
  function canApply(text,reviewed){var rows=String(text||'').trim().split(/\r?\n/).filter(function(s){return s.trim();});return Boolean(reviewed&&rows.length>=3&&rows.length<=100&&text.length<=12000);}
  function mount(env,host,options){
    var doc=env.document,disposed=false,sequence=0,controller=null,imageURL=null,raster=null,crop={x:0,y:0,w:1,h:1},start=null,running=false,cropReady=false;
    function node(tag,parent,text){var el=doc.createElement(tag);if(text)el.textContent=text;if(parent)parent.appendChild(el);return el;}
    var panel=node('details',host);panel.className='planning-corner-scan';node('summary',panel,'Đọc góc ranh từ ảnh');
    node('p',panel,'Chọn ảnh rồi kéo khoanh sát bảng tọa độ. Chỉ vùng đã cắt được gửi tới RadarBDS để đọc; không lưu ảnh và không gửi dịch vụ bên ngoài.');
    node('p',panel,'Nếu bảng X/Y theo VN-2000, chọn VN-2000 ở trên trước khi đọc.');
    var fileLabel=node('label',panel,'Ảnh bảng tọa độ'),file=node('input',fileLabel);file.type='file';file.accept='image/jpeg,image/png,image/webp';file.setAttribute('aria-label','Ảnh bảng tọa độ');
    var canvas=node('canvas',panel);canvas.hidden=true;canvas.setAttribute('aria-label','Kéo khoanh vùng bảng tọa độ');
    var tools=node('div',panel);tools.className='planning-corner-scan-actions';
    function button(text,parent){var el=node('button',parent||tools,text);el.type='button';return el;}
    var rotate=button('Xoay 90°'),all=button('Toàn bộ ảnh'),scan=button('Đọc vùng đã chọn'),cancel=button('Hủy đọc');cancel.hidden=true;
    var progress=node('progress',panel);progress.hidden=true;progress.setAttribute('aria-label','Đang đọc tọa độ từ ảnh');
    var status=node('p',panel);status.setAttribute('role','status');status.setAttribute('aria-live','polite');
    var review=node('div',panel);review.hidden=true;
    node('p',review,'OCR có thể đọc sai chữ số hoặc thiếu dòng. So từng góc với ảnh, sửa số và chọn đúng hệ chiếu VN-2000 trước khi vẽ.');
    var draftLabel=node('label',review,'Tọa độ đọc từ ảnh'),draft=node('textarea',draftLabel);draft.rows=6;draft.maxLength=12000;draft.setAttribute('aria-label','Tọa độ đọc từ ảnh');
    var confirmLabel=node('label',review);confirmLabel.className='planning-corner-review-confirm';var confirmed=node('input',confirmLabel);confirmed.type='checkbox';confirmed.setAttribute('aria-label','Tôi đã đối chiếu toàn bộ tọa độ với ảnh');node('span',confirmLabel,'Tôi đã đối chiếu toàn bộ tọa độ với ảnh');
    var apply=button('Áp dụng số đã kiểm tra',review);apply.disabled=true;
    function refresh(){scan.disabled=!raster||running||!cropReady;rotate.disabled=all.disabled=!raster||running;file.disabled=running;cancel.hidden=progress.hidden=!running;scan.setAttribute('aria-busy',String(running));apply.disabled=running||!canApply(draft.value,confirmed.checked);}
    function revoke(){if(imageURL){env.URL.revokeObjectURL(imageURL);imageURL=null;}}
    function abort(){++sequence;if(controller)controller.abort();controller=null;running=false;refresh();}
    function reset(){abort();revoke();raster=null;cropReady=false;file.value='';canvas.hidden=true;canvas.width=canvas.height=1;review.hidden=true;draft.value='';confirmed.checked=false;status.textContent='';refresh();}
    function invalidateDraft(){review.hidden=true;draft.value='';confirmed.checked=false;refresh();}
    panel.addEventListener('toggle',function(){if(!panel.open)reset();});
    function render(){if(!raster)return;canvas.width=raster.width;canvas.height=raster.height;var ctx=canvas.getContext('2d');ctx.drawImage(raster,0,0);var x=crop.x*canvas.width,y=crop.y*canvas.height,w=crop.w*canvas.width,h=crop.h*canvas.height;ctx.fillStyle='#102e2c55';ctx.fillRect(0,0,canvas.width,y);ctx.fillRect(0,y+h,canvas.width,canvas.height-y-h);ctx.fillRect(0,y,x,h);ctx.fillRect(x+w,y,canvas.width-x-w,h);ctx.strokeStyle='#08765b';ctx.lineWidth=Math.max(3,canvas.width/250);ctx.strokeRect(x,y,w,h);}
    file.addEventListener('change',function(){
      abort();revoke();review.hidden=true;confirmed.checked=false;draft.value='';raster=null;cropReady=false;canvas.hidden=true;
      var selected=file.files&&file.files[0];if(!validFile(selected)){status.textContent='Dùng JPG, PNG hoặc WebP, tối đa 12 MB.';refresh();return;}
      var seq=sequence,img=new env.Image();imageURL=env.URL.createObjectURL(selected);
      img.onload=function(){if(disposed||seq!==sequence)return;revoke();if(img.naturalWidth*img.naturalHeight>24000000){status.textContent='Ảnh quá lớn. Hãy chụp riêng bảng tọa độ.';refresh();return;}
        raster=doc.createElement('canvas');var scale=Math.min(1,2200/Math.max(img.naturalWidth,img.naturalHeight));raster.width=Math.round(img.naturalWidth*scale);raster.height=Math.round(img.naturalHeight*scale);raster.getContext('2d').drawImage(img,0,0,raster.width,raster.height);crop={x:0,y:0,w:1,h:1};canvas.hidden=false;render();status.textContent='Kéo khoanh sát bảng tọa độ, xoay cho ngay rồi bấm Đọc vùng đã chọn.';refresh();};
      img.onerror=function(){if(seq===sequence){revoke();status.textContent='Không mở được ảnh. Chọn ảnh JPG, PNG hoặc WebP khác.';refresh();}};img.src=imageURL;
    });
    function position(event){var b=canvas.getBoundingClientRect();return {x:Math.max(0,Math.min(1,(event.clientX-b.left)/b.width)),y:Math.max(0,Math.min(1,(event.clientY-b.top)/b.height))};}
    canvas.addEventListener('pointerdown',function(event){if(!raster||running)return;event.preventDefault();invalidateDraft();start=position(event);canvas.setPointerCapture(event.pointerId);});
    canvas.addEventListener('pointermove',function(event){if(!start)return;crop=normalizedCrop(start,position(event));render();});
    function end(){if(!start)return;start=null;cropReady=crop.w>=.02&&crop.h>=.02;if(!cropReady)crop={x:0,y:0,w:1,h:1};render();refresh();}
    canvas.addEventListener('pointerup',end);canvas.addEventListener('pointercancel',end);
    all.addEventListener('click',function(){invalidateDraft();cropReady=true;crop={x:0,y:0,w:1,h:1};render();refresh();});
    rotate.addEventListener('click',function(){if(!raster||running)return;invalidateDraft();cropReady=false;var next=doc.createElement('canvas');next.width=raster.height;next.height=raster.width;var ctx=next.getContext('2d');ctx.translate(next.width,0);ctx.rotate(Math.PI/2);ctx.drawImage(raster,0,0);raster=next;crop={x:0,y:0,w:1,h:1};render();refresh();});
    scan.addEventListener('click',async function(){
      if(!raster||running||!cropReady)return;abort();var seq=sequence;running=true;review.hidden=true;draft.value='';confirmed.checked=false;refresh();status.textContent='Đang đọc bảng tọa độ…';controller=new env.AbortController();var request=controller;
      var timeout=env.setTimeout(function(){request.abort();},30000);
      try{
        var selected=doc.createElement('canvas');selected.width=Math.max(1,Math.round(raster.width*crop.w));selected.height=Math.max(1,Math.round(raster.height*crop.h));selected.getContext('2d').drawImage(raster,raster.width*crop.x,raster.height*crop.y,raster.width*crop.w,raster.height*crop.h,0,0,selected.width,selected.height);
        var blob=await new Promise(function(resolve){selected.toBlob(resolve,'image/jpeg',.92);});selected.width=selected.height=1;
        if(disposed||seq!==sequence)return;if(!blob||blob.size>4000000)throw new Error('Vùng ảnh quá lớn. Hãy cắt sát bảng tọa độ hơn.');
        var response=await env.fetch(options.url+'?system='+encodeURIComponent(options.system()),{method:'POST',headers:{'Content-Type':'image/jpeg'},body:blob,signal:request.signal,cache:'no-store'});
        var data=await response.json();if(disposed||seq!==sequence)return;
        if(!response.ok)throw new Error(data.error||'Chưa đọc được ảnh. Vui lòng thử lại.');
        if(typeof data.text!=='string'||data.text.length>12000||!Array.isArray(data.warnings))throw new Error('Kết quả đọc ảnh không hợp lệ.');
        draft.value=data.text;review.hidden=false;status.textContent=data.text?'Đã đọc '+data.count+' góc. '+data.warnings.join(' '):'Chưa đọc được cặp tọa độ. Cắt sát bảng, kiểm tra hệ tọa độ hoặc nhập tay.';
      }catch(error){if(!disposed&&seq===sequence)status.textContent=error.name==='AbortError'?'Đọc ảnh bị hủy hoặc quá thời gian. Thử lại với vùng cắt nhỏ hơn.':error.message;}
      finally{env.clearTimeout(timeout);if(seq===sequence&&!disposed){running=false;controller=null;refresh();}}
    });
    cancel.addEventListener('click',function(){abort();status.textContent='Đã hủy đọc ảnh.';});
    confirmed.addEventListener('change',refresh);draft.addEventListener('input',function(){confirmed.checked=false;refresh();});
    apply.addEventListener('click',function(){if(!canApply(draft.value,confirmed.checked)||running)return;options.onApply(draft.value.trim());status.textContent='Đã đưa tọa độ vào Góc ranh. Kiểm tra hệ chiếu rồi bấm Xem ranh từ tọa độ.';});
    refresh();return {reset:reset,dispose:function(){disposed=true;reset();panel.remove();}};
  }
  return {mount:mount,validFile:validFile,normalizedCrop:normalizedCrop,canApply:canApply};
});
