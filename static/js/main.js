// Init theme on load before body renders
const savedTheme = localStorage.getItem('radar_theme') || 'dark';
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

const sourceNames = { 'batdongsan': 'BDS.vn', 'facebook': 'Facebook', 'guland': 'Guland' };
const sourceClasses = { 'batdongsan': 'source-bds', 'facebook': 'source-fb', 'guland': 'source-gl' };

function showLoader() { document.getElementById('mainLoader').classList.add('show'); }
function hideLoader() { document.getElementById('mainLoader').classList.remove('show'); }

function switchTab(tabId, btn) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
  if (btn) btn.classList.add('active');
  document.getElementById(`tab-${tabId}`).classList.add('active');
  
  if(tabId === 'market' && !treemapInstance) {
    loadHeatmap();
  }
  if(tabId === 'all' && document.getElementById('listingsTableBody').innerHTML.trim() === "") {
    loadListings(1);
  }
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
  
  // Only reload the trend chart to prevent global "jumping"
  const container = document.getElementById('trendContainer');
  container.classList.add('loading');
  
  fetch(`/api/dashboard?${getFilterQuery()}`)
    .then(res => res.json())
    .then(data => {
      renderTrendChart(data.trend_data);
    })
    .finally(() => {
      container.classList.remove('loading');
    });
}

function applyFilters() {
  currentFilters = getFilterQuery();
  currentPageNo = 1;
  initDashboard();
  
  // Reload other tabs if they were already loaded
  if(document.getElementById('tab-market').classList.contains('active') || treemapInstance) {
    loadHeatmap();
  }
  if(document.getElementById('tab-all').classList.contains('active') || document.getElementById('listingsTableBody').innerHTML.trim() !== "") {
    loadListings(1);
  }
}

async function initDashboard() {
  showLoader();
  try {
    const res = await fetch(`/api/dashboard?${currentFilters}`);
    const data = await res.json();
    
    // Update Stats
    document.getElementById('statTotal').innerText = data.stats.total;
    document.getElementById('statSignals').innerText = data.stats.signals;
    document.getElementById('badgeTotal').innerText = data.stats.total;
    document.getElementById('badgeSignals').innerText = data.stats.signals;
    const now = new Date();
    document.getElementById('lastUpdated').innerText = `Cập nhật lúc: ${now.getHours()}:${String(now.getMinutes()).padStart(2, '0')}`;
    
    // Update Wards based on City
    globalWardsByCity = data.wards_by_city;
    updateWardFilters(data.wards_by_city, data.active_wards);
    
    globalSignals = data.signals || [];
    sortAndRenderSignals();
    renderTrendChart(data.trend_data);
    
  } catch (err) {
    console.error(err);
    alert('Lỗi tải dữ liệu Dashboard');
  }
  hideLoader();
}

function sortAndRenderSignals() {
  const sorter = document.getElementById('signalSorter');
  if (!sorter) return;
  const val = sorter.value;
  let sorted = [...globalSignals];
  
  if (val === 'mos_desc') {
    sorted.sort((a, b) => b.mos_pct - a.mos_pct);
  } else if (val === 'price_asc') {
    sorted.sort((a, b) => a.price_ty - b.price_ty);
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
        <div style="font-size: 3rem; margin-bottom: 16px; opacity: 0.8; animation: pulse 2s infinite;">📡</div>
        <h3 style="color: var(--text); font-size: 1.2rem; margin-bottom: 8px;">Không tìm thấy Kèo Thơm nào</h3>
        <p style="color: var(--text-muted); font-size: 0.95rem; max-width: 400px; margin: 0 auto;">Radar chưa quét được tín hiệu nào khớp với bộ lọc hiện tại của bạn. Hãy thử nới lỏng bộ lọc ở menu bên trái nhé!</p>
      </div>
    `;
    return;
  }
  
  grid.innerHTML = signals.map(x => {
    const fairPrice = x.fair_ppm2 ? (x.fair_ppm2 * x.area_m2 / 1000).toFixed(2) : '-';
    const srcClass = sourceClasses[x.source] || 'source-fb';
    const mosClass = x.mos_pct >= 25 ? '' : 'low';
    const profit = fairPrice !== '-' ? (parseFloat(fairPrice) - x.price_ty).toFixed(2) : '-';
    const profitBadgeHtml = profit !== '-' ? `<div class="profit-badge">Hời ~ ${profit} tỷ</div>` : '';
    const dropBadgeHtml = x.price_dropped === 1 ? `<div class="drop-badge">📉 Giảm ${x.price_drop_pct ? x.price_drop_pct + '%' : 'giá'}</div>` : '';
    
    let timeStr = x.days_ago === 0 ? 'hôm nay' : `${x.days_ago} ngày trước`;
    let legalStr = x.has_so === 1 ? '📜 Sổ riêng' : (x.has_so === 0 ? '📄 Chờ sổ' : '📜 PL (Đang cập nhật)');
    
    const roadTiers = {
      1: '🛣️ Mặt tiền lớn',
      2: '🛣️ Mặt tiền nhựa/DX',
      3: '🚗 Hẻm xe hơi',
      4: '🛵 Hẻm xe máy'
    };
    let roadStr = roadTiers[x.road_tier] || '🚗 Đường (Chưa rõ)';
    
    const safeTitle = String(x.title || '').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    const safeDesc = String(x.description || '').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    const imgSrc = x.imgs && x.imgs.length ? x.imgs[0] : '';
    const imgsJson = encodeURIComponent(JSON.stringify(x.imgs && x.imgs.length ? x.imgs : []));
    const dataAttr = `data-id="${x.id}" data-title="${safeTitle}" data-desc="${safeDesc}" data-imgs="${imgsJson}" data-price="${x.price_ty}" data-ppm2="${x.actual_ppm2}" data-fair="${fairPrice}" data-fppm2="${x.fair_ppm2}" data-area="${x.area_m2}" data-ward="${x.ward}" data-road="${roadStr}" data-time="${timeStr}" data-profit="${profit}" data-mos="${x.mos_pct}" data-source="${sourceNames[x.source] || x.source}" data-drop="${x.price_drop_pct || ''}" data-score="${x.signal_score || '-'}"`;
    
    const isNew = x.days_ago <= 3;
    const newBadgeHtml = isNew ? `<div style="position:absolute; top:-5px; right:-5px; background:linear-gradient(135deg,#ef4444,#b91c1c); color:#fff; font-size:0.65rem; font-weight:800; padding:4px 10px; border-radius:8px; z-index:10; box-shadow:0 0 12px rgba(239,68,68,0.8); animation:pulse 2s infinite;">MỚI 🔥</div>` : '';
    const glowStyle = isNew ? `box-shadow: 0 0 0 2px rgba(239,68,68,0.5), 0 4px 12px rgba(0,0,0,0.1);` : ``;

    return `
      <div class="scard" onclick="openSignal(this)" style="${glowStyle}" ${dataAttr}>
        <div class="sc-img-wrap">
          <img class="sc-img" src="${imgSrc}" loading="lazy" alt="Img" onerror="this.src='https://placehold.co/400x300/e2e8f0/94a3b8?text=No+Image'">
          ${newBadgeHtml}
          <div class="mos-badge">-${x.mos_pct}%</div>
          ${x.price_dropped === 1 ? `<div class="drop-badge">Giảm ${x.price_drop_pct ? x.price_drop_pct + '%' : 'giá'}</div>` : ''}
          <div class="source-badge">MỚI - ${sourceNames[x.source] || x.source}</div>
        </div>
        <div class="sc-body">
          <div class="sc-title" title="${safeTitle}">${x.title}</div>
          
          <div class="price-container">
            <div class="price-actual">
              <span class="price-label">GIÁ CHỐT (THỰC TẾ)</span>
              <div class="price-val">${x.price_ty} tỷ</div>
              <div class="price-m2">~${x.actual_ppm2} tr/m²</div>
            </div>
            <div class="price-fair">
              <span class="price-label">ĐỊNH GIÁ AI</span>
              <div class="price-val-fair">${fairPrice} tỷ</div>
              <div class="price-m2">~${x.fair_ppm2 || '-'} tr/m²</div>
            </div>
          </div>

          <div class="sc-meta-grid">
            <div class="meta-item">📍 ${x.ward}</div>
            <div class="meta-item">📐 ${x.area_m2} m²</div>
            <div class="meta-item">${roadStr.split(' ')[0]} ${roadStr.split(' ').slice(1).join(' ')}</div>
            <div class="meta-item">${legalStr.split(' ')[0]} ${legalStr.split(' ').slice(1).join(' ')}</div>
          </div>

          <div class="sc-actions" onclick="event.stopPropagation()">
            <a href="https://zalo.me/0343216024" target="_blank" class="btn-zalo">💬 Zalo tư vấn</a>
            <a href="/listing/${x.id}" target="_blank" class="btn-analyze">Phân tích Deal</a>
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
  _smSlideImgs = imgs.length ? imgs : [''];
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
        onerror="this.style.display='none'; this.parentElement.style.background='#1e293b';">
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

function openSignal(card) {
  const d = card.dataset;
  
  // Build image slider
  const imgs = d.imgs ? JSON.parse(decodeURIComponent(d.imgs)) : [];
  buildSlider(imgs);
  
  // Title
  document.getElementById('sm-title').innerText = d.title;
  
  // Price
  document.getElementById('sm-price').innerText = `${d.price} tỷ`;
  document.getElementById('sm-ppm2').innerText = `${d.ppm2} tr/m²`;
  document.getElementById('sm-fair').innerText = `${d.fair} tỷ`;
  document.getElementById('sm-fppm2').innerText = `${d.fppm2} tr/m²`;
  
  // MOS badge
  const mosBadge = document.getElementById('sm-mos-badge');
  mosBadge.innerText = `-${d.mos}% MOS`;
  const mosNum = parseFloat(d.mos);
  mosBadge.style.background = mosNum >= 25
    ? 'linear-gradient(135deg,#10b981,#047857)'
    : 'linear-gradient(135deg,#f59e0b,#b45309)';
  
  // Profit badge
  const profitEl = document.getElementById('sm-profit-badge');
  const profitVal = parseFloat(d.profit);
  if (d.profit !== '-' && profitVal > 0) {
    profitEl.innerText = `Hời ~ ${d.profit} tỷ`;
    profitEl.style.display = 'inline-block';
  } else { profitEl.style.display = 'none'; }
  
  // Drop badge
  const dropEl = document.getElementById('sm-drop-badge');
  if (d.drop) {
    dropEl.innerText = `📉 Giảm ${d.drop}%`;
    dropEl.style.display = 'inline-block';
  } else { dropEl.style.display = 'none'; }
  
  // Source badge
  const srcBadge = document.getElementById('sm-source-badge');
  srcBadge.innerText = d.source;
  const srcColors = { 'BDS.vn': '#e11d48', 'Facebook': '#1877f2', 'Guland': '#f97316' };
  srcBadge.style.background = srcColors[d.source] || '#6366f1';
  
  // Tags
  const tags = [
    { icon: '📐', label: `${d.area} m²` },
    { icon: '📍', label: d.ward },
    { icon: '', label: d.road },
    { icon: '⏳', label: `Đăng ${d.time}` },
    { icon: '📊', label: `Signal Score: ${d.score || '-'}` },
  ];
  document.getElementById('sm-tags').innerHTML = tags
    .map(t => `<span style="background:rgba(255,255,255,0.05); border:1px solid var(--border); border-radius:7px; padding:4px 10px; font-size:0.78rem; color:var(--text-muted);">${t.icon} ${t.label}</span>`)
    .join('');
  
  // Description
  document.getElementById('sm-desc').innerText = d.desc || 'Không có mô tả.';
  
  // Links
  document.getElementById('sm-zalo').href = 'https://zalo.me/0343216024';
  document.getElementById('sm-detail').href = `/listing/${d.id}`;
  
  document.getElementById('signalModal').style.display = 'flex';
}

async function loadHeatmap() {
  const container = document.getElementById('heatmapContainer');
  container.classList.add('loading');
  try {
    const res = await fetch(`/api/heatmap?${currentFilters}`);
    const data = await res.json();
    
    if (treemapInstance) {
      treemapInstance.destroy();
      treemapInstance = null;
    }

    if (!data || data.length === 0) return;
    
    const ctx = document.getElementById('treemapChart').getContext('2d');
    
    // Gradient coloring based on avg_price
    treemapInstance = new Chart(ctx, {
      type: 'treemap',
      data: {
        datasets: [{
          tree: data,
          key: 'count',       // Box size based on number of listings
          groups: ['ward'],   // Group by ward
          spacing: 2,
          borderWidth: 0,
          backgroundColor(ctx) {
            if (ctx.type !== 'data') return 'transparent';
            const d = ctx.raw._data || ctx.raw;
            const avgMos = d ? d.avg_mos : 0;
            if (avgMos === 0) return 'rgba(156, 163, 175, 0.5)'; // Gray for neutral/no-data
            // MOS > 0% is good (green), < 0% is bad (red)
            if (avgMos > 0) {
                const ratio = Math.min(1, avgMos / 30); // Max intensity at 30% MOS
                return `rgba(16, 185, 129, ${0.4 + ratio * 0.6})`; // Green
            } else {
                const ratio = Math.min(1, Math.abs(avgMos) / 20); // Max intensity at -20% MOS
                return `rgba(239, 68, 68, ${0.4 + ratio * 0.6})`; // Red
            }
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
              const mosStr = d.avg_mos > 0 ? `+${d.avg_mos}%` : `${d.avg_mos}%`;
              return [d.ward, `${d.avg_price || 0} tr/m²`, `MOS: ${mosStr}`];
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
                  `Giá TB: ${d.avg_price || 0} tr/m²`,
                  `Cơ hội (MOS): ${d.avg_mos || 0}%`,
                  `Số lượng: ${d.count || 0} tin`
                ];
              }
            }
          }
        }
      }
    });
    
  } catch (err) {
    console.error("Heatmap error:", err);
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
    const res = await fetch(`/api/listings?${currentFilters}&page=${page}&limit=50`);
    const data = await res.json();
    
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
          <td><img src="${x.imgs && x.imgs.length ? x.imgs[0] : ''}" class="td-img" loading="lazy" onerror="this.style.display='none'"></td>
          <td style="font-weight:700;">${x.area_m2} m²</td>
          <td>
            <div style="color:var(--accent); font-weight:800; font-size:1rem;">${x.price_ty} tỷ</div>
            <div style="font-size:0.75rem; color:var(--text-muted); margin-top:2px;">${x.price_per_m2 || '-'} tr/m²</div>
          </td>
          <td>
            <div style="color:var(--primary); font-weight:800;">${fair} tỷ</div>
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
    console.error(e);
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
        labels: data.map(d => d.date),
        datasets: [{
          label: 'Giá (tỷ)',
          data: data.map(d => d.price_ty),
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
  const selectedCity = document.querySelector('input[name="city"]:checked').value;
  const wards = wardsByCity[selectedCity] || [];
  const container = document.getElementById('wardFilters');
  
  container.innerHTML = wards.map(w => {
    let checked = false;
    let disabled = false;
    


    // Check if current activeWards actually belong to the current city
    const hasValidActiveWard = activeWards && activeWards.some(aw => wards.includes(aw));
    
    if (hasValidActiveWard && !disabled) {
      checked = activeWards.includes(w);
    } else if (selectedCity === "THỦ DẦU MỘT" && w === "Tân An") {
      checked = true; // Default fallback
    } else if (selectedCity === "BẾN CÁT" && w === "Mỹ Phước 3") {
      checked = true; // Default fallback for Bến Cát
    }
    
    return `
      <label class="filter-option ${disabled ? 'disabled' : ''}">
        <input type="checkbox" name="ward" value="${w}" ${checked ? 'checked' : ''} ${disabled ? 'disabled' : ''}> ${w}
      </label>
    `;
  }).join('');
}

// Global listener for Filter changes (Auto-apply)
document.addEventListener('change', (e) => {
  // Check if the change happened inside the filter form
  if (e.target.closest('#filterForm')) {
    if (e.target.name === 'city') {
      // Update the UI ward options with empty activeWards → triggers default selection
      updateWardFilters(globalWardsByCity, []);
    }
    // Auto-apply filters immediately so data loads
    applyFilters();
  }
});

// Init on load
document.addEventListener('DOMContentLoaded', () => {
  // Try to detect location automatically
  detectLocation();
  
  if(window.location.search) {
    currentFilters = window.location.search.substring(1);
  } else {
    currentFilters = getFilterQuery();
  }
  initDashboard();
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

