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

const rosterProfiles = [
  {
    url: 'https://www.facebook.com/broker-a/',
    broker_name: 'Broker A',
    city: 'Thủ Dầu Một',
    active: true,
    crawl_every_days: 1,
    due_today: true,
    next_due_date: '2026-08-11',
    data_quality: {score: 82, label: 'Tốt'},
  },
  {
    url: 'https://m.facebook.com/broker-b',
    broker_name: 'Broker B',
    city: 'Bến Cát',
    active: true,
    crawl_every_days: 3,
    due_today: false,
    next_due_date: '2026-08-13',
    data_quality: {score: 50, label: 'Cần xem'},
  },
  {
    url: 'https://www.facebook.com/broker-c',
    broker_name: 'Broker C',
    city: 'Bến Cát',
    active: false,
    crawl_every_days: 7,
    due_today: true,
    data_quality: {score: null},
  },
];
const rosterSnapshot = JSON.stringify(rosterProfiles);
const roster = api.buildBrokerRosterViewModel(rosterProfiles, {});
assert.deepEqual(roster.summary, {
  total: 3,
  active: 2,
  due: 1,
  needsAttention: 2,
});
assert.equal(roster.resultCount, 3);
assert.equal(roster.activeFilterCount, 0);
assert.equal(roster.emptyState, '');
assert.equal(JSON.stringify(rosterProfiles), rosterSnapshot);

const filteredRoster = api.buildBrokerRosterViewModel(rosterProfiles, {
  search: 'broker-b',
  city: 'Bến Cát',
  active: 'true',
  cadence: '3',
  due: 'false',
  quality: 'needs_attention',
});
assert.deepEqual(filteredRoster.filteredProfiles, [rosterProfiles[1]]);
assert.equal(filteredRoster.activeFilterCount, 6);
assert.equal(
  api.buildBrokerRosterViewModel([], {}).emptyState,
  'empty',
);
assert.equal(
  api.buildBrokerRosterViewModel(rosterProfiles, {search: 'không tồn tại'}).emptyState,
  'filtered',
);

assert.deepEqual(api.brokerStatusState(rosterProfiles[0]), {
  key: 'active',
  label: 'Đang bật',
});
assert.deepEqual(api.brokerStatusState(rosterProfiles[2]), {
  key: 'paused',
  label: 'Đã tắt',
});
assert.equal(api.brokerScheduleState(rosterProfiles[0]).key, 'due');
assert.equal(api.brokerScheduleState(rosterProfiles[1]).detail, '2026-08-13');
assert.equal(api.brokerQualityState(rosterProfiles[0]).key, 'good');
assert.equal(api.brokerQualityState(rosterProfiles[1]).key, 'needs_attention');
assert.equal(api.brokerQualityState(rosterProfiles[2]).score, null);

assert.deepEqual(
  api.safeFacebookProfileLink('https://www.facebook.com/broker-a/'),
  {
    href: 'https://www.facebook.com/broker-a/',
    display: 'facebook.com/broker-a',
  },
);
assert.equal(api.safeFacebookProfileLink('javascript:alert(1)'), null);
assert.equal(api.safeFacebookProfileLink('https://example.com/broker-a'), null);
assert.match(source, /facebook-crawl\/tokens/);
assert.match(source, /function setOverviewLoading/);
assert.match(source, /function renderOverviewProblem/);
assert.match(source, /crawlOverviewRunBtn/);
assert.match(source, /crawlOverviewBrokersBtn/);
assert.match(source, /crawlOverviewRetryBtn/);
assert.match(source, /dataset\.health/);
assert.match(source, /aria-busy/);
assert.doesNotMatch(source, /\.innerHTML\s*=/);

const groupedProblems = api.groupOverviewProblems([
  {code: 'source_error', label: 'Nguồn guland đang lỗi'},
  {code: 'source_error', label: 'Nguồn guland đang lỗi'},
  {code: 'schedule_missing', label: 'Lịch crawl chưa hoạt động'},
  {code: '', label: ''},
]);
assert.deepEqual(groupedProblems, [
  {
    key: 'source_error:nguồn guland đang lỗi',
    code: 'source_error',
    label: 'Nguồn guland đang lỗi',
    severity: 'warning',
    count: 2,
  },
  {
    key: 'schedule_missing:lịch crawl chưa hoạt động',
    code: 'schedule_missing',
    label: 'Lịch crawl chưa hoạt động',
    severity: 'critical',
    count: 1,
  },
  {
    key: 'unknown:có vấn đề cần kiểm tra',
    code: 'unknown',
    label: 'Có vấn đề cần kiểm tra',
    severity: 'warning',
    count: 1,
  },
]);

const warningOverview = api.buildOverviewViewModel({
  schedule: {installed: true, next_run_time: '2026-08-11 21:00'},
  last_facebook_run: null,
  latest_job: {
    status: 'succeeded',
    progress_label: 'Recovered: crawl/reprocess done, images recovered',
  },
  apify: {enabled_tokens: 5, total_tokens: 12},
  problems: [
    {code: 'source_error', label: 'Nguồn facebook đang lỗi'},
  ],
});
assert.equal(warningOverview.health, 'warning');
assert.equal(warningOverview.healthLabel, 'Cần theo dõi');
assert.equal(warningOverview.nextRun, '2026-08-11 21:00');
assert.equal(warningOverview.lastFacebookRun, 'Chưa có dữ liệu lần chạy Facebook');
assert.equal(warningOverview.latestJob.status, 'succeeded');
assert.equal(warningOverview.latestJob.statusLabel, 'Đã hoàn tất');
assert.equal(warningOverview.latestJob.label, 'Recovered: crawl/reprocess done, images recovered');
assert.equal(warningOverview.apify.ratioLabel, '5 / 12 key');

const criticalOverview = api.buildOverviewViewModel({
  schedule: {installed: false},
  apify: {enabled_tokens: 0, total_tokens: 2},
  problems: [
    {code: 'schedule_missing', label: 'Lịch crawl chưa hoạt động'},
    {code: 'apify_unavailable', label: 'Không có Apify token khả dụng'},
  ],
});
assert.equal(criticalOverview.health, 'critical');
assert.equal(criticalOverview.healthLabel, 'Cần xử lý ngay');
assert.equal(criticalOverview.problems.length, 2);

const healthyOverview = api.buildOverviewViewModel({
  schedule: {installed: true},
  apify: {enabled_tokens: 1, total_tokens: 1},
  problems: [],
});
assert.equal(healthyOverview.health, 'healthy');
assert.equal(healthyOverview.healthLabel, 'Hệ thống ổn định');

const malformedOverview = api.buildOverviewViewModel({
  latest_job: {status: 'unexpected'},
  apify: {enabled_tokens: 'bad', total_tokens: -4},
  problems: 'not-an-array',
});
assert.equal(malformedOverview.latestJob.status, 'unexpected');
assert.equal(malformedOverview.latestJob.statusLabel, 'Chưa rõ');
assert.equal(malformedOverview.apify.enabled, 0);
assert.equal(malformedOverview.apify.total, 0);
assert.deepEqual(malformedOverview.problems, []);

assert.match(source, /crawlBrokerResetBtn/);
assert.match(source, /buildBrokerRosterViewModel\(state\.draft, readBrokerFilters\(\)\)/);
assert.match(source, /safeFacebookProfileLink\(profile\.url\)/);
assert.match(source, /noopener noreferrer/);
assert.match(source, /brokerCell\('STT', 'crawl-broker-ordinal'\)/);
assert.match(source, /brokerCell\('Khu vực', 'crawl-broker-area'\)/);
assert.match(source, /brokerName\.className = 'crawl-broker-name'/);
assert.match(source, /cell\.colSpan = 9/);
assert.equal(api.duplicatePresentationState(null, false), 'loading');
assert.equal(api.duplicatePresentationState(null, true), 'error');
assert.equal(api.duplicatePresentationState({items: []}, false), 'empty');
assert.equal(api.duplicatePresentationState({items: [{}]}, false), 'ready');
assert.match(source, /crawlBrokerDrawerBackdrop/);
assert.match(source, /event\.key === 'Escape'/);
assert.match(source, /event\.key !== 'Tab'/);

console.log('facebook crawl admin contracts: ok');
