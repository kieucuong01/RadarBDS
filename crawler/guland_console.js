// ============================================================
// GULAND CONSOLE CRAWLER
// Paste vào DevTools Console khi đang ở trang guland.vn/...
// Tự động crawl tất cả trang + detail pages → tải file JSON
// ============================================================

(async () => {
  const BASE = location.href.split('?')[0];
  const DELAY = ms => new Promise(r => setTimeout(r, ms));

  function parseCards(html) {
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const cards = doc.querySelectorAll('.c-sdb-card');
    const results = [];
    cards.forEach(card => {
      const links = card.querySelectorAll('a[href*="/post/"]');
      const a = links.length > 1 ? links[1] : links[0];
      if (!a) return;
      const url = a.href;
      const postId = url.match(/(\d+)(?:\.html)?$/)?.[1] || '';
      const title = (card.querySelector('.c-sdb-card__tle') || a).textContent.trim();
      const priceEl = card.querySelector('.sdb-inf-data.data-color-1.data-size-xl b');
      const infBs = card.querySelectorAll('.sdb-inf-data.data-size-lg b');
      const dateEl = card.querySelector('.profile-info__stl, .sdb-time');
      const imgs = [...card.querySelectorAll('img[src*="cdn.guland"]')].map(i => i.src);
      results.push({
        url: url.replace('https://guland.vn', 'guland.vn'),
        post_id: postId,
        title,
        price_raw: priceEl?.textContent.trim() || '',
        area_raw: infBs[0]?.textContent.trim() || '',
        pm2_raw: infBs[1]?.textContent.trim() || '',
        date_raw: dateEl?.textContent.trim() || '',
        imgs,
      });
    });
    return results;
  }

  function hasMore(html) {
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const btn = doc.querySelector('#btn-load-more');
    return btn ? !btn.classList.contains('d-none') : false;
  }

  async function fetchDetail(url) {
    try {
      const r = await fetch(url.startsWith('http') ? url : 'https://' + url);
      const html = await r.text();
      const doc = new DOMParser().parseFromString(html, 'text/html');

      const getText = sel => (doc.querySelector(sel)?.textContent.trim() || '');
      const infoRow = getText('.dtl-inf__row');

      const extract = (...keys) => {
        for (const k of keys) {
          const m = infoRow.match(new RegExp(k + '[\\s\\-:]+([^\\n]+?)(?=\\s{2,}|$)', 'i'));
          if (m) return m[1].trim();
        }
        return '';
      };

      const phoneEl = doc.querySelector('[href^="tel:"]');
      const phone = phoneEl ? phoneEl.href.replace('tel:', '') : '';

      return {
        description: getText('.dtl-inf__dsr'),
        address: getText('.dtl-stl__row'),
        property_type_raw: extract('Loại BĐS', 'Loại bds'),
        road_type_raw: extract('Loại đường', 'Đường'),
        road_width_raw: extract('Đường.hẻm vào rộng', 'Chiều rộng'),
        legal_raw: extract('Pháp lý'),
        contact_phone: phone,
      };
    } catch (e) {
      return {};
    }
  }

  // ── Bước 1: Crawl listing pages ──────────────────────────────
  console.log('🔍 Bước 1: Crawl listing pages...');
  const allCards = [];
  const seenUrls = new Set();

  for (let page = 1; page <= 50; page++) {
    const url = page === 1 ? BASE : `${BASE}?page=${page}`;
    console.log(`  Page ${page}: ${url}`);
    const r = await fetch(url);
    const html = await r.text();
    const cards = parseCards(html).filter(c => !seenUrls.has(c.url));
    cards.forEach(c => seenUrls.add(c.url));
    allCards.push(...cards);
    console.log(`  → ${cards.length} new cards (total=${allCards.length}) | more=${hasMore(html)}`);
    if (!cards.length || !hasMore(html)) break;
    await DELAY(300);
  }
  console.log(`✅ Tổng listing cards: ${allCards.length}`);

  // ── Bước 2: Crawl detail pages (batch 5) ────────────────────
  console.log('🔍 Bước 2: Crawl detail pages...');
  const results = [];
  const BATCH = 5;
  for (let i = 0; i < allCards.length; i += BATCH) {
    const batch = allCards.slice(i, i + BATCH);
    const details = await Promise.all(batch.map(c =>
      fetchDetail('https://guland.vn/' + c.url.replace('guland.vn/', ''))
    ));
    batch.forEach((card, j) => results.push({ ...card, ...details[j] }));
    if ((i + BATCH) % 50 === 0 || i + BATCH >= allCards.length) {
      console.log(`  ${Math.min(i + BATCH, allCards.length)}/${allCards.length} detail pages done`);
    }
    await DELAY(200);
  }

  // ── Bước 3: Download JSON ────────────────────────────────────
  const json = JSON.stringify(results, null, 2);
  const blob = new Blob([json], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'guland_fresh.json';
  a.click();

  console.log(`🎉 XONG! ${results.length} records → guland_fresh.json`);
  console.log(`   Has description: ${results.filter(r => r.description).length}/${results.length}`);
})();
