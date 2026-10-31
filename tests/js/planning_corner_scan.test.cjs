const test=require('node:test'),assert=require('node:assert/strict');
const api=require('../../static/js/main/planning_corner_scan.js');
test('scan validates image and requires a reviewed, bounded draft',()=>{
 assert(api.validFile({type:'image/jpeg',size:1000}));assert(!api.validFile({type:'image/svg+xml',size:1000}));assert(!api.validFile({type:'image/png',size:12000001}));
 const text='1 2\n3 4\n5 6';assert(!api.canApply(text,false));assert(api.canApply(text,true));assert(!api.canApply('1 2',true));
 assert.deepEqual(api.normalizedCrop({x:.8,y:.7},{x:.2,y:.1}),{x:.2,y:.1,w:.6000000000000001,h:.6});
});
test('scanner only applies reviewed edits and discards late OCR after reset',async()=>{
 const nodes=[],requests=[],applied=[];let revoked=0;
 const doc={createElement(tag){const el={tag,children:[],events:{},value:'',checked:false,attributes:{},
 appendChild(x){this.children.push(x);},setAttribute(k,v){this.attributes[k]=v;},addEventListener(k,f){this.events[k]=f;},remove(){},
 getContext:()=>({drawImage(){},fillRect(){},strokeRect(){},translate(){},rotate(){}}),toBlob(f){f(new Blob(['image'],{type:'image/jpeg'}));}};nodes.push(el);return el;}};
 const env={document:doc,AbortController,URL:{createObjectURL:()=> 'blob:local',revokeObjectURL(){revoked++;}},
 Image:class{naturalWidth=400;naturalHeight=200;set src(v){queueMicrotask(()=>this.onload());}},
 setTimeout:()=>1,clearTimeout(){},fetch:(url,options)=>new Promise(resolve=>requests.push({url,options,resolve}))};
 const mounted=api.mount(env,doc.createElement('div'),{url:'/api/planning/parcels/corners/scan.json',system:()=> 'vn2000',onApply:text=>applied.push(text)});
 const field=label=>nodes.find(n=>n.attributes['aria-label']===label),button=text=>nodes.find(n=>n.tag==='button'&&n.textContent===text),flush=()=>new Promise(r=>setImmediate(r));
 const file=field('Ảnh bảng tọa độ');file.files=[{type:'image/png',size:123}];file.events.change();await flush();assert.equal(revoked,1);assert.equal(button('Đọc vùng đã chọn').disabled,true);button('Toàn bộ ảnh').events.click();
 const work=button('Đọc vùng đã chọn').events.click();await flush();assert.equal(requests.length,1);assert(requests[0].options.body instanceof Blob);
 requests[0].resolve({ok:true,json:async()=>({text:'1218730 594520\n1218730 594550\n1218760 594550',count:3,warnings:[]})});await work;
 const apply=button('Áp dụng số đã kiểm tra');assert.equal(apply.disabled,true);apply.events.click();assert.equal(applied.length,0);
 field('Tôi đã đối chiếu toàn bộ tọa độ với ảnh').checked=true;field('Tôi đã đối chiếu toàn bộ tọa độ với ảnh').events.change();assert.equal(apply.disabled,false);apply.events.click();assert.equal(applied.length,1);
 const again=button('Đọc vùng đã chọn').events.click();await flush();mounted.reset();assert(requests[1].options.signal.aborted);
 requests[1].resolve({ok:true,json:async()=>({text:'LATE',count:3,warnings:[]})});await again;
 assert.equal(field('Tọa độ đọc từ ảnh').value,'');mounted.dispose();
});
