// ============================================================
// BATDONGSAN CONSOLE CRAWLER
// Paste vào DevTools Console khi đang ở trang batdongsan.com.vn
// (navigate đến bất kỳ trang nào của BDS trước)
// ============================================================

(async () => {
  const DELAY = ms => new Promise(r => setTimeout(r, ms));
  const BASE = 'https://batdongsan.com.vn';

  const SLUGS = [
    'ban-dat-phuong-tan-an_1',
    'ban-dat-phuong-phu-an_1',
    'ban-nha-phuong-tan-an_1',
    'ban-dat-duong-dx-122-phuong-tan-an_1-163',
  ];

  function parseCards(doc) {
    const items = doc.querySelectorAll('.js__card, [data-url], .re__card-full');
    const results = [];
    items.forEach(item => {
      // URL
      let url = item.getAttribute('data-url') || item.querySelector('a')?.getAttribute('href') || '';
      if (!url) return;
      if (!url.startsWith('http')) url = BASE + url;

      // Title
      const title = item.querySelector('span.pr-title, .js__card-title, .re__card-info-title')?.textContent.trim() || '';

      // Price
      const price = item.querySelector('.re__card-config-price, span[class*="price"]')?.textContent.trim() || '';

      // Area
      const area = item.querySelector('.re__card-config-area, span[class*="area"]')?.textContent.trim() || '';

      // Date
      const date = item.querySelector('[class*="time"], [class*="date"]')?.textContent.trim() || '';

      // Source ID from URL
      const sid = url.match(/-(\d+)\.html$/)?.[1] || url.match(/\/(\d+)\/?$/)?.[1] || '';

      results.push({ url, source_id: sid, title, price_raw: price, area_raw: area, date_raw: date });
    });
    return results;
  }

  async function fetchDetail(url) {
    try {
      const r = await fetch(url);
      const html = await r.text();
      const doc = new DOMParser().parseFromString(html, 'text/html');

      const getText = sel => doc.querySelector(sel)?.textContent.trim() || '';

      // Description
      const desc = getText('.re__section-description, .re__detail-content, [class*="description"]');

      // Phone (thường bị ẩn, lấy từ meta hoặc structured data)
      let phone = '';
      const phoneEl = doc.querySelector('[href^="tel:"]');
      if (phoneEl) phone = phoneEl.href.replace('tel:', '');

      // Address
      const address = getText('.re__pr-short-description, [class*="address"], [class*="location"]');

      // Area/price from detail (backup)
      const priceDetail = getText('.re__pr-price .re__pr-price-value');
      const areaDetail = getText('.re__pr-specs-content-item-value');

      return { description: desc, contact_phone: phone, address, price_raw_detail: priceDetail, area_raw_detail: areaDetail };
    } catch (e) {
      return {};
    }
  }

  // ── Bước 1: Crawl tất cả slug ────────────────────────────────
  console.log('🔍 Bước 1: Crawl listing pages...');
  const allCards = [];
  const seenUrls = new Set();

  for (const slug of SLUGS) {
    console.log(`  Slug: ${slug}`);
    for (let page = 1; page <= 20; page++) {
      const pageUrl = page === 1
        ? `${BASE}/${slug}`
        : `${BASE}/${slug}/p${page}`;

      const r = await fetch(pageUrl);
      const html = await r.text();
      const doc = new DOMParser().parseFromString(html, 'text/html');
      const cards = parseCards(doc).filter(c => !seenUrls.has(c.url));
      cards.forEach(c => seenUrls.add(c.url));
      allCards.push(...cards);
      console.log(`    Page ${page}: ${cards.length} new (total=${allCards.length})`);
      if (!cards.length) break;
      await DELAY(500);
    }
  }
  console.log(`✅ Tổng listing cards: ${allCards.length}`);

  // ── Bước 2: Crawl detail pages ───────────────────────────────
  console.log('🔍 Bước 2: Crawl detail pages...');
  const results = [];
  const BATCH = 3;
  for (let i = 0; i < allCards.length; i += BATCH) {
    const batch = allCards.slice(i, i + BATCH);
    const details = await Promise.all(batch.map(c => fetchDetail(c.url)));
    batch.forEach((card, j) => {
      const d = details[j];
      results.push({
        ...card,
        description: d.description || '',
        contact_phone: d.contact_phone || '',
        address: d.address || '',
        price_raw: card.price_raw || d.price_raw_detail || '',
        area_raw: card.area_raw || d.area_raw_detail || '',
      });
    });
    if ((i + BATCH) % 30 === 0 || i + BATCH >= allCards.length) {
      console.log(`  ${Math.min(i + BATCH, allCards.length)}/${allCards.length} done`);
    }
    await DELAY(500);
  }

  // ── Bước 3: Download JSON ────────────────────────────────────
  const json = JSON.stringify(results, null, 2);
  const blob = new Blob([json], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'bds_fresh.json';
  a.click();

  console.log(`🎉 XONG! ${results.length} records → bds_fresh.json`);
})();
