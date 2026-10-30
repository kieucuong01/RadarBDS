const assert = require('node:assert/strict');
const api = require('../../static/js/main/planning_overlay.js');
const base = 'https://r4gmiynxmeobj.vcdn.cloud/';
const template = name => `${base}${name}-2030/{z}/{x}/{y}.png`;
for (const [name, count] of [['binh-duong',4],['tay-ninh',5],['long-an',4]]) {
  const marks=api.referenceAnnotations(template(name));
  assert.equal(marks.length,count);
  for (const ring of marks) {
    assert.equal(ring.length,4);
    const [x,y]=ring[0];
    const c={z:11,x:Math.floor(x/256),y:Math.floor(y/256)};
    assert.ok(api.referenceClipPath(template(name),c).includes('evenodd'));
    assert.ok(api.referenceClipPath(template(name),{z:12,x:Math.floor(x*2/256),y:Math.floor(y*2/256)}));
  }
}
assert.deepEqual(api.referenceAnnotations(template('unknown')),[]);
assert.equal(api.referenceClipPath(template('long-an'),{z:11,x:0,y:0}),'');
const events={},active=new Set(),labels=[];
const map={removeLayer(l){active.delete(l);}};
const layer={options:{opacity:.65,pane:'planningPilot',zIndex:301},
  on(k,f){events[k]=f;},setOpacity(v){this.options.opacity=v;return this;}};
const L={imageOverlay(url,bounds,options){
  assert.ok(url.startsWith('data:image/svg+xml,'));
  const svg=decodeURIComponent(url.split(',')[1]);
  assert.ok(svg.includes('Radar'));assert.ok(svg.includes('BDS'));
  assert.equal(options.interactive,false);assert.equal(options.attribution,'');
  assert.ok(bounds[0][0]<bounds[1][0]&&bounds[0][1]<bounds[1][1]);
  const label={options,addTo(m){assert.equal(m,map);active.add(this);},setOpacity(v){this.options.opacity=v;}};
  labels.push(label);return label;
}};
api.referenceBranding(layer,map,L,template('tay-ninh'));
assert.equal(labels.length,5);assert.equal(active.size,0);
events.add();assert.equal(active.size,5);
assert.equal(layer.setOpacity(.35),layer);assert.ok(labels.every(l=>l.options.opacity===.35));
events.remove();assert.equal(active.size,0);
events.add();assert.equal(active.size,5);
events.remove();assert.equal(active.size,0);
assert.equal(layer.options.opacity,.35);
console.log('Reference branding: 13 verified polygons, zoom coordinates, opacity and toggle cleanup passed');
