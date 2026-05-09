function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebarOverlay');
    sidebar.classList.toggle('show');
    overlay.classList.toggle('show');
}

// Global State
let globalSignals = [];
let globalWardsByCity = {
  "THỦ DẦU MỘT": ["Tân An", "Tương Bình Hiệp", "Hiệp An", "Chánh Mỹ", "Phú Mỹ", "Phú Tân", "Chánh Nghĩa", "Định Hòa", "Phú Thọ", "Phú Hòa", "Phú Cường", "Hiệp Thành", "Phú Lợi"],
  "BẾN CÁT": ["Phú An", "An Tây", "An Điền", "Thới Hòa", "Mỹ Phước", "Mỹ Phước 1", "Mỹ Phước 2", "Mỹ Phước 3", "Mỹ Phước 4", "Chánh Phú Hòa", "Tân Định", "Hòa Lợi"]
};
let currentFilters = `city=${encodeURIComponent("THỦ DẦU MỘT")}&discount_min=15&source=facebook&source=guland`;
let activeTab = 'deals';
let theme = localStorage.getItem('radar_theme') || 'light';

// Init Theme
document.documentElement.setAttribute('data-theme', theme);

function toggleTheme() {
  theme = theme === 'light' ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem('radar_theme', theme);
  const icon = document.getElementById('themeIcon');
  icon.setAttribute('data-lucide', theme === 'light' ? 'moon' : 'sun');
  lucide.createIcons();
}

function switchTab(tabId, btn) {
  activeTab = tabId;
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById(`tab-${tabId}`).classList.add('active');
  
  if (tabId === 'market') {
    // Market logic here
  }
}

function changeCity(city, btn) {
  document.querySelectorAll('.city-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  
  // Logic to update wards based on city
  updateWardFilters(city);
  applyFilters();
}

function updateDiscount(val) {
  document.getElementById('discountVal').innerText = `≥ ${val}%`;
}

function toggleDrops() {
  const toggle = document.getElementById('dropsToggle');
  toggle.classList.toggle('active');
  applyFilters();
}

function updateWardFilters(city) {
  const wards = globalWardsByCity[city] || [];
  const container = document.getElementById('wardFilters');
  
  container.innerHTML = wards.map(w => `
    <label class="filter-option">
      <div class="filter-checkbox-wrap">
        <input type="checkbox" name="ward" value="${w}" checked onchange="applyFilters()">
        <div class="custom-checkbox"></div>
        <span class="option-label">${w}</span>
      </div>
    </label>
  `).join('');
}

function filterWards() {
  const query = document.getElementById('wardSearch').value.toLowerCase();
  document.querySelectorAll('.ward-list .filter-option').forEach(opt => {
    const text = opt.querySelector('.option-label').innerText.toLowerCase();
    opt.style.display = text.includes(query) ? 'flex' : 'none';
  });
}

function changeSort(sortId, btn) {
    document.querySelectorAll('.sort-opt').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    applyFilters();
}

function applyFilters() {
    const form = document.getElementById('filterForm');
    const fd = new FormData(form);
    const params = new URLSearchParams();
    
    // Custom manual fields
    params.append('city', document.querySelector('.city-btn.active').dataset.city);
    params.append('discount_min', document.getElementById('discountRange').value);
    params.append('only_drops', document.getElementById('dropsToggle').classList.contains('active') ? '1' : '0');
    
    // Sort field
    const activeSort = document.querySelector('.sort-opt.active');
    if (activeSort) params.append('sort_by', activeSort.dataset.sort);
    
    // Form fields (wards, sources, prop_types)
    for (let [k, v] of fd.entries()) {
        params.append(k, v);
    }
    
    currentFilters = params.toString();
    currentPage = 1;
    fetchDashboard();
}

function showLoader() { document.getElementById('mainLoader').classList.add('show'); }
function hideLoader() { document.getElementById('mainLoader').classList.remove('show'); }

function changeTrendPeriod(period) {
    document.querySelectorAll('.period-btn').forEach(btn => {
        btn.classList.toggle('active', btn.getAttribute('onclick').includes(period));
    });
    // Update global filters and refetch
    const params = new URLSearchParams(currentFilters);
    params.set('trend_period', period);
    currentFilters = params.toString();
    fetchDashboard();
}

async function fetchDashboard() {
    const loader = document.getElementById('mainLoader');
    if (loader) loader.classList.add('show');
    
    console.log("RadarBDS: Fetching dashboard with filters:", currentFilters);
    try {
        const res = await fetch(`/api/dashboard?${currentFilters}`);
        if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
        const data = await res.json();
        
        globalWardsByCity = data.wards_by_city;
        globalSignals = data.signals || [];
        
        // Update stats in header
        if (data.stats) {
            if (document.getElementById('stat-total')) document.getElementById('stat-total').innerText = data.stats.total;
            if (document.getElementById('stat-new')) document.getElementById('stat-new').innerText = data.stats.new_today || 0;
            if (document.getElementById('stat-signals')) document.getElementById('stat-signals').innerText = data.stats.signals;
        }
        
        renderSignals(globalSignals);
        
        // Safety wrap analytical renders
        try {
            renderTrendChart(data.trend_data);
            renderHeatmap(data.ward_stats);
        } catch (e) {
            console.warn("RadarBDS: Analytics render failed:", e);
        }
        
        // Check if data returned ward stats to update counts
        if (data.ward_stats) {
            // ... (rest of logic can stay if needed, but I'll just remove the if block for wardFilters length)
        }
        
    } catch (err) {
        console.error("Dashboard error:", err);
        const grid = document.getElementById('signalsGrid');
        if (grid) grid.innerHTML = `<div style="grid-column:1/-1; text-align:center; padding:100px; color:var(--danger);">Lỗi tải dữ liệu: ${err.message}</div>`;
    } finally {
        if (loader) loader.classList.remove('show');
    }
}

let trendChartInstance = null;
function renderTrendChart(trendData) {
    const ctx = document.getElementById('trendChart');
    if (!ctx || !trendData) return;
    
    // trendData: { ward: [ {week: "2024-W1", median_ppm2: 15.5}, ... ] }
    const wards = Object.keys(trendData);
    if (wards.length === 0) return;

    // Collect all unique time labels (weeks/days/months)
    const allLabels = new Set();
    wards.forEach(w => trendData[w].forEach(p => allLabels.add(p.week)));
    const sortedLabels = Array.from(allLabels).sort();

    const colors = ['#5252E6', '#F59E0B', '#10B981', '#EF4444', '#8B5CF6', '#EC4899'];

    const datasets = wards.map((ward, i) => {
        const dataMap = {};
        trendData[ward].forEach(p => dataMap[p.week] = p.median_ppm2);
        
        return {
            label: ward,
            data: sortedLabels.map(lbl => dataMap[lbl] || null),
            borderColor: colors[i % colors.length],
            backgroundColor: 'transparent',
            borderWidth: 3,
            tension: 0.3,
            pointRadius: 4,
            pointHoverRadius: 6,
            spanGaps: true
        };
    });

    if (trendChartInstance) trendChartInstance.destroy();
    
    trendChartInstance = new Chart(ctx, {
        type: 'line',
        data: { labels: sortedLabels, datasets: datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'bottom', labels: { boxWidth: 12, usePointStyle: true, font: { size: 11, weight: '700' } } },
                tooltip: { mode: 'index', intersect: false }
            },
            scales: {
                y: { 
                    beginAtZero: false, 
                    title: { display: true, text: 'Giá (tr/m²)', font: { weight: '700' } },
                    grid: { color: 'rgba(0,0,0,0.05)' }
                },
                x: { grid: { display: false } }
            }
        }
    });
}

let mosChartInstance = null;
function renderHeatmap(marketData) {
    const ctx = document.getElementById('mosChart');
    if (!ctx || !marketData) return;
    
    if (marketData.length === 0) {
        // Handle empty state (maybe draw placeholder)
        return;
    }

    // Sort by ward name or MOS
    const sorted = [...marketData].sort((a, b) => b.avg_price - a.avg_price).slice(0, 8); // Top 8 wards
    
    const labels = sorted.map(d => d.ward);
    const actualPrices = sorted.map(d => d.avg_price);
    const fairPrices = sorted.map(d => {
        // Calc fair price from MOS: MOS = (Fair - Actual) / Fair * 100 
        // -> Actual = Fair * (1 - MOS/100) -> Fair = Actual / (1 - MOS/100)
        const mos = d.avg_mos || 0;
        return d.avg_price / (1 - mos/100);
    });

    if (mosChartInstance) mosChartInstance.destroy();

    mosChartInstance = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Giá thực tế',
                    data: actualPrices,
                    backgroundColor: '#6366F1', // Indigo
                    borderRadius: 6
                },
                {
                    label: 'Định giá AI',
                    data: fairPrices,
                    backgroundColor: '#10B981', // Emerald
                    borderRadius: 6
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'top', labels: { boxWidth: 12, font: { weight: '700' } } }
            },
            scales: {
                y: { beginAtZero: true, title: { display: true, text: 'Tỷ VNĐ', font: { weight: '700' } } },
                x: { grid: { display: false } }
            }
        }
    });
}

const PAGE_SIZE = 12;
let currentPage = 1;

function renderSignals(signals) {
  const grid = document.getElementById('signalsGrid');
  const pagination = document.getElementById('pagination');
  if (!grid) return;

  if (!signals || signals.length === 0) {
    grid.innerHTML = '<div style="grid-column: 1/-1; text-align: center; padding: 100px 0; color: var(--text-muted);">Không tìm thấy tin rao phù hợp.</div>';
    if (pagination) pagination.innerHTML = '';
    return;
  }

  const totalPages = Math.ceil(signals.length / PAGE_SIZE);
  if (currentPage > totalPages) currentPage = 1;

  const start = (currentPage - 1) * PAGE_SIZE;
  const pageSignals = signals.slice(start, start + PAGE_SIZE);

  grid.innerHTML = pageSignals.map((s, idx) => {
    const globalIdx = start + idx;
    const fairPriceTy = (s.fair_ppm2 && s.area_m2) ? (s.fair_ppm2 * s.area_m2 / 1000).toFixed(2) : '-';
    const isNew = s.days_ago <= 3;
    const timeLabel = s.days_ago === 0 ? 'Hôm nay' : `${s.days_ago} ngày trước`;
    const roadLabel = s.road_width_m ? `Đường ${s.road_width_m}m` : (s.road_tier <= 2 ? 'Mặt tiền' : 'Kiệt/Hẻm');

    return `
      <div class="sc-card animate-up" onclick="handleSignalClick(${globalIdx})">
        <div class="sc-img-wrap">
          <img src="${s.imgs && s.imgs.length ? s.imgs[0] : 'https://placehold.co/600x400'}" class="sc-img" onerror="this.src='https://placehold.co/600x400'">
          <div class="sc-badge-left"><i data-lucide="trending-down" size="14"></i> -${s.mos_pct}%</div>
          ${isNew ? `<div class="sc-badge-right"><i data-lucide="star" size="14"></i> MỚI</div>` : ''}
          <div class="sc-overlay-bottom">
            <div class="sc-source">${s.source}</div>
            <div class="sc-time"><i data-lucide="clock" size="12"></i> ${timeLabel}</div>
          </div>
        </div>
        <div class="sc-body">
          <div class="sc-title">${s.title}</div>
          <div class="sc-price-box">
            <div class="price-col actual">
              <span>Thực tế</span>
              <b>${s.price_ty} tỷ</b>
              <small>${s.actual_ppm2} tr/m²</small>
            </div>
            <div class="price-col">
              <span>Định giá</span>
              <b>${fairPriceTy} tỷ</b>
              <small>${s.fair_ppm2 || '-'} tr/m²</small>
            </div>
          </div>
          <div class="sc-meta">
            <div class="m-item"><i data-lucide="map-pin" size="13"></i> ${s.ward}</div>
            <div class="m-item"><i data-lucide="maximize" size="13"></i> ${s.area_m2} m²</div>
            <div class="m-item"><i data-lucide="navigation" size="13"></i> ${roadLabel}</div>
            <div class="m-item"><i data-lucide="file-text" size="13"></i> ${s.has_so ? 'Sổ Hồng' : 'Đang chờ'}</div>
          </div>
          <div class="sc-actions" onclick="event.stopPropagation()">
            <a href="https://zalo.me/${s.phone || '0343216024'}" target="_blank" class="btn-outline">
              <i data-lucide="message-circle" size="14"></i> Zalo
            </a>
            <button class="btn-primary" onclick="handleSignalClick(${globalIdx})">
              <i data-lucide="sparkles" size="14"></i> Phân tích Deal
            </button>
          </div>
        </div>
      </div>
    `;
  }).join('');

  // Render pagination
  if (pagination && totalPages > 1) {
    let pages = '';
    
    // Prev button
    pages += `<button class="page-btn" onclick="goToPage(${currentPage - 1})" ${currentPage === 1 ? 'disabled' : ''}>‹ Trước</button>`;
    
    // Page numbers (show up to 5 around current)
    const range = [];
    for (let i = 1; i <= totalPages; i++) {
      if (i === 1 || i === totalPages || (i >= currentPage - 2 && i <= currentPage + 2)) {
        range.push(i);
      }
    }
    let prev = null;
    for (const p of range) {
      if (prev && p - prev > 1) pages += `<span class="page-info">…</span>`;
      pages += `<button class="page-btn ${p === currentPage ? 'active' : ''}" onclick="goToPage(${p})">${p}</button>`;
      prev = p;
    }

    // Next button
    pages += `<button class="page-btn" onclick="goToPage(${currentPage + 1})" ${currentPage === totalPages ? 'disabled' : ''}>Sau ›</button>`;
    pages += `<span class="page-info">${signals.length} tin • Trang ${currentPage}/${totalPages}</span>`;
    
    pagination.innerHTML = pages;
  } else if (pagination) {
    pagination.innerHTML = signals.length > 0 ? `<span class="page-info">${signals.length} tin</span>` : '';
  }

  lucide.createIcons();
}

function goToPage(page) {
  currentPage = page;
  renderSignals(globalSignals);
  document.getElementById('signalsGrid').scrollIntoView({ behavior: 'smooth', block: 'start' });
}


function handleSignalClick(idx) {
    if (globalSignals && globalSignals[idx]) {
        showSignalDetail(globalSignals[idx]);
    }
}

let priceChartInstance = null;
let currentGalleryImages = [];
let currentGalleryIdx = 0;

function showSignalDetail(s) {
    console.log("RadarBDS: Showing detail for", s.id);
    
    // 1. Basic Info
    document.getElementById('modalTitle').innerText = s.title;
    document.getElementById('modalMeta').innerText = `Đăng ${s.days_ago === 0 ? 'Hôm nay' : s.days_ago + ' ngày trước'} • ${s.source}`;
    document.getElementById('modalBadgeMOS').innerText = `SUPER SIGNAL - ${s.mos_pct}%`;
    document.getElementById('modalDescription').innerText = s.description || 'Không có mô tả chi tiết.';
    document.getElementById('btnZalo').href = `https://zalo.me/0343216024?text=${encodeURIComponent("Chào bạn, mình quan tâm đến tin đăng: " + s.title + " (ID: " + s.id + ")")}`;

    // 2. AI Review (Dynamic generation based on data)
    const roadType = s.road_width_m ? `đường ${s.road_width_m}m` : (s.road_tier <= 2 ? 'mặt tiền' : 'hẻm xe hơi');
    const aiText = `Tín hiệu ngợp **cấp độ cao**: giá chào thấp hơn fair value **${s.mos_pct}%**, đã giảm **${s.price_dropped ? 'nhiều lần' : 'giá'}** trong thời gian ngắn. Pháp lý **${s.has_so ? 'Sổ Hồng' : 'Đang kiểm tra'}**, vị trí thuộc khu ${s.ward}. Phù hợp đầu tư trung hạn hoặc lướt sóng.`;
    document.getElementById('modalAIReview').innerHTML = aiText.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

    // 3. Gallery
    currentGalleryImages = s.imgs && s.imgs.length ? s.imgs : ['https://placehold.co/600x400?text=No+Image'];
    currentGalleryIdx = 0;
    updateGallery();

    // 4. Price History & Chart
    fetchPriceHistory(s.id, s.price_ty);

    // 5. Comps
    fetchComps(s.id, s.area_m2, s.price_ty);

    document.getElementById('signalModal').style.display = 'flex';
    lucide.createIcons();
}

function updateGallery() {
    const mainImg = document.getElementById('modalMainImg');
    const thumbs = document.getElementById('modalThumbs');
    const counter = document.getElementById('galCounter');

    mainImg.src = currentGalleryImages[currentGalleryIdx];
    counter.innerText = `${currentGalleryIdx + 1} / ${currentGalleryImages.length}`;

    thumbs.innerHTML = currentGalleryImages.map((img, i) => `
        <img src="${img}" class="thumb-item ${i === currentGalleryIdx ? 'active' : ''}" onclick="currentGalleryIdx=${i}; updateGallery()">
    `).join('');
}

function changeGallery(dir) {
    currentGalleryIdx = (currentGalleryIdx + dir + currentGalleryImages.length) % currentGalleryImages.length;
    updateGallery();
}

async function fetchPriceHistory(listingId, currentPrice) {
    const container = document.getElementById('modalPriceHistory');
    container.innerHTML = '<div style="font-size:12px; color:var(--text-muted);">Đang tải lịch sử giá...</div>';
    
    try {
        const res = await fetch(`/api/history/${listingId}`);
        const history = await res.json();
        
        // Prepare data for chart
        const labels = history.map(h => h.date);
        const data = history.map(h => h.price_ty);
        
        renderPriceChart(labels, data);
        
        // Render list
        container.innerHTML = history.reverse().map((h, i) => {
            const prevPrice = history[i+1] ? history[i+1].price_ty : null;
            const drop = prevPrice ? (((h.price_ty - prevPrice) / prevPrice) * 100).toFixed(1) : null;
            return `
                <div class="price-item">
                    <div class="pi-date"><i data-lucide="calendar" size="12"></i> ${h.date}</div>
                    <div class="pi-val">
                        ${h.price_ty} tỷ
                        ${drop && drop < 0 ? `<span class="pi-drop">${drop}%</span>` : ''}
                    </div>
                </div>
            `;
        }).join('');
        lucide.createIcons();
        
    } catch (err) {
        container.innerHTML = 'Không có dữ liệu lịch sử giá.';
    }
}

function renderPriceChart(labels, data) {
    const ctx = document.getElementById('priceChart').getContext('2d');
    
    if (priceChartInstance) {
        priceChartInstance.destroy();
    }
    
    priceChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Giá (tỷ)',
                data: data,
                borderColor: '#5252e6',
                backgroundColor: 'rgba(82, 82, 230, 0.1)',
                borderWidth: 2,
                tension: 0.3,
                pointBackgroundColor: '#5252e6',
                fill: true
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                y: { display: true, grid: { display: false } },
                x: { display: true, grid: { display: false } }
            }
        }
    });
}

async function fetchComps(listingId, area, price) {
    const tbody = document.getElementById('modalCompsTable');
    tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; color:var(--text-muted); padding:20px;">Đang tìm giao dịch tương tự...</td></tr>';
    
    try {
        const res = await fetch(`/api/comps/${listingId}`);
        const comps = await res.json();
        
        let html = comps.map(c => `
            <tr>
                <td>${c.title.substring(0, 20)}...</td>
                <td>${c.area_m2} m²</td>
                <td class="c-price">${c.price_ty} tỷ</td>
                <td>${(c.posted_at || '').substring(0, 7)}</td>
            </tr>
        `).join('');
        
        // Add current deal highlight
        html += `
            <tr class="highlight">
                <td><strong>Deal hiện tại</strong></td>
                <td><strong>${area} m²</strong></td>
                <td class="c-now">${price} tỷ</td>
                <td><strong>Now</strong></td>
            </tr>
        `;
        
        tbody.innerHTML = html;
        
    } catch (err) {
        tbody.innerHTML = '<tr><td colspan="4">Không tìm thấy dữ liệu so sánh.</td></tr>';
    }
}

function closeModal() {
  document.getElementById('signalModal').style.display = 'none';
}

// Initial Load
document.addEventListener('DOMContentLoaded', () => {
    console.log("RadarBDS: DOM loaded, initializing...");
    try {
        // 1. Populate ward filters first so applyFilters captures them
        const activeCity = document.querySelector('.city-btn.active').dataset.city;
        updateWardFilters(activeCity);
        
        // 2. Then fetch data
        applyFilters(); 
        
        if (typeof lucide !== 'undefined') {
            lucide.createIcons();
        }
    } catch (e) {
        console.error("Initialization error:", e);
    }
});

function appendMessage(role, text) {
  const container = document.getElementById('chatMessages');
  const div = document.createElement('div');
  div.className = `message ${role}`;
  div.innerText = text;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

