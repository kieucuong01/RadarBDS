// Init theme on load before body renders
const savedTheme = localStorage.getItem('radar_theme') || 'light';
document.documentElement.setAttribute('data-theme', savedTheme);

function toggleTheme() {
  const isLight = document.documentElement.getAttribute('data-theme') === 'light';
  if (isLight) {
    document.documentElement.setAttribute('data-theme', 'dark');
    localStorage.setItem('radar_theme', 'dark');
  } else {
    document.documentElement.setAttribute('data-theme', 'light');
    localStorage.setItem('radar_theme', 'light');
  }
}

function toggleMenu() {
  if (window.innerWidth <= 1024) {
    document.getElementById('sidebar').classList.toggle('show');
    document.getElementById('mobileOverlay').classList.toggle('show');
  } else {
    document.getElementById('sidebar').classList.toggle('collapsed');
  }
}

function hideSidebarMobile() {
  if (window.innerWidth <= 1024) {
    document.getElementById('sidebar').classList.remove('show');
    document.getElementById('mobileOverlay').classList.remove('show');
  }
}

// Global State
let currentFilters = "";
let currentPageNo = 1;
let trendPeriod = 'month'; 
let historyChartInstance = null;
let globalSignals = [];
let globalWardsByCity = {};
const CACHE_TTL_MS = 60000;
const responseCache = new Map();
const requestControllers = {};
let filterDebounceTimer = null;

const CITY_COORDS = {
  "THỦ DẦU MỘT": { lat: 10.98, lon: 106.65 },
  "BẾN CÁT": { lat: 11.13, lon: 106.61 },
  "THUẬN AN": { lat: 10.91, lon: 106.70 },
  "DĨ AN": { lat: 10.91, lon: 106.77 },
  "TÂN UYÊN": { lat: 11.05, lon: 106.81 }
};

function detectLocation() {
  if (!navigator.geolocation) {
    console.warn("Geolocation not supported. Using fallback.");
    applyFilters();
    return;
  }
  
  navigator.geolocation.getCurrentPosition((pos) => {
    const lat = pos.coords.latitude;
    const lon = pos.coords.longitude;
    
    let closestCity = "THỦ DẦU MỘT";
    let minDist = Infinity;
    
    for (const [city, coords] of Object.entries(CITY_COORDS)) {
      const d = Math.sqrt(Math.pow(lat - coords.lat, 2) + Math.pow(lon - coords.lon, 2));
      if (d < minDist) {
        minDist = d;
        closestCity = city;
      }
    }
    
    const radios = document.getElementsByName('city');
    radios.forEach(r => {
      if (r.value === closestCity) {
        r.checked = true;
      }
    });
    
    console.log("Detected location, closest city:", closestCity);
    applyFilters();
  }, (err) => {
    console.warn("Geolocation error:", err.message);
    // Fallback: Ensure THỦ DẦU MỘT is checked (which triggers Tân An fallback in updateWardFilters)
    const radios = document.getElementsByName('city');
    radios.forEach(r => { if(r.value === "THỦ DẦU MỘT") r.checked = true; });
    applyFilters();
  });
}
let treemapInstance = null;
let trendInstance = null;
let priceGapInstance = null;
const PLACEHOLDER_IMG = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='800' height='520' viewBox='0 0 800 520'%3E%3Crect width='800' height='520' fill='%23e2e8f0'/%3E%3Cpath d='M275 330l78-86 58 62 38-42 76 66H275z' fill='%2394a3b8'/%3E%3Ccircle cx='505' cy='190' r='38' fill='%23cbd5e1'/%3E%3Ctext x='400' y='405' text-anchor='middle' font-family='Arial,sans-serif' font-size='30' font-weight='700' fill='%2364748b'%3EChưa có ảnh%3C/text%3E%3C/svg%3E";

const sourceNames = { 'batdongsan': 'BDS.vn', 'facebook': 'Facebook', 'guland': 'Guland' };
const sourceClasses = { 'batdongsan': 'source-bds', 'facebook': 'source-fb', 'guland': 'source-gl' };

function showLoader() { document.getElementById('mainLoader').classList.add('show'); }
function hideLoader() { document.getElementById('mainLoader').classList.remove('show'); }

function isCacheFresh(entry) {
  return entry && (Date.now() - entry.ts) < CACHE_TTL_MS;
}

async function fetchJSONCached(scope, url, useCache = true) {
  const cacheKey = `${scope}|${url}`;
  const cached = responseCache.get(cacheKey);
  if (useCache && isCacheFresh(cached)) {
    return cached.data;
  }

  if (requestControllers[scope]) {
    requestControllers[scope].abort();
  }

  const controller = new AbortController();
  requestControllers[scope] = controller;

  const res = await fetch(url, { signal: controller.signal });
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText}`);
  }
  const data = await res.json();
  responseCache.set(cacheKey, { ts: Date.now(), data });

  if (requestControllers[scope] === controller) {
    delete requestControllers[scope];
  }

  return data;
}

function activeTabId() {
  const active = document.querySelector('.tab-content.active');
  return active ? active.id.replace('tab-', '') : 'signals';
}

function switchTab(tabId, btn) {
  document.querySelectorAll('.nav-link').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
  if (btn) btn.classList.add('active');
  document.getElementById(`tab-${tabId}`).classList.add('active');

  if(tabId === 'market') {
    loadMarketCharts();
    loadTrendData();
  }
  if(tabId === 'all') {
    loadListings(1);
  }
}

function selectCity(btn) {
  document.querySelectorAll('.city-pill').forEach(p => p.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('cityInput').value = btn.dataset.city;
  updateWardFilters(globalWardsByCity, []);
  applyFilters();
}

function filterWards(query) {
  const q = query.toLowerCase().trim();
  document.querySelectorAll('#wardFilters .filter-option').forEach(label => {
    const text = label.textContent.toLowerCase();
    label.style.display = text.includes(q) ? '' : 'none';
  });
}

function getFilterQuery() {
  const form = document.getElementById('filterForm');
  const fd = new FormData(form);
  const params = new URLSearchParams();
  for (let [k, v] of fd.entries()) {
    params.append(k, v);
  }
  params.append('trend_period', trendPeriod);
  return params.toString();
}

function updateTrendPeriod(p, btn) {
  trendPeriod = p;
  document.querySelectorAll('.p-pill').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  
  currentFilters = getFilterQuery();
  loadTrendData(false);
}

function applyFilters() {
  currentFilters = getFilterQuery();
  currentPageNo = 1;
  initDashboard();
  
  const tab = activeTabId();
  if(tab === 'market') {
    loadMarketCharts(false);
    loadTrendData(false);
  }
  if(tab === 'all') {
    loadListings(1);
  }
}

function scheduleApplyFilters() {
  clearTimeout(filterDebounceTimer);
  filterDebounceTimer = setTimeout(applyFilters, 200);
}

async function initDashboard() {
  showLoader();
  try {
    const data = await fetchJSONCached('dashboard', `/api/dashboard?${currentFilters}`);
    
    // Update Stats
    document.getElementById('statTotal').innerText = data.stats.total;
    document.getElementById('statSignals').innerText = data.stats.signals;
    const el = document.getElementById('statNewRecent');
    if (el) el.innerText = data.stats.hot || 0;
    const bSig = document.getElementById('badgeSignals');
    const bTot = document.getElementById('badgeTotal');
    if (bSig) bSig.innerText = data.stats.signals;
    if (bTot) bTot.innerText = data.stats.total;
    
    // Update Wards based on City
    globalWardsByCity = data.wards_by_city;
    updateWardFilters(data.wards_by_city, data.active_wards);
    
    globalSignals = data.signals || [];
    sortAndRenderSignals();
    
  } catch (err) {
    if (err.name === 'AbortError') return;
    console.error(err);
    alert('Lỗi tải dữ liệu Dashboard');
  } finally {
    hideLoader();
  }
}

function setSortPill(btn) {
  document.querySelectorAll('.sort-pill').forEach(p => p.classList.remove('active'));
  btn.classList.add('active');
  sortAndRenderSignals();
}

function sortAndRenderSignals() {
  const activeBtn = document.querySelector('.sort-pill.active');
  if (!activeBtn) return;
  const val = activeBtn.dataset.sort;
  let sorted = [...globalSignals];

  if (val === 'mos_desc') {
    sorted.sort((a, b) => b.mos_pct - a.mos_pct);
  } else if (val === 'price_asc') {
    sorted.sort((a, b) => a.price_ty - b.price_ty);
  } else if (val === 'price_m2_asc') {
    sorted.sort((a, b) => (a.actual_ppm2 || 999) - (b.actual_ppm2 || 999));
  } else if (val === 'newest') {
    sorted.sort((a, b) => a.days_ago - b.days_ago);
  } else if (val === 'score_desc') {
    sorted.sort((a, b) => (b.signal_score || 0) - (a.signal_score || 0));
  }
  renderSignals(sorted);
}

function renderSignals(signals) {
  const grid = document.getElementById('signalsGrid');
  if (!signals || signals.length === 0) {
    grid.innerHTML = `
      <div style="grid-column: 1/-1; padding: 60px 20px; text-align: center; background: rgba(255,255,255,0.02); border: 1px dashed var(--border); border-radius: 16px; margin-top: 20px;">
        <div style="font-size: 3rem; margin-bottom: 16px; opacity: 0.8;">📡</div>
        <h3 style="color: var(--text); font-size: 1.2rem; margin-bottom: 8px;">Không tìm thấy Kèo Thơm nào</h3>
        <p style="color: var(--text-muted); font-size: 0.95rem; max-width: 400px; margin: 0 auto;">Radar chưa quét được tín hiệu nào khớp với bộ lọc hiện tại. Hãy thử nới lỏng bộ lọc ở menu bên trái!</p>
      </div>
    `;
    return;
  }

  grid.innerHTML = signals.map(x => {
    const fairPrice = x.fair_ppm2 ? (x.fair_ppm2 * x.area_m2 / 1000).toFixed(2) : '-';
    const profit = fairPrice !== '-' ? (parseFloat(fairPrice) - x.price_ty).toFixed(2) : '-';

    let timeStr = x.days_ago === 0 ? 'hôm nay' : `${x.days_ago} ngày trước`;
    let legalStr = x.has_so === 1 ? 'Sổ Hồng' : (x.has_so === 0 ? 'Chờ sổ' : 'Đang cập nhật');

    const roadTiers = {
      1: 'Mặt tiền',
      2: 'Đường nhựa',
      3: 'Hẻm xe hơi',
      4: 'Hẻm xe máy'
    };
    let roadStr = roadTiers[x.road_tier] || 'Chưa rõ';

    const safeTitle = String(x.title || '').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    const safeDesc = String(x.description || '').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    const imgSrc = x.imgs && x.imgs.length ? x.imgs[0] : PLACEHOLDER_IMG;
    const imgsJson = encodeURIComponent(JSON.stringify(x.imgs && x.imgs.length ? x.imgs : []));
    const dataAttr = `data-id="${x.id}" data-title="${safeTitle}" data-desc="${safeDesc}" data-imgs="${imgsJson}" data-price="${x.price_ty}" data-ppm2="${x.actual_ppm2}" data-fair="${fairPrice}" data-fppm2="${x.fair_ppm2}" data-area="${x.area_m2}" data-ward="${x.ward}" data-road="${roadStr}" data-time="${timeStr}" data-profit="${profit}" data-mos="${x.mos_pct}" data-source="${sourceNames[x.source] || x.source}" data-drop="${x.price_drop_pct || ''}" data-score="${x.signal_score || '-'}"`;

    const isNew = x.days_ago <= 3;
    const newBadgeHtml = isNew ? `<div class="new-badge"><svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg> MỚI</div>` : '';

    const srcName = sourceNames[x.source] || x.source;
    const dropBadge = x.price_dropped ? `<span class="sc-drop-tag"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 18 13.5 8.5 8.5 13.5 1 6"/></svg> Giảm ${x.drop_pct ? x.drop_pct + '%' : '2 lần'}</span>` : '';

    return `
      <div class="scard" onclick="openSignal(this)" ${dataAttr}>
        <div class="sc-img-wrap">
          <img class="sc-img" src="${imgSrc}" loading="lazy" alt="Img" onerror="this.onerror=null;this.src=PLACEHOLDER_IMG">
          <div class="mos-badge"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="23 18 13.5 8.5 8.5 13.5 1 6"/><polyline points="17 18 23 18 23 12"/></svg> -${x.mos_pct}%</div>
          ${newBadgeHtml}
          <div class="sc-img-tags">
            <span class="sc-source-tag">${srcName}</span>
            <span class="sc-time-tag"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg> ${timeStr}</span>
            ${dropBadge}
          </div>
        </div>
        <div class="sc-body">
          <div class="sc-title" title="${safeTitle}">${x.title}</div>

          <div class="price-container">
            <div class="price-actual">
              <span class="price-label price-label-actual">THỰC TẾ</span>
              <div class="price-val">${x.price_ty || '-'} tỷ</div>
              <div class="price-m2">${x.actual_ppm2 || '-'} tr/m²</div>
            </div>
            <div class="price-fair">
              <span class="price-label price-label-fair">FAIR VALUE AI</span>
              <div class="price-val-fair">${fairPrice} tỷ</div>
              <div class="price-m2">${x.fair_ppm2 || '-'} tr/m²</div>
            </div>
          </div>

          <div class="sc-meta-grid">
            <div class="meta-item"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg> ${x.ward}</div>
            <div class="meta-item"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/></svg> ${x.area_m2 || '-'} m²</div>
            <div class="meta-item"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" y1="22" x2="4" y2="15"/></svg> ${roadStr}</div>
            <div class="meta-item"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg> ${legalStr}</div>
          </div>

          <div class="sc-actions" onclick="event.stopPropagation()">
            <a href="https://zalo.me/0343216024" target="_blank" class="btn-zalo"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg> Zalo</a>
            <a href="/listing/${x.id}" target="_blank" class="btn-analyze"><svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg> Phân tích Deal</a>
          </div>
        </div>
      </div>
    `;
  }).join('');
}

// Slider state
let _smSlideIdx = 0;
let _smSlideImgs = [];

function slideSignal(dir) {
  if (_smSlideImgs.length <= 1) return;
  _smSlideIdx = (_smSlideIdx + dir + _smSlideImgs.length) % _smSlideImgs.length;
  document.getElementById('sm-slides').style.transform = `translateX(-${_smSlideIdx * 100}%)`;
  // Update counter
  document.getElementById('sm-img-count').innerText = `${_smSlideIdx + 1} / ${_smSlideImgs.length}`;
  // Update dots
  document.querySelectorAll('#sm-dots span').forEach((d, i) => {
    d.style.background = i === _smSlideIdx ? '#fff' : 'rgba(255,255,255,0.4)';
  });
}

function buildSlider(imgs) {
  _smSlideIdx = 0;
  _smSlideImgs = imgs.length ? imgs : [PLACEHOLDER_IMG];
  const slides = document.getElementById('sm-slides');
  const dots = document.getElementById('sm-dots');
  const counter = document.getElementById('sm-img-count');
  const prevBtn = document.getElementById('sm-prev');
  const nextBtn = document.getElementById('sm-next');

  // Build slides
  slides.style.transform = 'translateX(0)';
  slides.innerHTML = _smSlideImgs.map(src => `
    <div style="min-width:100%; height:100%; flex-shrink:0; background:#0f172a;">
      <img src="${src}" style="width:100%; height:100%; object-fit:contain; display:block; background:#0f172a;"
        onerror="this.onerror=null;this.src=PLACEHOLDER_IMG;">
    </div>`
  ).join('');

  // Dots
  dots.innerHTML = _smSlideImgs.length > 1
    ? _smSlideImgs.map((_, i) => `<span onclick="_smSlideIdx=${i-1}; slideSignal(1);" style="width:7px; height:7px; border-radius:50%; background:${i===0?'#fff':'rgba(255,255,255,0.4)'}; cursor:pointer; transition:background 0.2s; display:inline-block;"></span>`).join('')
    : '';

  // Arrows + counter
  const multi = _smSlideImgs.length > 1;
  prevBtn.style.display = multi ? 'flex' : 'none';
  nextBtn.style.display = multi ? 'flex' : 'none';
  counter.innerText = multi ? `1 / ${_smSlideImgs.length}` : '';
}

let smHistoryChart = null;

function openSignal(card) {
  const d = card.dataset;

  // Build image slider
  const imgs = d.imgs ? JSON.parse(decodeURIComponent(d.imgs)) : [];
  buildSlider(imgs);

  // Thumbnails
  const thumbsEl = document.getElementById('sm-thumbs');
  thumbsEl.innerHTML = imgs.length > 1
    ? imgs.map((src, i) => `<img src="${src}" onclick="_smSlideIdx=${i-1}; slideSignal(1);" onerror="this.style.display='none'">`).join('')
    : '';

  // Signal badge
  const mosNum = parseFloat(d.mos) || 0;
  const badgeLabel = mosNum >= 25 ? 'SUPER SIGNAL' : 'SIGNAL';
  document.getElementById('sm-signal-badge').innerHTML = `<span>${badgeLabel} · -${d.mos}%</span>`;

  // Title
  document.getElementById('sm-title').innerText = d.title;

  // Meta line
  document.getElementById('sm-meta-line').innerHTML = `<span>Đăng ${d.time}</span> · <span>${d.source}</span>`;

  // Description
  document.getElementById('sm-desc').innerText = d.desc || 'Không có mô tả.';

  // AI Assessment
  const aiSection = document.getElementById('sm-ai-section');
  const aiText = document.getElementById('sm-ai-text');
  const price = parseFloat(d.price) || 0;
  const fair = parseFloat(d.fair) || 0;
  const area = parseFloat(d.area) || 0;
  const dropInfo = d.drop ? `, đã giảm <b>${d.drop}%</b>` : '';
  if (fair > 0 && price > 0) {
    aiText.innerHTML = `Tín hiệu ngợp <b>cấp độ ${mosNum >= 25 ? 'cao' : 'trung bình'}</b>: giá chào thấp hơn fair value <b>${Math.round(mosNum)}%</b>${dropInfo}. Khu vực <b>${d.ward}</b>, ${d.road}. Diện tích ${area} m². Khuyến nghị xác minh chủ sở hữu, đàm phán thêm 2-5%.`;
    aiSection.style.display = 'block';
  } else {
    aiSection.style.display = 'none';
  }

  // Tags
  const tags = [
    { icon: '📐', label: `${d.area} m²` },
    { icon: '📍', label: d.ward },
    { icon: '🛣️', label: d.road },
    { icon: '📊', label: `Score: ${d.score || '-'}` },
  ];
  document.getElementById('sm-tags').innerHTML = tags
    .map(t => `<span>${t.icon} ${t.label}</span>`).join('');

  // Links
  document.getElementById('sm-zalo').href = 'https://zalo.me/0343216024';
  document.getElementById('sm-detail').href = `/listing/${d.id}`;

  // Load price history + comps
  loadSignalHistory(d.id, price, area, d.ward);

  document.getElementById('signalModal').style.display = 'flex';
}

async function loadSignalHistory(listingId, currentPrice, area, ward) {
  const historyEl = document.getElementById('sm-price-history');
  const compsBody = document.getElementById('sm-comps-body');
  historyEl.innerHTML = '';
  compsBody.innerHTML = '';

  // Destroy old chart
  if (smHistoryChart) { smHistoryChart.destroy(); smHistoryChart = null; }

  try {
    const res = await fetch(`/api/history/${listingId}`);
    const data = await res.json();

    // Price history rows with % change
    if (data.history && data.history.length > 0) {
      let prevPrice = null;
      historyEl.innerHTML = data.history.map(h => {
        let changeHtml = '';
        if (prevPrice && h.price_ty) {
          const pct = ((h.price_ty - prevPrice) / prevPrice * 100).toFixed(1);
          changeHtml = `<span class="ph-change">${pct}%</span>`;
        }
        prevPrice = h.price_ty;
        return `<div class="ph-row"><span class="ph-date">📅 ${h.date}</span><span class="ph-price">${h.price_ty} tỷ</span>${changeHtml}</div>`;
      }).join('');

      // Mini chart
      const ctx = document.getElementById('sm-history-chart').getContext('2d');
      smHistoryChart = new Chart(ctx, {
        type: 'line',
        data: {
          labels: data.history.map(h => h.date),
          datasets: [{
            data: data.history.map(h => h.price_ty),
            borderColor: '#6366f1', backgroundColor: 'rgba(99,102,241,0.1)',
            fill: true, tension: 0.3, pointRadius: 4, pointBackgroundColor: '#6366f1', borderWidth: 2
          }]
        },
        options: {
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            x: { grid: { color: 'rgba(0,0,0,0.05)' }, ticks: { font: { size: 10 } } },
            y: { grid: { color: 'rgba(0,0,0,0.05)', drawBorder: false }, ticks: { font: { size: 10 } } }
          }
        }
      });
    }

    // COMPS — similar listings in same ward
    if (data.comps && data.comps.length > 0) {
      compsBody.innerHTML = data.comps.map(c =>
        `<tr><td>${c.address || c.title || '-'}</td><td>${c.area_m2 || '-'} m²</td><td><b>${c.price_ty} tỷ</b></td><td>${c.date || '-'}</td></tr>`
      ).join('');
    }
    // Add current deal row
    compsBody.innerHTML += `<tr><td>Deal hiện tại</td><td>${area} m²</td><td><b>${currentPrice} tỷ</b></td><td>Now</td></tr>`;

  } catch (err) {
    console.error('History load error:', err);
  }
}

async function loadMarketCharts(useCache = true) {
  const container = document.getElementById('heatmapContainer');
  const gapContainer = document.getElementById('priceGapContainer');
  if (container) container.classList.add('loading');
  if (gapContainer) gapContainer.classList.add('loading');
  try {
    const data = await fetchJSONCached('market', `/api/heatmap?${currentFilters}`, useCache);
    renderHeatmap(data);
    renderPriceGapChart(data);
  } catch (err) {
    if (err.name !== 'AbortError') console.error("Market charts error:", err);
  } finally {
    if (container) container.classList.remove('loading');
    if (gapContainer) gapContainer.classList.remove('loading');
  }
}

async function loadHeatmap() {
  const container = document.getElementById('heatmapContainer');
  container.classList.add('loading');
  try {
    const data = await fetchJSONCached('market', `/api/heatmap?${currentFilters}`);
    renderHeatmap(data);
  } catch (err) {
    if (err.name !== 'AbortError') console.error("Heatmap error:", err);
  } finally {
    container.classList.remove('loading');
  }
}

function renderHeatmap(data) {
    if (treemapInstance) {
      treemapInstance.destroy();
      treemapInstance = null;
    }

    const canvas = document.getElementById('treemapChart');
    const container = document.getElementById('heatmapContainer');
    const oldEmpty = document.getElementById('heatmapEmptyState');
    if (oldEmpty) oldEmpty.remove();

    const opportunityData = (data || []).filter(d => (d.deal_count || 0) > 0 && (d.median_mos || 0) > 0);
    if (canvas) canvas.style.display = '';

    if (opportunityData.length === 0) {
      if (canvas) canvas.style.display = 'none';
      if (container) {
        container.insertAdjacentHTML('beforeend', `
          <div id="heatmapEmptyState" style="position:absolute; inset:0; display:flex; align-items:center; justify-content:center; text-align:center; color:var(--text-muted); padding:24px;">
            <div>
              <div style="font-size:2rem; margin-bottom:10px;">📡</div>
              <div style="font-weight:800; color:var(--text); margin-bottom:4px;">Chưa có deal MOS dương</div>
              <div style="font-size:0.85rem;">Hãy nới filter phường, nguồn tin hoặc loại hình để radar có thêm mẫu signal.</div>
            </div>
          </div>
        `);
      }
      return;
    }
    
    const ctx = canvas.getContext('2d');
    
    // Gradient coloring based on avg_price
    treemapInstance = new Chart(ctx, {
      type: 'treemap',
      data: {
        datasets: [{
          tree: opportunityData,
          key: 'deal_count',
          spacing: 2,
          borderWidth: 0,
          backgroundColor(ctx) {
            if (ctx.type !== 'data') return 'transparent';
            const d = ctx.raw._data || ctx.raw;
            const mos = d ? (d.median_mos || 0) : 0;
            const ratio = Math.min(1, mos / 50);
            return `rgba(16, 185, 129, ${0.35 + ratio * 0.65})`;
          },
          labels: {
            display: true,
            align: 'center',
            position: 'center',
            color: 'white',
            font: { family: 'Inter', size: 14, weight: 'bold' },
            formatter(ctx) {
              if (ctx.type !== 'data') return '';
              const d = ctx.raw._data || ctx.raw;
              if (!d || !d.ward) return '';
              const mos = d.median_mos || 0;
              return [d.ward, `${d.deal_count || 0} deal`, `MOS trung vị +${mos}%`];
            }
          }
        }]
      },
      options: {
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: (items) => {
                const d = items[0].raw._data || items[0].raw;
                return d ? d.ward : '';
              },
              label: (item) => {
                const d = item.raw._data || item.raw;
                if (!d) return '';
                return [
                  `Deal signal: ${d.deal_count || 0} tin`,
                  `MOS trung vị: +${d.median_mos || 0}%`,
                  `MOS trung bình: +${d.avg_signal_mos || 0}%`,
                  `Tỷ lệ deal: ${d.signal_rate || 0}%`,
                  `Tổng tin hợp lệ: ${d.total_count || 0}`,
                  `Giá TB: ${d.avg_price || 0} tr/m²`
                ];
              }
            }
          }
        }
      }
    });
}

async function loadPriceGapChart() {
  const container = document.getElementById('priceGapContainer');
  if (!container) return;
  container.classList.add('loading');
  try {
    const data = await fetchJSONCached('market', `/api/heatmap?${currentFilters}`);
    renderPriceGapChart(data);
  } catch (err) {
    if (err.name !== 'AbortError') console.error('Price gap chart error:', err);
  } finally {
    container.classList.remove('loading');
  }
}

function renderPriceGapChart(data) {
    if (priceGapInstance) { priceGapInstance.destroy(); priceGapInstance = null; }
    if (!data || data.length === 0) return;

    // Sort by avg_price_ty descending, take top wards with fair value data
    const filtered = data.filter(d => d.avg_price_ty > 0 && d.avg_fair_ty > 0)
      .sort((a, b) => b.avg_price_ty - a.avg_price_ty)
      .slice(0, 10);

    if (filtered.length === 0) return;

    const ctx = document.getElementById('priceGapChart').getContext('2d');
    priceGapInstance = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: filtered.map(d => d.ward),
        datasets: [
          {
            label: 'Giá chào TB',
            data: filtered.map(d => d.avg_price_ty),
            backgroundColor: '#6366f1',
            borderRadius: 4, barPercentage: 0.7, categoryPercentage: 0.8
          },
          {
            label: 'Định giá AI',
            data: filtered.map(d => d.avg_fair_ty),
            backgroundColor: '#10b981',
            borderRadius: 4, barPercentage: 0.7, categoryPercentage: 0.8
          }
        ]
      },
      options: {
        maintainAspectRatio: false,
        plugins: {
          legend: { position: 'top', labels: { font: { family: 'Plus Jakarta Sans', size: 12, weight: '600' }, usePointStyle: true, pointStyle: 'rectRounded' } },
          tooltip: {
            callbacks: {
              label: (item) => `${item.dataset.label}: ${item.raw.toFixed(2)} tỷ`
            }
          }
        },
        scales: {
          x: { grid: { display: false }, ticks: { font: { family: 'Plus Jakarta Sans', size: 11 } } },
          y: { grid: { color: 'rgba(0,0,0,0.06)' }, ticks: { font: { size: 10 }, callback: v => v + ' tỷ' }, beginAtZero: true }
        }
      }
    });
}

async function loadTrendData(useCache = true) {
  const container = document.getElementById('trendContainer');
  if (!container) return;
  container.classList.add('loading');
  try {
    const data = await fetchJSONCached('trend', `/api/trends?${currentFilters}`, useCache);
    renderTrendChart(data.trend_data || {});
  } catch (err) {
    if (err.name !== 'AbortError') console.error('Trend chart error:', err);
  } finally {
    container.classList.remove('loading');
  }
}

function renderTrendChart(trendData) {
  const ctx = document.getElementById('trendChart').getContext('2d');
  if (trendInstance) {
    trendInstance.destroy();
    trendInstance = null;
  }
  
  if (!trendData || Object.keys(trendData).length === 0) {
    return;
  }
  
  const datasets = [];
  const colors = ['#4f46e5', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4', '#f97316'];
  const allTimeKeys = new Set();
  
  for (const w in trendData) {
    trendData[w].forEach(d => allTimeKeys.add(d.week));
  }
  const sortedKeys = Array.from(allTimeKeys).sort();
  const labels = sortedKeys.map(w => w.replace('D-', '').replace('M-', ''));
  
  let i = 0;
  for (const ward in trendData) {
    const data = trendData[ward];
    const dataMap = {};
    data.forEach(d => dataMap[d.week] = d.median_ppm2);
    const wardData = sortedKeys.map(w => dataMap[w] || null);
    
    const color = colors[i % colors.length];
    datasets.push({
      label: ward, 
      data: wardData,
      borderColor: color, 
      backgroundColor: color + '10',
      borderWidth: 3, 
      tension: 0.4, 
      fill: false,
      pointRadius: sortedKeys.length > 30 ? 0 : 4, 
      pointHoverRadius: 8,
      spanGaps: true,
      borderCapStyle: 'round'
    });
    i++;
  }
  
  Chart.defaults.font.family = "'Inter', sans-serif";
  trendInstance = new Chart(ctx, {
    type: 'line',
    data: { labels, datasets },
    options: {
      animation: { duration: 0 }, // Disable animation to prevent "jumping"
      responsive: true, 
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: { 
        legend: { 
          position: 'bottom',
          labels: { boxWidth: 12, padding: 20, font: { size: 11, weight: '600' } }
        },
        tooltip: {
          padding: 12,
          backgroundColor: 'rgba(0,0,0,0.8)',
          titleFont: { size: 14, weight: 'bold' },
          bodyFont: { size: 13 },
          cornerRadius: 8
        }
      },
      scales: {
        y: { 
          title: { display: true, text: 'Giá (tr/m²)', font: { weight: '600' } },
          grid: { color: 'rgba(255,255,255,0.05)' },
          ticks: { font: { size: 11 } }
        },
        x: { 
          grid: { display: false },
          ticks: { 
            font: { size: 10 },
            maxRotation: 45,
            autoSkip: true,
            maxTicksLimit: 12
          }
        }
      }
    }
  });
}

async function loadListings(page) {
  const tbody = document.getElementById('listingsTableBody');
  tbody.classList.add('loading');
  try {
    const data = await fetchJSONCached('listings', `/api/listings?${currentFilters}&page=${page}&limit=50`);
    
    currentPageNo = data.page;
    document.getElementById('currentPage').innerText = data.page;
    document.getElementById('totalPages').innerText = data.pages;
    document.getElementById('btnPrevPage').disabled = (data.page <= 1);
    document.getElementById('btnNextPage').disabled = (data.page >= data.pages);
    
    const tbody = document.getElementById('listingsTableBody');
    tbody.innerHTML = data.listings.map(x => {
      const fair = x.fair_ppm2 ? (x.fair_ppm2 * x.area_m2 / 1000).toFixed(2) : '-';
      return `
        <tr>
          <td><span style="font-size:0.75rem; font-weight:700; color:var(--text-muted);">${x.prop_type}</span></td>
          <td><span style="background:#f1f5f9; padding:4px 8px; border-radius:6px; font-weight:600; font-size:0.8rem;">${x.ward}</span></td>
          <td><img src="${x.imgs && x.imgs.length ? x.imgs[0] : PLACEHOLDER_IMG}" class="td-img" loading="lazy" onerror="this.onerror=null;this.src=PLACEHOLDER_IMG"></td>
          <td style="font-weight:700;">${x.area_m2 ? x.area_m2 + ' m²' : '-'}</td>
          <td>
            <div style="color:var(--accent); font-weight:800; font-size:1rem;">${x.price_ty ? x.price_ty + ' tỷ' : '-'}</div>
            <div style="font-size:0.75rem; color:var(--text-muted); margin-top:2px;">${x.price_per_m2 || '-'} tr/m²</div>
          </td>
          <td>
            <div style="color:var(--primary); font-weight:800;">${fair !== '-' ? fair + ' tỷ' : '-'}</div>
            <div style="font-size:0.75rem; color:var(--primary); opacity:0.8; margin-top:2px;">${x.fair_ppm2 || '-'} tr/m²</div>
          </td>
          <td style="max-width: 300px;">
            <div class="td-title" title="${String(x.title || '').replace(/"/g, '&quot;')}">${x.title}</div>
            <div class="td-desc" title="${String(x.description || '').replace(/"/g, '&quot;')}">${x.description}</div>
          </td>
          <td style="text-align:center;"><a href="/listing/${x.id}" target="_blank" style="color:var(--primary); font-weight:900; font-size:1.2rem; text-decoration:none;">↗</a></td>
        </tr>
      `;
    }).join('');
    
  } catch(e) {
    if (e.name !== 'AbortError') console.error(e);
  } finally {
    tbody.classList.remove('loading');
  }
}

function changePage(dir) {
  loadListings(currentPageNo + dir);
}

async function openHistory(id, title) {
  document.getElementById('historyTitle').innerText = `Lịch sử giá: ${title}`;
  document.getElementById('historyModal').style.display = 'flex';
  
  try {
    const res = await fetch(`/api/history/${id}`);
    const data = await res.json();
    
    if (historyChartInstance) historyChartInstance.destroy();
    
    const ctx = document.getElementById('historyChartCanvas').getContext('2d');
    historyChartInstance = new Chart(ctx, {
      type: 'line',
      data: {
        labels: (data.history || data).map(d => d.date),
        datasets: [{
          label: 'Giá (tỷ)',
          data: (data.history || data).map(d => d.price_ty),
          borderColor: '#10b981', backgroundColor: 'rgba(16, 185, 129, 0.1)',
          borderWidth: 3, tension: 0.1, fill: true, stepped: true,
          pointRadius: 6, pointHoverRadius: 8,
        }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          y: { title: { display: true, text: 'Tổng giá (tỷ)' } },
          x: { grid: { display: false } }
        }
      }
    });
  } catch(e) {
    console.error(e);
  }
}

function closeModal(id) {
  document.getElementById(id).style.display = 'none';
}

window.onclick = function(event) {
  if (event.target.classList.contains('modal')) {
    event.target.style.display = 'none';
  }
}

function updateWardFilters(wardsByCity, activeWards) {
  const selectedCity = document.getElementById('cityInput').value;
  const wards = wardsByCity[selectedCity] || [];
  const container = document.getElementById('wardFilters');
  const searchInput = document.getElementById('wardSearch');
  if (searchInput) searchInput.value = '';
  const selected = new Set(activeWards || []);
  const shouldCheckAll = selected.size === 0;

  container.innerHTML = wards.map(w => {
    const checked = shouldCheckAll || selected.has(w) ? 'checked' : '';
    return `
      <label class="filter-option">
        <input type="checkbox" name="ward" value="${w}" ${checked}> ${w}
      </label>
    `;
  }).join('');
}

// Global listener for Filter changes (Auto-apply)
document.addEventListener('change', (e) => {
  if (e.target.closest('#filterForm')) {
    scheduleApplyFilters();
  }
});

// Init on load
document.addEventListener('DOMContentLoaded', () => {
  if(window.location.search) {
    currentFilters = window.location.search.substring(1);
    initDashboard();
  } else {
    detectLocation();
  }
});

// AI Chat Logic
let chatHistory = [];

function toggleChat() {
  const win = document.getElementById('chatWindow');
  win.style.display = win.style.display === 'flex' ? 'none' : 'flex';
  if (win.style.display === 'flex') {
    document.getElementById('chatInput').focus();
  }
}

async function sendMessage() {
  const input = document.getElementById('chatInput');
  const msg = input.value.trim();
  if (!msg) return;

  // Add user message to UI
  appendMessage('user', msg);
  input.value = '';

  // Add loading indicator
  const loadingId = 'loading-' + Date.now();
  const msgContainer = document.getElementById('chatMessages');
  const loadingDiv = document.createElement('div');
  loadingDiv.className = 'message bot';
  loadingDiv.id = loadingId;
  loadingDiv.innerText = 'RadarBDS AI đang trả lời...';
  msgContainer.appendChild(loadingDiv);
  msgContainer.scrollTop = msgContainer.scrollHeight;

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: msg, history: chatHistory })
    });
    const data = await res.json();
    
    // Remove loading and show response
    loadingDiv.remove();
    appendMessage('bot', data.response);
    
    // Update history
    chatHistory.push({ role: 'user', content: msg });
    chatHistory.push({ role: 'assistant', content: data.response });
    if (chatHistory.length > 10) chatHistory = chatHistory.slice(-10); // Keep last 5 turns
    
  } catch (err) {
    loadingDiv.innerText = 'Lỗi kết nối. Vui lòng thử lại.';
    console.error(err);
  }
}

function appendMessage(role, text) {
  const container = document.getElementById('chatMessages');
  const div = document.createElement('div');
  div.className = `message ${role}`;
  div.innerText = text;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

