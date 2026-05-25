const STATUS = {
  new: { label: 'Chờ xử lý', cls: 'status-new' },
  called: { label: 'Đang tư vấn', cls: 'status-called' },
  viewing: { label: 'Đi xem đất', cls: 'status-viewing' },
  deposit: { label: 'Chốt cọc', cls: 'status-deposit' },
  cancelled: { label: 'Hủy', cls: 'status-cancelled' }
};
const STATUS_KEYS = Object.keys(STATUS);
const SOURCE_NAMES = { facebook: 'Facebook', guland: 'Guland', batdongsan: 'BDS.vn' };
const PTYPES = { dat_nen: 'Đất nền', dat_vuon: 'Đất vườn', nha_dat: 'Nhà đất', nha_tro: 'Nhà trọ', chung_cu: 'Chung cư', nha_o_xa_hoi: 'Nhà ở xã hội' };
const PLACEHOLDER = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='640' height='420' viewBox='0 0 640 420'%3E%3Crect width='640' height='420' fill='%23eef2f7'/%3E%3Cpath d='M250 250l55-72 44 57 25-32 66 82H204z' fill='%2394a3b8'/%3E%3Ccircle cx='392' cy='150' r='24' fill='%2394a3b8'/%3E%3C/svg%3E";
const ADMIN_THEME_KEY = 'radar_admin_theme';

let leadTimer = null;
let activeQualityTab = 'dups';
let activeInfraFilter = 'timeline';

function initAdminTheme() {
  const saved = localStorage.getItem(ADMIN_THEME_KEY) || 'light';
  document.documentElement.setAttribute('data-theme', saved);
}

function toggleAdminTheme() {
  const current = document.documentElement.getAttribute('data-theme') || 'light';
  const next = current === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem(ADMIN_THEME_KEY, next);
}

function esc(v) {
  return String(v ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
}

async function fetchJSON(url, options = {}) {
  const clean = new URL(url, window.location.href);
  clean.username = '';
  clean.password = '';
  const res = await fetch(clean.toString(), options);
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

function money(v) {
  if (v === null || v === undefined || v === '') return '-';
  return `${Number(v).toLocaleString('vi-VN', { maximumFractionDigits: 2 })} tỷ`;
}

function area(v) {
  if (v === null || v === undefined || v === '') return '-';
  return `${Number(v).toLocaleString('vi-VN', { maximumFractionDigits: 1 })} m²`;
}

function ppm2(v) {
  if (v === null || v === undefined || v === '') return '-';
  const n = Number(v);
  if (!Number.isFinite(n) || n <= 0) return '-';
  return `${n.toLocaleString('vi-VN', { maximumFractionDigits: 1 })} tr/m²`;
}

function shortDate(v) {
  return (v || '').replace('T', ' ').slice(0, 16) || '-';
}

function switchPanel(name) {
  document.querySelectorAll('.nav-item').forEach(btn => btn.classList.toggle('active', btn.dataset.panel === name));
  document.querySelectorAll('.workspace-panel').forEach(panel => panel.classList.toggle('active', panel.id === `panel-${name}`));
  if (name === 'crm') loadLeads();
  if (name === 'quality') {
    if (activeQualityTab === 'dups') loadDuplicates();
    else loadBlacklist();
  }
  if (name === 'training') loadTrainingItems();
  if (name === 'infra') loadInfraItems();
  if (name === 'users') loadUsers();
}

// ──────────────────────────────────────────────────────────────
// User management (RBAC)
// ──────────────────────────────────────────────────────────────
let userTimer = null;

function userQuery() {
  const q = new URLSearchParams();
  const text = document.getElementById('userSearch').value.trim();
  const tier = document.getElementById('userTierFilter').value;
  if (text) q.set('q', text);
  if (tier) q.set('tier', tier);
  return q.toString();
}

async function loadUsers() {
  const data = await fetchJSON(`/admin/api/users?${userQuery()}`);
  renderUserStats(data.summary || {});
  renderUserRows(data.items || []);
}

function renderUserStats(s) {
  const items = [
    ['Total Users', s.total || 0, 'tất cả'],
    ['VIP', s.vip || 0, 'đang trả phí'],
    ['Free', s.free || 0, 'miễn phí'],
    ['Admin', s.admin || 0, 'nội bộ'],
    ['Banned', s.banned || 0, 'đã chặn'],
  ];
  document.getElementById('userStats').innerHTML = items.map((s, idx) => `
    <div class="stat-card">
      <small>${esc(s[0])}</small>
      <div><strong style="color:${idx === 1 ? 'var(--green)' : idx === 4 ? 'var(--red)' : 'var(--ink)'}">${s[1]}</strong><span>${esc(s[2])}</span></div>
    </div>
  `).join('');
}

function renderUserRows(items) {
  const body = document.getElementById('userTableBody');
  if (!items.length) {
    body.innerHTML = `<tr><td colspan="9"><div class="empty">Không có user phù hợp.</div></td></tr>`;
    return;
  }
  body.innerHTML = items.map(u => {
    const tierBadgeColor = u.effective_tier === 'vip' ? 'var(--green)' : u.effective_tier === 'admin' ? 'var(--orange)' : 'var(--ink-muted)';
    const banned = u.is_banned ? `<span style="color:var(--red)">BANNED</span>` : '';
    const vipExp = u.vip_expires_at ? shortDate(u.vip_expires_at) : '-';
    const expired = u.tier === 'vip' && u.effective_tier !== 'vip' ? ' <small style="color:var(--red)">(hết hạn)</small>' : '';
    const tg = u.telegram_linked ? '✓' : '-';
    return `
      <tr>
        <td>#${u.id}</td>
        <td><strong>${esc(u.identifier || '-')}</strong><br><small>${esc(u.identifier_type || '')}</small></td>
        <td>${esc(u.display_name || '-')}</td>
        <td><strong style="color:${tierBadgeColor}">${esc((u.effective_tier || u.tier || '').toUpperCase())}</strong>${expired} ${banned}</td>
        <td>${vipExp}</td>
        <td>${tg}</td>
        <td>${Number(u.watchlist_count || 0)}</td>
        <td>${shortDate(u.created_at)}</td>
        <td>${shortDate(u.last_login_at)}</td>
        <td>
          <button class="icon-btn" onclick="grantVip(${u.id}, 30)">+30d VIP</button>
          <button class="icon-btn" onclick="grantVip(${u.id}, 7)">+7d</button>
          <button class="icon-btn" onclick="revokeVip(${u.id})">Revoke</button>
          <button class="icon-btn" onclick="toggleBan(${u.id}, ${u.is_banned ? 0 : 1})">${u.is_banned ? 'Unban' : 'Ban'}</button>
        </td>
      </tr>
    `;
  }).join('');
}

async function grantVip(userId, days) {
  const customDays = prompt(`Cấp VIP bao nhiêu ngày? (default ${days})`, String(days));
  if (customDays === null) return;
  const n = parseInt(customDays, 10);
  if (!n || n <= 0) return alert('Số ngày không hợp lệ');
  try {
    await fetchJSON(`/admin/api/users/${userId}/grant-vip`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ days: n }),
    });
    loadUsers();
  } catch (e) { alert('Lỗi: ' + (e.message || e)); }
}

async function revokeVip(userId) {
  if (!confirm(`Thu hồi VIP của user #${userId}?`)) return;
  try {
    await fetchJSON(`/admin/api/users/${userId}/revoke`, { method: 'POST' });
    loadUsers();
  } catch (e) { alert('Lỗi: ' + (e.message || e)); }
}

async function toggleBan(userId, banned) {
  const verb = banned ? 'Ban' : 'Unban';
  if (!confirm(`${verb} user #${userId}?`)) return;
  try {
    await fetchJSON(`/admin/api/users/${userId}/ban`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ banned: !!banned }),
    });
    loadUsers();
  } catch (e) { alert('Lỗi: ' + (e.message || e)); }
}

function leadQuery() {
  const q = new URLSearchParams();
  const text = document.getElementById('leadSearch').value.trim();
  const status = document.getElementById('leadStatusFilter').value;
  if (text) q.set('q', text);
  if (status) q.set('status', status);
  return q.toString();
}

async function loadLeads() {
  const data = await fetchJSON(`/admin/api/leads?${leadQuery()}`);
  renderLeadStats(data.summary || {});
  renderLeadRows(data.items || []);
}

function renderLeadStats(summary) {
  const stats = [
    ['Total Leads', summary.total || 0, 'tất cả'],
    ['Won Deals', summary.deposit || 0, 'đã chốt cọc'],
    ['Pending', summary.new || 0, 'cần xử lý'],
    ['Đi xem đất', summary.viewing || 0, 'đang hẹn'],
    ['Hủy', summary.cancelled || 0, 'đã hủy']
  ];
  document.getElementById('leadStats').innerHTML = stats.map((s, idx) => `
    <div class="stat-card">
      <small>${esc(s[0])}</small>
      <div><strong style="color:${idx === 1 ? 'var(--green)' : idx === 2 ? 'var(--orange)' : idx === 4 ? 'var(--red)' : 'var(--ink)'}">${s[1]}</strong><span>${esc(s[2])}</span></div>
    </div>
  `).join('');
}

function renderLeadRows(items) {
  document.getElementById('leadCountMeta').textContent = `Hiển thị ${items.length} lead`;
  const body = document.getElementById('leadRows');
  if (!items.length) {
    body.innerHTML = `<tr><td colspan="5"><div class="empty">Chưa có lead phù hợp.</div></td></tr>`;
    return;
  }
  body.innerHTML = items.map(x => {
    const st = STATUS[x.status] || STATUS.new;
    const listingLabel = x.listing_title ? `#${x.listing_id} · ${x.listing_title}` : (x.listing_id ? `Deal #${x.listing_id}` : (x.listing_url || '-'));
    const link = x.listing_id ? `/listing/${x.listing_id}` : (x.listing_url || '#');
    return `
      <tr>
        <td>${shortDate(x.created_at)}</td>
        <td class="phone">${esc(x.zalo_phone || '-')}</td>
        <td><a class="deal-pill" href="${esc(link)}" target="_blank">${esc(listingLabel)}</a></td>
        <td>
          <select class="status-select ${st.cls}" data-lead="${x.id}">
            ${STATUS_KEYS.map(k => `<option value="${k}" ${x.status === k ? 'selected' : ''}>${STATUS[k].label}</option>`).join('')}
          </select>
        </td>
        <td><button class="icon-btn" onclick="window.open('${esc(link)}','_blank')">Mở</button></td>
      </tr>
    `;
  }).join('');
  body.querySelectorAll('.status-select').forEach(sel => {
    sel.addEventListener('change', async () => {
      await fetchJSON(`/admin/api/leads/${sel.dataset.lead}/status`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: sel.value })
      });
      loadLeads();
    });
  });
}

function exportLeads() {
  const q = leadQuery();
  const clean = new URL(`/admin/api/leads/export.csv${q ? '?' + q : ''}`, window.location.href);
  clean.username = '';
  clean.password = '';
  window.location.href = clean.toString();
}

function switchQualityTab(name) {
  activeQualityTab = name;
  document.querySelectorAll('.segment[data-quality-tab]').forEach(btn => btn.classList.toggle('active', btn.dataset.qualityTab === name));
  document.querySelectorAll('.quality-tab').forEach(tab => tab.classList.toggle('active', tab.id === `quality-${name === 'dups' ? 'dups' : 'blacklist'}`));
  if (name === 'dups') loadDuplicates();
  else loadBlacklist();
}

function infraFilters() {
  if (!activeInfraFilter || activeInfraFilter === 'all') return '';
  const q = new URLSearchParams();
  q.set('kind', activeInfraFilter);
  return q.toString();
}

function resetInfraForm() {
  document.getElementById('infraId').value = '';
  document.getElementById('infraKind').value = 'timeline';
  document.getElementById('infraTitle').value = '';
  document.getElementById('infraSubtitle').value = '';
  document.getElementById('infraSummary').value = '';
  document.getElementById('infraWard').value = '';
  document.getElementById('infraRoadRef').value = '';
  document.getElementById('infraProjectCode').value = '';
  document.getElementById('infraMilestone').value = '';
  document.getElementById('infraStatus').value = '';
  document.getElementById('infraSeverity').value = '';
  document.getElementById('infraProgress').value = '';
  document.getElementById('infraDate').value = '';
  document.getElementById('infraSortOrder').value = '0';
  document.getElementById('infraSourceUrl').value = '';
}

function renderInfraRows(items) {
  const root = document.getElementById('infraRows');
  if (!items.length) {
    root.innerHTML = `<div class="empty">Chưa có item hạ tầng nào.</div>`;
    return;
  }
  root.innerHTML = items.map((x) => `
    <article class="infra-item" data-id="${x.id}">
      <div class="infra-item-top">
        <div>
          <span class="infra-kind">${esc(x.kind)}</span>
          <h4>${esc(x.title)}</h4>
        </div>
        <small>${esc(x.relative_time || '')}</small>
      </div>
      <p>${esc(x.summary || x.subtitle || '')}</p>
      <div class="infra-meta">
        ${x.ward ? `<span>${esc(x.ward)}</span>` : ''}
        ${x.road_ref ? `<span>${esc(x.road_ref)}</span>` : ''}
        ${x.milestone_label ? `<span>${esc(x.milestone_label)}</span>` : ''}
        ${x.progress_pct !== null && x.progress_pct !== undefined ? `<span>${Number(x.progress_pct).toFixed(0)}%</span>` : ''}
        ${x.status_tag ? `<span>${esc(x.status_tag)}</span>` : ''}
        ${x.severity ? `<span>${esc(x.severity)}</span>` : ''}
      </div>
      <div class="infra-item-actions">
        <button class="secondary-btn" onclick="editInfra(${x.id})">Sửa</button>
        <button class="secondary-btn" onclick="deactivateInfra(${x.id})">Ẩn</button>
      </div>
    </article>
  `).join('');
}

async function loadInfraItems() {
  const query = infraFilters();
  const data = await fetchJSON(`/admin/api/infra${query ? '?' + query : ''}`);
  renderInfraRows(data.items || []);
}

function switchInfraFilter(name) {
  activeInfraFilter = name;
  document.querySelectorAll('.segment[data-infra-filter]').forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.infraFilter === name);
  });
  loadInfraItems();
}

function collectInfraPayload() {
  return {
    id: Number(document.getElementById('infraId').value || 0),
    kind: document.getElementById('infraKind').value,
    title: document.getElementById('infraTitle').value.trim(),
    subtitle: document.getElementById('infraSubtitle').value.trim(),
    summary: document.getElementById('infraSummary').value.trim(),
    ward: document.getElementById('infraWard').value.trim(),
    road_ref: document.getElementById('infraRoadRef').value.trim(),
    project_code: document.getElementById('infraProjectCode').value.trim(),
    milestone_label: document.getElementById('infraMilestone').value.trim(),
    status_tag: document.getElementById('infraStatus').value,
    severity: document.getElementById('infraSeverity').value,
    progress_pct: document.getElementById('infraProgress').value.trim(),
    event_date: document.getElementById('infraDate').value.trim(),
    sort_order: document.getElementById('infraSortOrder').value.trim() || '0',
    source_url: document.getElementById('infraSourceUrl').value.trim()
  };
}

async function saveInfra() {
  const payload = collectInfraPayload();
  if (!payload.title) {
    window.alert('Cần nhập tiêu đề.');
    return;
  }
  await fetchJSON('/admin/api/infra', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  resetInfraForm();
  await loadInfraItems();
}

async function editInfra(id) {
  const data = await fetchJSON('/admin/api/infra?active=0');
  const item = (data.items || []).find((x) => Number(x.id) === Number(id));
  if (!item) return;
  document.getElementById('infraId').value = item.id;
  document.getElementById('infraKind').value = item.kind || 'timeline';
  document.getElementById('infraTitle').value = item.title || '';
  document.getElementById('infraSubtitle').value = item.subtitle || '';
  document.getElementById('infraSummary').value = item.summary || '';
  document.getElementById('infraWard').value = item.ward || '';
  document.getElementById('infraRoadRef').value = item.road_ref || '';
  document.getElementById('infraProjectCode').value = item.project_code || '';
  document.getElementById('infraMilestone').value = item.milestone_label || '';
  document.getElementById('infraStatus').value = item.status_tag || '';
  document.getElementById('infraSeverity').value = item.severity || '';
  document.getElementById('infraProgress').value = item.progress_pct ?? '';
  document.getElementById('infraDate').value = (item.event_date || '').slice(0, 10);
  document.getElementById('infraSortOrder').value = item.sort_order ?? 0;
  document.getElementById('infraSourceUrl').value = item.source_url || '';
  document.getElementById('infraTitle').focus();
}

async function deactivateInfra(id) {
  await fetchJSON(`/admin/api/infra/${id}`, { method: 'DELETE' });
  await loadInfraItems();
}

async function loadDuplicates() {
  const data = await fetchJSON('/admin/api/qc/duplicates');
  const items = data.items || [];
  document.getElementById('dupCount').textContent = items.length;
  const root = document.getElementById('duplicateCards');
  if (!items.length) {
    root.innerHTML = `<div class="empty">Không còn cặp duplicate cần xử lý.</div>`;
    return;
  }
  root.innerHTML = items.map(x => duplicateCard(x)).join('');
}

function adPanel(x, side) {
  const isCanon = side === 'canonical';
  const id = isCanon ? x.duplicate_of_id : x.id;
  const source = isCanon ? x.canonical_source : x.source;
  const price = isCanon ? x.canonical_price_ty : x.price_ty;
  const areaVal = isCanon ? x.canonical_area_m2 : x.area_m2;
  const desc = isCanon ? x.canonical_description_excerpt : x.description_excerpt;
  const img = isCanon ? x.canonical_image : x.image;
  const dt = isCanon ? x.canonical_dt : x.dt;
  const detail = isCanon ? x.canonical_detail_url : x.detail_url;
  return `
    <div class="ad-box">
      <img class="ad-img" src="${esc(img || PLACEHOLDER)}" onerror="this.src=PLACEHOLDER" alt="">
      <div>
        <a class="ad-title" href="${esc(detail)}" target="_blank">AD-${id} · ${esc(SOURCE_NAMES[source] || source || '-')}</a>
        <div class="ad-meta">${money(price)} · ${area(areaVal)} · ${shortDate(dt)}</div>
        <div class="ad-desc">${esc(desc || '-')}</div>
      </div>
    </div>
  `;
}

function duplicateCard(x) {
  const confidence = Math.min(96, Math.max(72, Math.round(100 - Math.abs((x.price_ty || 0) - (x.canonical_price_ty || 0)) * 5)));
  return `
    <article class="dup-card">
      <div class="dup-head">
        <div>Cặp nghi trùng <span class="deal-pill">DUP-${x.id}</span></div>
        <div style="color:var(--muted)">AI confidence: <strong style="color:var(--red)">${confidence}%</strong></div>
      </div>
      <div class="dup-grid">
        ${adPanel(x, 'listing')}
        ${adPanel(x, 'canonical')}
      </div>
      <div class="dup-actions">
        <button class="primary-btn merge-btn" onclick="mergeDup(${x.id}, ${x.duplicate_of_id})">Gộp thành 1 Deal</button>
        <button class="secondary-btn" onclick="splitDup(${x.id}, ${x.duplicate_of_id})">Khác lô</button>
      </div>
    </article>
  `;
}

async function mergeDup(id, target) {
  await fetchJSON('/admin/api/qc/duplicates/merge', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ listing_id: id, target_listing_id: target, note: 'admin_control_room_merge' })
  });
  loadDuplicates();
}

async function splitDup(id, target) {
  const note = window.prompt('Lý do tách lô?', 'not_same_lot') || 'not_same_lot';
  await fetchJSON('/admin/api/qc/duplicates/split', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ listing_id: id, target_listing_id: target, note })
  });
  loadDuplicates();
}

async function loadBlacklist() {
  const data = await fetchJSON('/admin/api/blacklist');
  const items = data.items || [];
  document.getElementById('blacklistCount').textContent = items.filter(x => x.active).length;
  const root = document.getElementById('blacklistRows');
  if (!items.length) {
    root.innerHTML = `<div class="empty">Chưa có SĐT trong blacklist.</div>`;
    return;
  }
  root.innerHTML = items.map(x => `
    <div class="blacklist-row">
      <strong>${esc(x.phone_norm)}</strong>
      <span>${esc(x.reason || '-')}</span>
      <span style="color:${x.active ? 'var(--green)' : 'var(--muted)'}">${x.active ? 'active' : 'inactive'}</span>
      <button class="secondary-btn" ${x.active ? '' : 'disabled'} onclick="deactivateBlacklist('${esc(x.phone_norm)}')">Deactivate</button>
    </div>
  `).join('');
}

async function addBlacklist() {
  const phone = document.getElementById('blacklistPhone').value.trim();
  const reason = document.getElementById('blacklistReason').value.trim();
  if (!phone) return;
  await fetchJSON('/admin/api/blacklist', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ phone, reason })
  });
  document.getElementById('blacklistPhone').value = '';
  document.getElementById('blacklistReason').value = '';
  loadBlacklist();
}

async function deactivateBlacklist(phone) {
  await fetchJSON('/admin/api/blacklist', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ phone })
  });
  loadBlacklist();
}

let _trnGal = {};
let _trnGalIds = [];
let _trnGalIdx = 0;
let _trnWardsLoaded = false;
let _trnWardCities = {};   // { city: [wards] }
let _trnAllWards = [];     // mọi phường có signal (kể cả ngoài CITY_MAP)
let _trnOffset = 0;
let _trnLoading = false;
let _trnHasMore = false;
let _trnChipDelegated = false;
const TRN_PAGE = 50;

function trnFilterQuery(offset = 0) {
  const city  = document.getElementById('trnCity')?.value || '';
  const ward  = document.getElementById('trnWard')?.value || '';
  const mos   = document.getElementById('trnMos')?.value || '0';
  const sort  = document.getElementById('trnSort')?.value || 'default';
  const queue = document.getElementById('trnQueue')?.value || 'main';
  const p = new URLSearchParams({ limit: String(TRN_PAGE), sort, offset: String(offset) });
  if (queue && queue !== 'main') p.set('queue', queue);
  if (city) p.set('city', city);
  if (ward) p.set('ward', ward);
  if (mos && mos !== '0') p.set('mos_min', mos);
  return p.toString();
}

function _trnPopulateWards(city) {
  const wardSel = document.getElementById('trnWard');
  if (!wardSel) return;
  const cur = wardSel.value;
  const list = city && _trnWardCities[city] ? _trnWardCities[city]
    : (_trnAllWards.length ? _trnAllWards : Object.values(_trnWardCities).flat().sort());
  wardSel.innerHTML = '<option value="">Tất cả phường</option>' +
    list.map(w => `<option value="${esc(w)}">${esc(w)}</option>`).join('');
  if (list.includes(cur)) wardSel.value = cur;
}

function _trnBindChipDelegation(root) {
  if (_trnChipDelegated) return;
  _trnChipDelegated = true;
  root.addEventListener('click', (ev) => {
    const chip = ev.target.closest('.chip');
    if (!chip || !root.contains(chip)) return;
    const group = chip.dataset.group;
    if (group !== 'reason') {
      root.querySelectorAll(`.chip[data-card="${chip.dataset.card}"][data-group="${group}"]`).forEach(c => c.classList.remove('active'));
    }
    chip.classList.toggle('active');
    if (group === 'extraction') syncExtractionState(chip.dataset.card);
  });
}

async function loadTrainingItems(append = false) {
  if (_trnLoading) return;
  _trnLoading = true;
  try {
    if (!append) _trnOffset = 0;
    const data = await fetchJSON('/admin/api/ai-training/items?' + trnFilterQuery(_trnOffset));
    const root = document.getElementById('trainingGrid');
    const items = data.items || [];

    // Badge: luôn "chưa review / tổng signal"
    const badge = document.getElementById('trainingCount');
    if (badge) badge.textContent = `${data.pending || 0}/${data.total || 0}`;
    const meta = document.getElementById('trainingMeta');
    const shown = append ? (_trnOffset + items.length) : items.length;
    const queueLabel = data.queue_label || 'Review mới';
    if (meta) meta.textContent = `· ${queueLabel} · ${data.pending || 0} mục / ${data.total || 0} signal · hiển thị ${shown}`;

    // City + ward dropdowns (populate once)
    if (!_trnWardsLoaded && (data.ward_cities || data.wards)) {
      _trnWardCities = data.ward_cities || {};
      _trnAllWards = (data.wards || []).slice();
      const citySel = document.getElementById('trnCity');
      if (citySel) {
        citySel.innerHTML = '<option value="">Tất cả TP</option>' +
          Object.keys(_trnWardCities).map(c => `<option value="${esc(c)}">${esc(c)}</option>`).join('');
      }
      _trnPopulateWards('');
      _trnWardsLoaded = true;
    }

    _trnOffset += items.length;
    _trnHasMore = !!data.has_more;

    // Gallery store
    items.forEach(it => { _trnGal[it.id] = (it.images && it.images.length) ? it.images : []; });

    if (!items.length && !append) {
      root.innerHTML = `<div class="empty">Không có signal nào khớp bộ lọc.</div>`;
      _trnSyncSentinel();
      return;
    }
    const html = items.map(trainingCard).join('');
    if (append) root.insertAdjacentHTML('beforeend', html);
    else root.innerHTML = html;
    _trnBindChipDelegation(root);
    requestAnimationFrame(() => _trnSyncDescriptionToggles(root));
    _trnSyncSentinel();
  } finally {
    _trnLoading = false;
  }
}

// Sentinel cuối lưới: scroll tới → tự load thêm (infinite scroll)
let _trnObserver = null;
function _trnSyncSentinel() {
  const sent = document.getElementById('trnSentinel');
  if (!sent) return;
  sent.style.display = _trnHasMore ? 'block' : 'none';
  if (!_trnObserver) {
    _trnObserver = new IntersectionObserver((entries) => {
      if (entries.some(e => e.isIntersecting) && _trnHasMore && !_trnLoading) {
        loadTrainingItems(true);
      }
    }, { rootMargin: '400px' });
    _trnObserver.observe(sent);
  }
}

// Trích xuất sai → ẩn mục "2. Định giá AI" (tin đó để học làm sạch dữ liệu);
// chỉ khi trích xuất "Đúng hết" mới chấm định giá (để cải tiến phần định giá).
function syncExtractionState(cid) {
  const active = document.querySelector(`.chip[data-card="${cid}"][data-group="extraction"].active`);
  const ok = !active || active.dataset.value === 'all_correct';
  const valbox = document.getElementById(`valbox-${cid}`);
  const note = document.getElementById(`exnote-${cid}`);
  if (valbox) valbox.style.display = ok ? '' : 'none';
  if (note) note.style.display = ok ? 'none' : '';
}

async function loadMoreTraining() {
  await loadTrainingItems(true);
}

async function saveLegalVerification(id, status) {
  const val = (suffix) => document.getElementById(`legal-${suffix}-${id}`)?.value || '';
  const payload = {
    listing_id: id,
    status,
    legal_road_text: val('road'),
    legal_ward: val('ward'),
    legal_area_m2: val('area'),
    legal_residential_m2: val('res'),
    thua_so: val('thua'),
    to_ban_do: val('to')
  };
  const result = await fetchJSON('/admin/api/legal-verification', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  if (result && result.ok) {
    loadTrainingItems();
  }
}

function trnToggleExpand(id) {
  const card = document.querySelector(`.training-card[data-id="${id}"]`);
  const btn = document.getElementById(`expbtn-${id}`);
  if (!card) return;
  const expanded = card.classList.toggle('expanded');
  if (btn) btn.textContent = expanded ? '▲ Thu gọn' : '▼ Mở review';
}

function trnToggleDesc(id) {
  const wrap = document.querySelector(`.train-desc-wrap[data-desc-wrap="${id}"]`);
  const btn = document.querySelector(`.train-desc-toggle[data-desc-toggle="${id}"]`);
  if (!wrap) return;
  const expanded = wrap.classList.toggle('expanded');
  if (btn) btn.textContent = expanded ? 'Thu gọn' : 'Xem thêm';
}

function _trnSyncDescriptionToggles(scope = document) {
  scope.querySelectorAll('.train-desc-wrap').forEach(wrap => {
    const desc = wrap.querySelector('.train-desc');
    const btn = wrap.querySelector('.train-desc-toggle');
    if (!desc || !btn) return;
    const wasExpanded = wrap.classList.contains('expanded');
    if (wasExpanded) wrap.classList.remove('expanded');
    const needsToggle = desc.scrollHeight > desc.clientHeight + 1;
    if (wasExpanded) wrap.classList.add('expanded');
    btn.hidden = !needsToggle;
    if (!needsToggle) wrap.classList.remove('expanded');
    btn.textContent = wrap.classList.contains('expanded') ? 'Thu gọn' : 'Xem thêm';
  });
}

function openTrnGallery(id) {
  const imgs = _trnGal[id] || [];
  if (!imgs.length) return;
  _trnGalIds = imgs;
  _trnGalIdx = 0;
  _trnGalRender();
  document.getElementById('trnGallery').classList.add('open');
}
function closeTrnGallery() {
  document.getElementById('trnGallery').classList.remove('open');
}
function trnGalleryNav(delta) {
  if (!_trnGalIds.length) return;
  _trnGalIdx = (_trnGalIdx + delta + _trnGalIds.length) % _trnGalIds.length;
  _trnGalRender();
}
function _trnGalRender() {
  document.getElementById('trnGalleryImg').src = _trnGalIds[_trnGalIdx];
  document.getElementById('trnGalleryCounter').textContent =
    `${_trnGalIdx + 1} / ${_trnGalIds.length}`;
}

function trainingCard(x) {
  const cid = `card-${x.id}`;
  const explain = x.explain || {};
  const missing = (explain.missing_fields || []).length ? explain.missing_fields.join(', ') : 'không';
  const nImg = (x.images && x.images.length) || 0;
  const desc = (x.description || '').trim();
  const actualPpm2 = x.actual_ppm2 || x.price_per_m2 || '';
  const fairPpm2 = x.fair_ppm2 || '';
  const sourceFlags = (x.source_quality_flags || '').split(',').filter(Boolean);
  const legal = x.legal_summary || {};
  const legalFlags = String(legal.flags || '').split(',').filter(Boolean);
  const legalBox = (x.is_legal_qc || legal.status) ? `
            <div class="review-box legal-qc-box">
              <div class="review-title">Legal QC · ${esc(legal.status || 'unverified')} · ${Math.round(legal.trust_score || legal.confidence_score || 0)}%</div>
              <ul class="explain-list">
                <li>Thua/to: ${esc(legal.thua_so || '-')} / ${esc(legal.to_ban_do || '-')}</li>
                <li>DT so: ${area(legal.legal_area_m2)} · Tho cu: ${area(legal.legal_residential_m2)}</li>
                <li>Ward: ${esc(legal.legal_ward || '-')} · Road: ${esc(legal.legal_road_text || '-')}</li>
                ${legalFlags.length ? `<li>Flags: ${legalFlags.map(esc).join(', ')}</li>` : ''}
              </ul>
              <div class="legal-qc-grid">
                <input id="legal-road-${x.id}" value="${esc(legal.legal_road_text || '')}" placeholder="Duong tren so">
                <input id="legal-ward-${x.id}" value="${esc(legal.legal_ward || '')}" placeholder="Phuong tren so">
                <input id="legal-area-${x.id}" value="${esc(legal.legal_area_m2 || '')}" placeholder="DT so">
                <input id="legal-res-${x.id}" value="${esc(legal.legal_residential_m2 || '')}" placeholder="Tho cu">
                <input id="legal-thua-${x.id}" value="${esc(legal.thua_so || '')}" placeholder="Thua so">
                <input id="legal-to-${x.id}" value="${esc(legal.to_ban_do || '')}" placeholder="To ban do">
              </div>
              <div class="chip-row">
                <button class="secondary-btn legal-qc-action" onclick="saveLegalVerification(${x.id}, 'verified')">Xac nhan dung so</button>
                <button class="secondary-btn legal-qc-action" onclick="saveLegalVerification(${x.id}, 'needs_review')">Can soi tiep</button>
                <button class="secondary-btn legal-qc-action" onclick="saveLegalVerification(${x.id}, 'conflict')">Co conflict</button>
              </div>
            </div>` : '';
  const fairTitle = x.fair_ty
    ? `(Fair Value: ${money(x.fair_ty)}${fairPpm2 ? ` · ${ppm2(fairPpm2)}` : ''})`
    : '';
  return `
    <article class="training-card" data-id="${x.id}">
      <div class="train-img-wrap">
        <img class="train-img" src="${esc(x.image || PLACEHOLDER)}" onerror="this.src=PLACEHOLDER" alt="">
        <div class="mos-chip">MOS ${Math.round(x.mos_pct || 0)}%</div>
        ${nImg ? `<button class="train-gallery-btn" onclick="openTrnGallery(${x.id})">🖼️ Ảnh (${nImg})</button>` : ''}
      </div>
      <div class="train-body">
        <div class="train-title">
          <a href="${esc(x.detail_url)}" target="_blank">${esc(x.ward || 'Unknown')}</a>
          <span>TD-${x.id}</span>
        </div>
        <div class="train-lines">
          <div><strong>${esc(x.title || 'Không có tiêu đề')}</strong></div>
          <div>${esc(x.road_type || 'Chưa rõ đường')} · ${esc(PTYPES[x.property_type] || x.property_type || 'Chưa rõ loại')}</div>
          <div>DT: <strong>${area(x.area_m2)}</strong> · Giá rao: <strong>${money(x.price_ty)}</strong> · Giá/m²: <strong>${ppm2(actualPpm2)}</strong></div>
        </div>
        ${desc ? `
          <div class="train-desc-wrap" data-desc-wrap="${x.id}">
            <div class="train-desc">${esc(desc)}</div>
            <button type="button" class="train-desc-toggle" data-desc-toggle="${x.id}" onclick="trnToggleDesc(${x.id})" hidden>Xem thêm</button>
          </div>` : ''}

        <div class="trn-review-cols${x.ai_verdict ? ' has-ai' : ''}">
          <div class="trn-review-main">
            ${legalBox}
            <div class="review-box">
              <div class="review-title">1. Thông tin trích xuất</div>
              <div class="chip-row">
                <button class="chip active" data-card="${cid}" data-group="extraction" data-value="all_correct">Đúng hết</button>
                <button class="chip" data-card="${cid}" data-group="extraction" data-value="wrong_ward">Sai phường</button>
                <button class="chip" data-card="${cid}" data-group="extraction" data-value="wrong_road">Sai đường</button>
                <button class="chip" data-card="${cid}" data-group="extraction" data-value="wrong_property_type">Sai loại hình</button>
                <button class="chip" data-card="${cid}" data-group="extraction" data-value="wrong_price">Sai giá</button>
                <button class="chip" data-card="${cid}" data-group="extraction" data-value="wrong_area">Sai diện tích</button>
              </div>
              <div class="extraction-note" id="exnote-${cid}" style="display:none;margin-top:8px;font-size:11px;color:var(--muted)">
                Trích xuất sai → tin này dùng để học <strong>làm sạch dữ liệu</strong>, không cần chấm định giá.
              </div>
            </div>
            <div class="review-box" id="valbox-${cid}">
              <div class="review-title">2. Định giá AI ${fairTitle}</div>
              <div class="chip-row">
                <button class="chip" data-card="${cid}" data-group="valuation" data-value="cheap_real">Rẻ thật</button>
                <button class="chip" data-card="${cid}" data-group="valuation" data-value="fair">Giá hợp lý</button>
                <button class="chip" data-card="${cid}" data-group="valuation" data-value="overpriced">Đang cao</button>
                <button class="chip" data-card="${cid}" data-group="valuation" data-value="fake_price">Giá ảo</button>
                <button class="chip" data-card="${cid}" data-group="valuation" data-value="cannot_price">Không định giá</button>
              </div>
              <ul class="explain-list">
                <li>Score ${Math.round(x.signal_score || 0)}, segment ${esc(x.segment || '-')} (${x.n_segment || 0} mẫu)</li>
                <li>Giá thực ${money(x.price_ty)} (${ppm2(actualPpm2)}), fair ${money(x.fair_ty)} (${ppm2(fairPpm2)}), thiếu field: ${esc(missing)}</li>
                ${sourceFlags.length ? `<li>Source QC: ${sourceFlags.map(esc).join(', ')}</li>` : ''}
              </ul>
              <div class="review-title" style="margin-top:10px">Nguyên nhân</div>
              <div class="chip-row">
                ${[['bad_fengshui','Phong thủy xấu'],['deep_alley','Hẻm sâu'],['corner_lot','Đất góc'],['bait_listing','Tin mồi'],['fake_price','Giá ảo'],['bad_data','Dữ liệu sai']].map(([v,l]) => `<button class="chip reason-chip" data-card="${cid}" data-group="reason" data-value="${v}">${l}</button>`).join('')}
              </div>
            </div>
            <button class="primary-btn save-training" onclick="saveTraining(${x.id})">Lưu Phản Hồi & Dạy AI</button>
          </div>
          <div class="trn-review-aside">${x.ai_verdict ? `
            <div class="review-box" style="opacity:.92;height:100%">
              <div class="review-title">🤖 Claude pre-review</div>
              <ul class="explain-list">
                <li><strong>${esc(x.ai_verdict)}</strong>${x.ai_confidence != null ? ` · ${Math.round(x.ai_confidence * 100)}%` : ''}</li>
                ${x.ai_reasoning ? `<li>${esc(x.ai_reasoning)}</li>` : ''}
                ${(() => { let f = []; try { f = JSON.parse(x.ai_red_flags || '[]'); } catch (e) { f = []; } return (f && f.length) ? `<li>🚩 ${f.map(esc).join(', ')}</li>` : ''; })()}
                ${x.ai_needs_map_check ? `<li>🗺️ Cần kiểm tra quy hoạch/pháp lý/vị trí</li>` : ''}
              </ul>
            </div>` : ''}</div>
        </div>
      </div>
    </article>
  `;
}

async function saveTraining(id) {
  const card = document.querySelector(`.training-card[data-id="${id}"]`);
  const extraction = card.querySelector('.chip[data-group="extraction"].active')?.dataset.value || 'all_correct';
  const extractionOk = extraction === 'all_correct';
  // Trích xuất sai → bỏ qua chấm định giá, tin này về nhánh học làm sạch dữ liệu.
  const valuation = extractionOk
    ? (card.querySelector('.chip[data-group="valuation"].active')?.dataset.value || '')
    : 'cannot_price';
  if (extractionOk && !valuation) {
    alert('Chọn nhãn định giá trước khi lưu.');
    return;
  }
  const tags = Array.from(card.querySelectorAll('.chip[data-group="reason"].active')).map(x => x.dataset.value);
  let verdict;
  if (tags.includes('fake_price') || valuation === 'fake_price') {
    verdict = 'fake_price';
  } else if (!extractionOk) {
    verdict = 'bad_data';                       // sai trích xuất → học làm sạch dữ liệu
  } else if (tags.includes('bad_data')) {
    verdict = 'cannot_price';
  } else {
    verdict = valuation;                        // nhãn định giá tách riêng: cheap_real|fair|overpriced|fake_price|cannot_price
  }
  await fetchJSON('/admin/api/ai-training/feedback', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      listing_id: id,
      verdict,
      extraction_verdict: extraction,
      valuation_verdict: valuation,
      reason_tags: tags,
      reason_code: tags[0] || extraction || valuation,
      reason_text: 'admin_ai_training'
    })
  });
  card.remove();
}

document.addEventListener('DOMContentLoaded', () => {
  initAdminTheme();
  document.querySelectorAll('.nav-item').forEach(btn => btn.addEventListener('click', () => switchPanel(btn.dataset.panel)));
  document.querySelectorAll('.segment[data-quality-tab]').forEach(btn => btn.addEventListener('click', () => switchQualityTab(btn.dataset.qualityTab)));
  document.querySelectorAll('.segment[data-infra-filter]').forEach(btn => btn.addEventListener('click', () => switchInfraFilter(btn.dataset.infraFilter)));
  document.getElementById('leadStatusFilter').addEventListener('change', loadLeads);
  document.getElementById('leadSearch').addEventListener('input', () => {
    clearTimeout(leadTimer);
    leadTimer = setTimeout(loadLeads, 220);
  });
  document.getElementById('exportLeadsBtn').addEventListener('click', exportLeads);
  document.getElementById('addBlacklistBtn').addEventListener('click', addBlacklist);
  document.getElementById('refreshTrainingBtn').addEventListener('click', loadTrainingItems);
  ['trnMos', 'trnSort', 'trnWard', 'trnQueue'].forEach(idv => {
    const el = document.getElementById(idv);
    if (el) el.addEventListener('change', () => {
      if (idv === 'trnQueue') {
        _trnWardsLoaded = false;
        _trnAllWards = [];
        _trnWardCities = {};
      } else {
        _trnWardsLoaded = true;
      }
      loadTrainingItems();
    });
  });
  const citySel = document.getElementById('trnCity');
  if (citySel) citySel.addEventListener('change', () => {
    _trnPopulateWards(citySel.value);
    document.getElementById('trnWard').value = '';
    loadTrainingItems();
  });
  // Sidebar collapse
  const toggleSidebar = document.getElementById('toggleSidebar');
  if (toggleSidebar) {
    let collapsed = false;
    try { collapsed = localStorage.getItem('sidebarCollapsed') === '1'; } catch (e) {}
    if (collapsed) document.body.classList.add('sidebar-collapsed');
    toggleSidebar.addEventListener('click', () => {
      document.body.classList.toggle('sidebar-collapsed');
      const c = document.body.classList.contains('sidebar-collapsed');
      try { localStorage.setItem('sidebarCollapsed', c ? '1' : '0'); } catch (e) {}
    });
  }
  const applyTrnView = (view) => {
    const grid = document.getElementById('trainingGrid');
    if (grid) grid.classList.toggle('view-list', view === 'list');
    document.getElementById('trnViewGrid')?.classList.toggle('active', view !== 'list');
    document.getElementById('trnViewList')?.classList.toggle('active', view === 'list');
    try { localStorage.setItem('trnView', view); } catch (e) {}
    if (grid) requestAnimationFrame(() => _trnSyncDescriptionToggles(grid));
  };
  document.getElementById('trnViewGrid')?.addEventListener('click', () => applyTrnView('grid'));
  document.getElementById('trnViewList')?.addEventListener('click', () => applyTrnView('list'));
  let savedView = 'grid';
  try { savedView = localStorage.getItem('trnView') || 'grid'; } catch (e) {}
  applyTrnView(savedView);
  document.addEventListener('keydown', (e) => {
    const g = document.getElementById('trnGallery');
    if (!g || !g.classList.contains('open')) return;
    if (e.key === 'Escape') closeTrnGallery();
    else if (e.key === 'ArrowLeft') trnGalleryNav(-1);
    else if (e.key === 'ArrowRight') trnGalleryNav(1);
  });
  document.getElementById('refreshInfraBtn').addEventListener('click', loadInfraItems);
  document.getElementById('saveInfraBtn').addEventListener('click', saveInfra);
  document.getElementById('resetInfraBtn').addEventListener('click', resetInfraForm);
  document.getElementById('adminThemeToggle').addEventListener('click', toggleAdminTheme);
  const refreshUsersBtn = document.getElementById('refreshUsersBtn');
  if (refreshUsersBtn) refreshUsersBtn.addEventListener('click', loadUsers);
  const userTierFilter = document.getElementById('userTierFilter');
  if (userTierFilter) userTierFilter.addEventListener('change', loadUsers);
  const userSearch = document.getElementById('userSearch');
  if (userSearch) userSearch.addEventListener('input', () => {
    clearTimeout(userTimer);
    userTimer = setTimeout(loadUsers, 220);
  });
  loadLeads();
});
