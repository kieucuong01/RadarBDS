const test = require('node:test');
const assert = require('node:assert/strict');
const measure = require('../../static/js/main/planning_measure.js');
const p = (lat,lng)=>({lat,lng});
test('great-circle distance and area use metres and are independent of vertex direction',()=>{
  assert(Math.abs(measure.distance(p(0,0),p(0,1))-111194.93)<.1);
  const ring=[p(11,106),p(11,106.001),p(11.001,106.001),p(11.001,106)];
  const expected=6371000**2*Math.PI/180*.001*(Math.sin(11.001*Math.PI/180)-Math.sin(11*Math.PI/180));
  assert(Math.abs(measure.area(ring)-expected)<.001);
  assert(Math.abs(measure.area([...ring].reverse())-expected)<.001);
  assert(measure.validPolygon(ring));
});
test('crossed, duplicate, collinear and non-finite outlines cannot report an area',()=>{
  assert(!measure.validPolygon([p(11,106),p(11.001,106.001),p(11.001,106),p(11,106.001)]));
  assert(!measure.validPolygon([p(11,106),p(11,106.001),p(11,106.002)]));
  assert(!measure.canAdd([p(11,106)],p(11,106)));
  assert(!measure.canAdd([],p(NaN,106)));
  assert(!measure.canAdd([p(11,106),p(11.001,106.001),p(11.001,106)],p(11,106.001)));
});
test('distance and area have readable metric formatting',()=>{
  assert.match(measure.formatDistance(120),/120.*m/);
  assert.match(measure.formatDistance(1500),/1,5.*km/);
  assert.match(measure.formatArea(120),/120.*m²/);
  assert.match(measure.formatArea(15000),/15.000.*m².*1,5.*ha/);
});
