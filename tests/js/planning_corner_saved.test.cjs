const test=require('node:test'),assert=require('node:assert/strict');
const api=require('../../static/js/main/planning_corner_saved.js');
const row={name:'Lô A',system:'vn2000',crs:'tm3-10815',corners:'1 2\n3 4\n5 6'};
test('saved outlines reject corrupt and oversized storage',()=>{
 assert.deepEqual(api.read({getItem:()=>'{bad'}),[]);
 assert.deepEqual(api.read({getItem:()=>JSON.stringify(Array(21).fill(row))}),[]);
 assert.deepEqual(api.read({getItem:()=>JSON.stringify([row])}),[row]);
 assert.deepEqual(api.read({getItem(){throw Error('denied');}}),[]);
});
test('save requires validated input and reopening preserves coordinates and projection',()=>{
 const nodes=[],opened=[];let raw=null,validated=null;
 const doc={createElement(tag){const el={tag,value:'',children:[],events:{},attributes:{},appendChild(x){this.children.push(x);},replaceChildren(){this.children=[];},setAttribute(k,v){this.attributes[k]=v;},addEventListener(k,f){this.events[k]=f;}};nodes.push(el);return el;}};
 const storage={getItem:()=>raw,setItem(k,v){raw=v;}};
 api.mount({document:doc,localStorage:storage},doc.createElement('div'),{validated:()=>validated,open:r=>opened.push(r)});
 const button=t=>nodes.find(n=>n.tag==='button'&&n.textContent===t);
 const name=nodes.find(n=>n.attributes['aria-label']==='Tên ranh lưu');name.value=row.name;
 button('Lưu ranh đã kiểm tra').events.click();assert.equal(raw,null);
 validated={system:row.system,crs:row.crs,corners:row.corners};button('Lưu ranh đã kiểm tra').events.click();
 assert.equal(api.read(storage).length,1);
 const list=nodes.find(n=>n.attributes['aria-label']==='Ranh đã lưu');list.value='0';button('Mở ranh đã lưu').events.click();
 assert.deepEqual(opened,[row]);list.value='0';button('Xóa bản lưu').events.click();assert.deepEqual(api.read(storage),[]);
});
