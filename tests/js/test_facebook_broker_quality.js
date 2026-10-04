'use strict';
const assert = require('assert');
const api = require('../../static/js/admin/facebook-crawl.js');

const healthyDue = {active: true, due_today: true, data_quality: {score: 90}};
assert.equal(api.buildBrokerRosterViewModel([healthyDue], {}).summary.needsAttention, 0);
assert.equal(api.buildBrokerRosterViewModel([healthyDue], {}).summary.due, 1);
assert.equal(api.buildOverviewViewModel({latest_job: {
  status: 'succeeded', stage: 'done_partial',
}}).latestJob.statusLabel, 'Hoàn tất một phần');
assert.equal(api.brokerQualityState({stats_status: 'unavailable'}).label, 'Thống kê lỗi');
assert.equal(api.brokerQualityState({raw_count: 0, data_quality: {score: null}}).label, 'Chưa có bài');
assert.equal(api.brokerQualityState({raw_count: 4, data_quality: {score: null, sample_size: 4}}).label, 'Chưa đủ mẫu');
assert.equal(api.brokerQualityState({data_quality: {score: 88, serious_flag_pct: 22}}).key, 'needs_attention');
assert.equal(api.brokerQualityState({data_quality: {score: 88, serious_flag_pct: 22, label: 'Dữ liệu sạch'}}).label, 'Cần kiểm tra lỗi parse');
assert.match(api.brokerQualityDetail({raw_count: 120, data_quality: {score: 90, sample_size: 100}}), /100.*120/);
assert.match(api.brokerCrawlDetail({raw_count: 20, latest_received_at: '2026-08-01'}), /01\/08\/2026/);
assert.doesNotMatch(api.brokerCrawlDetail({raw_count: 20, latest_received_at: '2026-08-01'}), /Chưa crawl/);
console.log('Facebook broker quality behavior passed');

