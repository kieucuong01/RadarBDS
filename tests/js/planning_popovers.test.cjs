const test=require('node:test'),assert=require('node:assert/strict');
const overlay=require('../../static/js/main/planning_overlay.js');
const listing=require('../../static/js/main/listing_map.js');

test('outside pointer closes open map popovers while inside inputs stay open',()=>{
 const input={},outside={};const panel={open:true,contains:n=>n===input};
 overlay.dismissOutsidePanels([panel],input);assert.equal(panel.open,true);
 overlay.dismissOutsidePanels([panel],outside);assert.equal(panel.open,false);
 panel.open=true;overlay.dismissOutsidePanels([panel],null);assert.equal(panel.open,true);
});

test('filter drawer ignores its own controls and toggle but dismisses for map/other panels',()=>{
 const input={},button={},map={};
 const sidebar={contains:n=>n===input},trigger={contains:n=>n===button};
 assert.equal(listing.outsideFilters(input,sidebar,trigger),false);
 assert.equal(listing.outsideFilters(button,sidebar,trigger),false);
 assert.equal(listing.outsideFilters(map,sidebar,trigger),true);
 assert.equal(listing.outsideFilters(null,sidebar,trigger),false);
});
