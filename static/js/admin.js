const STATUS = {
  new: { label: 'Chờ xử lý', cls: 'status-new' },
  called: { label: 'Đang tư vấn', cls: 'status-called' },
  viewing: { label: 'Đi xem đất', cls: 'status-viewing' },
  deposit: { label: 'Chốt cọc', cls: 'status-deposit' },
  cancelled: { label: 'Hủy', cls: 'status-cancelled' }
};
const STATUS_KEYS = Object.keys(STATUS);
const SOURCE_NAMES = { facebook: 'Facebook', guland: 'Guland', batdongsan: 'BDS.vn' };
const PTYPES = { dat_nen: 'Đất nền', dat_vuon: 'Đất vườn', nha_dat: 'Nhà đất', nha_tro: 'Nhà trọ', chung_cu: 'Chung cư' };
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

async function loadTrainingItems() {
  const data = await fetchJSON('/admin/api/ai-training/items?limit=24');
  const root = document.getElementById('trainingGrid');
  const items = data.items || [];
  if (!items.length) {
    root.innerHTML = `<div class="empty">Chưa có signal nào cần training.</div>`;
    return;
  }
  root.innerHTML = items.map(trainingCard).join('');
  root.querySelectorAll('.chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const group = chip.dataset.group;
      if (group !== 'reason') {
        root.querySelectorAll(`.chip[data-card="${chip.dataset.card}"][data-group="${group}"]`).forEach(c => c.classList.remove('active'));
      }
      chip.classList.toggle('active');
    });
  });
}

function trainingCard(x) {
  const cid = `card-${x.id}`;
  const explain = x.explain || {};
  const missing = (explain.missing_fields || []).length ? explain.missing_fields.join(', ') : 'không';
  return `
    <article class="training-card" data-id="${x.id}">
      <div class="train-img-wrap">
        <img class="train-img" src="${esc(x.image || PLACEHOLDER)}" onerror="this.src=PLACEHOLDER" alt="">
        <div class="mos-chip">MOS ${Math.round(x.mos_pct || 0)}%</div>
      </div>
      <div class="train-body">
        <div class="train-title">
          <a href="${esc(x.detail_url)}" target="_blank">${esc(x.ward || 'Unknown')}</a>
          <span>TD-${x.id}</span>
        </div>
        <div class="train-lines">
          <div>${esc(x.road_type || 'Chưa rõ đường')} · ${esc(PTYPES[x.property_type] || x.property_type || 'Chưa rõ loại')}</div>
          <div>DT: <strong>${area(x.area_m2)}</strong> · Giá rao: <strong>${money(x.price_ty)}</strong></div>
        </div>

        <div class="review-box">
          <div class="review-title">1. Thông tin trích xuất</div>
          <div class="chip-row">
            <button class="chip active" data-card="${cid}" data-group="extraction" data-value="all_correct">Đúng hết</button>
            <button class="chip" data-card="${cid}" data-group="extraction" data-value="wrong_ward">Sai phường</button>
            <button class="chip" data-card="${cid}" data-group="extraction" data-value="wrong_road">Sai đường</button>
            <button class="chip" data-card="${cid}" data-group="extraction" data-value="wrong_property_type">Sai loại hình</button>
          </div>
        </div>

        <div class="review-box">
          <div class="review-title">2. Định giá AI ${x.fair_ty ? `(Fair Value: ${money(x.fair_ty)})` : ''}</div>
          <div class="chip-row">
            <button class="chip" data-card="${cid}" data-group="valuation" data-value="too_high">Hơi cao</button>
            <button class="chip active" data-card="${cid}" data-group="valuation" data-value="correct">Chuẩn</button>
            <button class="chip" data-card="${cid}" data-group="valuation" data-value="too_low">Hơi thấp</button>
          </div>
          <ul class="explain-list">
            <li>Score ${Math.round(x.signal_score || 0)}, segment ${esc(x.segment || '-')} (${x.n_segment || 0} mẫu)</li>
            <li>Giá thực ${money(x.price_ty)}, fair ${money(x.fair_ty)}, thiếu field: ${esc(missing)}</li>
          </ul>
          <div class="review-title" style="margin-top:12px">Nguyên nhân</div>
          <div class="chip-row">
            ${['bad_fengshui','deep_alley','corner_lot','bait_listing','fake_price','bad_data'].map(tag => `<button class="chip reason-chip" data-card="${cid}" data-group="reason" data-value="${tag}">${tag.replace(/_/g, ' ')}</button>`).join('')}
          </div>
        </div>
        <button class="primary-btn save-training" onclick="saveTraining(${x.id})">Lưu Phản Hồi & Dạy AI</button>
      </div>
    </article>
  `;
}

async function saveTraining(id) {
  const card = document.querySelector(`.training-card[data-id="${id}"]`);
  const extraction = card.querySelector('.chip[data-group="extraction"].active')?.dataset.value || 'all_correct';
  const valuation = card.querySelector('.chip[data-group="valuation"].active')?.dataset.value || 'correct';
  const tags = Array.from(card.querySelectorAll('.chip[data-group="reason"].active')).map(x => x.dataset.value);
  const verdict = tags.includes('fake_price') ? 'fake_price' : tags.includes('bad_data') ? 'bad_data' : (valuation === 'correct' && extraction === 'all_correct' ? 'correct' : 'bad_data');
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
  document.getElementById('refreshInfraBtn').addEventListener('click', loadInfraItems);
  document.getElementById('saveInfraBtn').addEventListener('click', saveInfra);
  document.getElementById('resetInfraBtn').addEventListener('click', resetInfraForm);
  document.getElementById('adminThemeToggle').addEventListener('click', toggleAdminTheme);
  loadLeads();
});
