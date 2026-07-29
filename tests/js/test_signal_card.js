const assert = require('node:assert/strict');
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
assert.match(feed, /role="button"/);
assert.match(feed, /favorite-btn/);
assert.match(feed, /Ráp mối/);

console.log('shared signal card renderer: ok');
