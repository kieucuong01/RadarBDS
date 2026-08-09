const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const api = require(path.join(
  __dirname,
  '..',
  '..',
  'static',
  'js',
  'main',
  'signal_card.js',
));

const item = {
  id: 42,
  title: 'Đất nền Phú Lợi',
  primary_img: '/data/images/thumbs/42.webp',
  price_ty: 2,
  actual_ppm2: 20,
  fair_ppm2_display: 30,
  area_m2: 100,
  frontage_m: 5,
  depth_m: 20,
  mos_pct_display: 33.3,
  ward: 'Phú Lợi',
  road_label: 'Đường nhựa 6m',
  street_label: 'Mặt tiền ĐX 43',
  prop_type: 'dat_nen',
  prop_type_label: 'Đất nền',
  tho_cu_label: 'TC 60m²',
  days_ago: 0,
  detail_url: '/listing/42',
};

const comparable = api.render(item, {
  context: 'comparable',
  openMode: 'link',
  showFavorite: false,
  showContact: false,
});
assert.match(comparable, /class="scard[^"]*signal-shared-card/);
assert.match(comparable, /href="\/listing\/42"/);
assert.match(comparable, /mos-badge/);
assert.match(comparable, /price-actual/);
assert.match(comparable, /price-fair/);
assert.match(comparable, /meta-chip-ward/);
assert.match(comparable, /meta-chip-area/);
assert.doesNotMatch(comparable, /favorite-btn/);
assert.doesNotMatch(comparable, /Ráp mối/);
assert.match(comparable, /onerror="RadarSignalCard\.useFallbackImage\(this\)"/);

const withoutImage = api.render({ ...item, primary_img: '', imgs: [] }, {
  context: 'comparable',
  openMode: 'link',
  showFavorite: false,
  showContact: false,
});
assert.match(withoutImage, /<img[^>]+class="sc-img/);
assert.match(withoutImage, /data-default-image="true"/);
assert.match(withoutImage, /Chưa có ảnh/);
assert.match(api.defaultImage(), /^data:image\/svg\+xml/);

const fakeImage = {
  onerror: () => {},
  src: '/bad.jpg',
  dataset: {},
  classList: { add() {} },
  parentElement: { classList: { add() {} } },
};
api.useFallbackImage(fakeImage);
assert.equal(fakeImage.onerror, null);
assert.equal(fakeImage.src, api.defaultImage());
assert.equal(fakeImage.dataset.defaultImage, 'true');

const feed = api.render(item, {
  context: 'signal',
  openMode: 'modal',
  showFavorite: true,
  showContact: true,
});
assert.match(feed, /<article class="scard[^>]*signal-shared-card/);
assert.match(feed, /class="sc-title sc-title-link"/);
assert.match(feed, /href="\/listing\/42"/);
assert.doesNotMatch(feed, /role="button"/);
assert.doesNotMatch(feed, /tabindex="0"/);
assert.doesNotMatch(feed, /onkeydown=/);
assert.match(feed, /favorite-btn/);
assert.match(feed, /Ráp mối/);

const gulandFirstSeen = api.render({
  ...item,
  source: 'guland',
  days_ago: 3,
  card_date_reason: 'first_seen',
}, {
  context: 'signal',
  openMode: 'modal',
});
assert.match(gulandFirstSeen, /Theo dõi từ 3 ngày trước/);
assert.match(gulandFirstSeen, />MỚI</);

const gulandPriceUpdated = api.render({
  ...item,
  source: 'guland',
  days_ago: 0,
  card_date_reason: 'price_updated',
}, {
  context: 'signal',
  openMode: 'modal',
});
assert.match(gulandPriceUpdated, /Cập nhật giá hôm nay/);
assert.match(gulandPriceUpdated, />CẬP NHẬT GIÁ</);
assert.doesNotMatch(gulandPriceUpdated, />MỚI</);

const unknownDate = api.render({
  ...item,
  days_ago: null,
  card_date_reason: 'posted',
}, {
  context: 'signal',
  openMode: 'modal',
});
assert.match(unknownDate, /Chưa rõ ngày/);
assert.doesNotMatch(unknownDate, />MỚI</);

const legacyFeed = api.render({
  ...item,
  price_dropped: true,
  drop_pct: 3.7,
  fair_ppm2: 24.3,
  fair_ppm2_old: 24.3,
  fair_ppm2_new: 30.8,
  fair_ppm2_display: 24.3,
  source_quality_recheck: true,
  source_quality_flags: 'low_segment_confidence',
}, {
  context: 'signal',
  openMode: 'modal',
  showFavorite: true,
  showContact: true,
});
assert.match(legacyFeed, /sc-time-tag/);
assert.match(legacyFeed, /sc-drop-tag/);
assert.match(legacyFeed, /valuation-sep/);
assert.match(legacyFeed, /valuation-total-row/);
assert.match(legacyFeed, /valuation-ppm2-row/);
assert.match(legacyFeed, /data-fair-ppm2-old="24\.3"/);
assert.match(legacyFeed, /data-fair-ppm2-new="30\.8"/);
assert.match(legacyFeed, /sc-quality-tag/);

const signalsSource = fs.readFileSync(path.join(
  __dirname,
  '..',
  '..',
  'static',
  'js',
  'main',
  'signals.js',
), 'utf8');
assert.doesNotMatch(signalsSource, /Đã lưu/);
assert.match(signalsSource, /<article class="scard/);
assert.match(signalsSource, /class="sc-title sc-title-link"/);
assert.doesNotMatch(
  signalsSource,
  /<div class="scard[^`]*role="button" tabindex="0"/,
);

console.log('shared signal card renderer: ok');
