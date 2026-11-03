const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('static/js/main/filters.js','utf8');
function fn(name){const start=source.indexOf('function '+name+'(');return source.slice(start,source.indexOf('\nfunction ',start+1));}
function query(province){
 const ctx={URLSearchParams,FormData:class{entries(){return new URLSearchParams('province='+province+'&price_max=5&date_range=1m').entries()}},
  document:{getElementById:id=>id==='listingProvince'?{value:province}:null,querySelector:()=>null},
  window:{RadarFilterRuntime:require('../../static/js/main/filter_runtime.js'),RadarAreaScope:{getCurrentScope:()=>({}),applyScopeToParams:p=>{p.set('city','THỦ DẦU MỘT');p.append('ward','Tân An')}}},
  globalWardsByCity:{},selectedRangeTokens:()=>[],getKeywordSearchValue:()=>'',trendPeriod:'month'};
 vm.createContext(ctx);vm.runInContext(fn('getFilterQuery'),ctx);return new URLSearchParams(ctx.getFilterQuery());
}
test('province changes remove old locality without discarding price and time filters',()=>{
 const other=query('ha-noi');assert.equal(other.get('province'),'ha-noi');assert.equal(other.get('ward_mode'),'none');assert.equal(other.has('city'),false);assert.equal(other.has('ward'),false);assert.equal(other.get('price_max'),'5');assert.equal(other.get('date_range'),'1m');
 const bd=query('binh-duong');assert.equal(bd.get('ward'),'Tân An');assert.equal(bd.get('city'),'THỦ DẦU MỘT');assert.equal(bd.has('ward_mode'),false);
});
