const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const runtime = require('../../static/js/main/filter_runtime.js');

function harness({ mobile = true, fetcher } = {}) {
  const elements = new Map();
  const events = [];
  const element = (id) => {
    if (!elements.has(id)) elements.set(id, {
      value: '', scrollTop: 0, textContent: '', innerHTML: '',
      classList: { add() {}, remove() {} },
    });
    return elements.get(id);
  };
  const context = vm.createContext({
    URLSearchParams, console, Set, Map,
    window: { USER_TIER: 'guest', scrollY: 0, RadarFilterRuntime: runtime,
      matchMedia: () => ({ matches: mobile }),
      scrollTo: ({ top }) => { context.window.scrollY = top; } },
    document: { getElementById: element, querySelector: element, querySelectorAll: () => [], addEventListener() {} },
    requestAnimationFrame: (callback) => callback(),
    activeTabId: () => 'all', currentFilters: 'city=TDM', currentPageNo: 1,
    listingsView: 'grid', listingsLoading: false, listingsHasMore: false, loadedListings: [],
    requestControllers: {},
    responseCache: new Map(),
    fetchJSONCached: async (...args) => {
      events.push(['fetch', args[1]]);
      return fetcher ? fetcher(...args) : { listings: [{ id: events.filter(([name]) => name === 'fetch').length }], has_more: false, total: 2 };
    },
  });
  vm.runInContext(fs.readFileSync('static/js/main/listings.js', 'utf8'), context);
  context.renderListingSkeletonCards = () => events.push(['skeleton']);
  context.renderListingCards = (items, options) => events.push(['render', items, options]);
  return { context, element, events };
}

test('returning to unchanged listings retains appended pages, DOM and scroll without fetching', async () => {
  const { context: c, element, events } = harness();
  await c.loadListings(1);
  await c.loadListings(2);
  c.window.scrollY = 430;
  element('tab-all').scrollTop = 210;
  element('#tab-all .table-scroll').scrollTop = 80;
  c.rememberListingsScroll();
  c.window.scrollY = 0;
  element('tab-all').scrollTop = 0;
  const before = events.length;
  await c.loadListings(1, { reuse: true });
  assert.equal(events.length, before);
  assert.equal(c.loadedListings.length, 2);
  assert.equal(c.currentPageNo, 2);
  assert.equal(c.window.scrollY, 430);
  assert.equal(element('tab-all').scrollTop, 210);
  assert.equal(element('#tab-all .table-scroll').scrollTop, 80);
});

test('empty results are retained, while changed filters or tier reload', async () => {
  const { context: c, events } = harness({ fetcher: async () => ({ listings: [], total: 0 }) });
  await c.loadListings(1);
  await c.loadListings(1, { reuse: true });
  assert.equal(events.filter(([name]) => name === 'fetch').length, 1);
  c.currentFilters = 'city=BenCat';
  await c.loadListings(1, { reuse: true });
  c.window.USER_TIER = 'vip';
  await c.loadListings(1, { reuse: true });
  assert.equal(events.filter(([name]) => name === 'fetch').length, 3);
});

test('mobile pages use 12 consistently even if viewport changes before page two', async () => {
  const { context: c, events } = harness();
  await c.loadListings(1);
  c.window.matchMedia = () => ({ matches: false });
  await c.loadListings(2);
  const queries = events.filter(([name]) => name === 'fetch').map(([, url]) => new URL(url, 'https://test').searchParams);
  assert.deepEqual(queries.map((p) => p.get('limit')), ['12', '12']);
  assert.deepEqual(queries.map((p) => p.get('page')), ['1', '2']);
});

test('desktop keeps 50 and honors explicit end-of-feed on a full page', async () => {
  const { context: c, events } = harness({ mobile: false,
    fetcher: async () => ({ listings: Array.from({ length: 50 }, (_, id) => ({ id })), has_more: false, total: 50 }),
  });
  await c.loadListings(1);
  assert.equal(new URL(events.find(([name]) => name === 'fetch')[1], 'https://test').searchParams.get('limit'), '50');
  assert.equal(c.listingsHasMore, false);
  assert.equal(c.loadedListings.length, 50);
});

function deferred() {
  let resolve, reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

test('new filter aborts the old request and late results never overwrite the new cards', async () => {
  const requests = [];
  const { context: c, events } = harness({ fetcher: () => {
    const pending = deferred(); requests.push(pending); return pending.promise;
  } });
  const old = c.loadListings(1);
  let aborted = 0;
  c.requestControllers.listings = { abort() { aborted++; } };
  c.currentFilters = 'ward=new';
  const newest = c.loadListings(1);
  assert.equal(aborted, 1);
  assert.equal(requests.length, 2);
  requests[1].resolve({ listings: [{ id: 20 }], total: 1, has_more: false });
  await newest;
  requests[0].resolve({ listings: [{ id: 10 }], total: 1 });
  await old;
  assert.deepEqual(Array.from(c.loadedListings, (x) => x.id), [20]);
  assert.deepEqual(events.filter(([name]) => name === 'render').map(([, items]) => items[0].id), [20]);
});

test('same in-flight request is shared; old failure cannot clear the newer loading state', async () => {
  const requests = [];
  const { context: c, element } = harness({ fetcher: () => {
    const pending = deferred(); requests.push(pending); return pending.promise;
  } });
  const old = c.loadListings(1);
  assert.equal(c.loadListings(1), old);
  assert.equal(requests.length, 1);
  c.currentFilters = 'ward=second';
  const newest = c.loadListings(1);
  requests[0].reject(new Error('old failure'));
  await old;
  assert.equal(c.listingsLoading, true);
  assert.equal(element('listingsGrid').innerHTML, '');
  requests[1].resolve({ listings: [{ id: 2 }], has_more: false });
  await newest;
  assert.equal(c.listingsLoading, false);
});

test('append removes repeated IDs while advancing page only after success', async () => {
  let page = 0;
  const { context: c } = harness({ fetcher: async () => ({
    listings: ++page === 1 ? [{ id: 1 }, { id: 2 }] : [{ id: 2 }, { id: 3 }], has_more: true,
  }) });
  await c.loadListings(1);
  await c.loadListings(2);
  assert.deepEqual(Array.from(c.loadedListings, (x) => x.id), [1, 2, 3]);
  assert.equal(c.currentPageNo, 2);
});

test('listings filter starts feed first and only the current completed run schedules metadata', async () => {
  const requests = [];
  const { context: c, events } = harness({ fetcher: () => {
    const pending = deferred(); requests.push(pending); return pending.promise;
  } });
  vm.runInContext(fs.readFileSync('static/js/main/filters.js', 'utf8'), c);
  c.getFilterQuery = () => c.currentFilters;
  c.ensureDashboardScript = async () => {};
  c.initializeListingsUi = () => {};
  c.deferCountsRefresh = () => events.push(['counts']);
  c.refreshDashboardMeta = () => events.push(['dashboard']);
  c.applyFilters();
  await new Promise(setImmediate);
  assert.equal(requests.length, 1);
  assert.equal(events.some(([name]) => name === 'counts' || name === 'dashboard'), false);
  c.currentFilters = 'ward=new';
  c.applyFilters();
  await new Promise(setImmediate);
  requests[0].resolve({ listings: [{ id: 1 }] });
  await new Promise(setImmediate);
  assert.equal(events.some(([name]) => name === 'counts' || name === 'dashboard'), false);
  requests[1].resolve({ listings: [{ id: 2 }] });
  await new Promise(setImmediate);
  const order = events.map(([name]) => name);
  assert.ok(order.indexOf('render') < order.indexOf('counts'));
  assert.ok(order.indexOf('render') < order.indexOf('dashboard'));
  assert.equal(order.filter((name) => name === 'counts').length, 1);
});
