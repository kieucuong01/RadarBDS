'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const api = require('../../static/js/admin/facebook-crawl.js');
const source = fs.readFileSync(
  path.join(__dirname, '../../static/js/admin/facebook-crawl.js'),
  'utf8',
);

assert.equal(api.normalizeView('unknown'), 'overview');
assert.equal(api.normalizeView(''), 'overview');
assert.equal(api.normalizeView('brokers'), 'brokers');
assert.equal(api.normalizeView('run'), 'run');

const baseline = [
  {
    url: 'https://www.facebook.com/broker-a',
    broker_name: 'Broker A',
    city: 'Thủ Dầu Một',
    active: true,
    daily_limit: 30,
    range_days: 7,
    crawl_every_days: 1,
  },
];
const equivalent = [{...baseline[0]}];
const changed = [{...baseline[0], daily_limit: 31}];

assert.equal(api.isDraftDirty(baseline, equivalent), false);
assert.equal(api.isDraftDirty(baseline, changed), true);
assert.equal(
  api.normalizedProfilesHash(baseline),
  api.normalizedProfilesHash(equivalent),
);
assert.notEqual(
  api.normalizedProfilesHash(baseline),
  api.normalizedProfilesHash(changed),
);

const draftForRemoval = [
  {url: 'https://www.facebook.com/broker-a', broker_name: 'Broker A'},
  {url: 'https://www.facebook.com/broker-b', broker_name: 'Broker B'},
];
const remainingAfterRemoval = api.removeProfileFromDraft(
  draftForRemoval,
  'https://www.facebook.com/broker-a',
);
assert.deepEqual(remainingAfterRemoval, [
  {url: 'https://www.facebook.com/broker-b', broker_name: 'Broker B'},
]);
assert.deepEqual(draftForRemoval, [
  {url: 'https://www.facebook.com/broker-a', broker_name: 'Broker A'},
  {url: 'https://www.facebook.com/broker-b', broker_name: 'Broker B'},
]);

assert.deepEqual(api.requestsForView('overview'), ['/admin/api/facebook-crawl/overview']);
assert.deepEqual(api.requestsForView('brokers'), [
  '/admin/api/facebook-crawl/profiles',
  '/admin/api/facebook-crawl/duplicates?actionable=1&limit=20&offset=0',
]);
assert.deepEqual(api.requestsForView('run'), ['/admin/api/facebook-crawl/jobs']);

const preview = api.buildRunPreview({
  broker_name: 'Broker A',
  mode: 'first',
  limit: 900,
  days: 7,
  download_images: true,
});
assert.match(preview, /Broker A/);
assert.match(preview, /Lần đầu/);
assert.match(preview, /900/);
assert.match(preview, /Có tải ảnh/);

assert.match(api.buildMaintenancePreview('reprocess'), /toàn bộ dữ liệu Facebook/i);
assert.match(api.buildMaintenancePreview('valuation_only'), /định giá/i);
assert.equal(api.nextDuplicateOffset({offset: 20, items: new Array(7)}), 27);
assert.equal(api.runLimitForMode('first', {daily_limit: 25}), 330);
assert.equal(api.runLimitForMode('daily', {daily_limit: 25}), 25);
assert.equal(api.runLimitForMode('range', {daily_limit: 25}), 25);
assert.equal(api.runLimitForMode('daily', {}), 30);

const preselected = api.preselectRun(
  {view: 'brokers', runProfileUrl: '', shouldSubmit: false},
  baseline[0],
);
assert.equal(preselected.view, 'run');
assert.equal(preselected.runProfileUrl, baseline[0].url);
assert.equal(preselected.shouldSubmit, false);

const conflict = api.profileSaveFailure(
  {draft: changed, conflict: null},
  {
    status: 409,
    payload: {
      error: 'profile_revision_conflict',
      revision: 'new-revision',
      profiles: baseline,
    },
  },
);
assert.deepEqual(conflict.draft, changed);
assert.equal(conflict.conflict.revision, 'new-revision');
assert.match(source, /facebook-crawl\/tokens/);
assert.doesNotMatch(source, /\.innerHTML\s*=/);

console.log('facebook crawl admin contracts: ok');
