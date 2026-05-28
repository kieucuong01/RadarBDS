// Market opportunity, market indicators, and trend chart rendering.
async function loadMarketCharts(useCache = true) {
  const opportunityContainer = document.getElementById('opportunityListContainer');
  if (opportunityContainer) opportunityContainer.classList.add('loading');
  try {
    const data = await fetchJSONCached('market', `/api/heatmap?${currentFilters}`, useCache);
    renderOpportunityList(data);
  } catch (err) {
    if (err.name !== 'AbortError') console.error("Market charts error:", err);
  } finally {
    if (opportunityContainer) opportunityContainer.classList.remove('loading');
  }
}

function _opportunityAction(mos, dealCount) {
  if (mos >= 25 && dealCount >= 3) return 'Ưu tiên xem trước';
  if (mos >= 15) return 'Có thể lọc sâu';
  return 'Theo dõi thêm';
}

function _fmtMarketPrice(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return '-';
  return `${n.toLocaleString('vi-VN', { maximumFractionDigits: 1 })} tr/m²`;
}

function _viewOpportunityWard(ward) {
  const target = String(ward || '').trim();
  if (!target) return;
  const boxes = Array.from(document.querySelectorAll('#wardFilters input[name="ward"]'));
  let found = false;
  boxes.forEach((box) => {
    const matched = box.value === target;
    box.checked = matched;
    found = found || matched;
  });
  if (found) updateWardSelectionSummary();

  const signalBtn = Array.from(document.querySelectorAll('.nav-link'))
    .find(btn => (btn.textContent || '').includes('Săn Deal'));
  switchTab('signals', signalBtn || null);
  if (found) {
    applyFilters();
  } else {
    loadSignals(1, { reset: true });
  }
  hideSidebarMobile();
}

function renderOpportunityList(data) {
  const root = document.getElementById('opportunityList');
  const summaryEl = document.getElementById('opportunitySummary');
  if (!root) return;

  const rows = (data || [])
    .filter(d => Number(d.deal_count || 0) > 0 && Number(d.median_mos || 0) > 0)
    .sort((a, b) => {
      const scoreA = Number(a.deal_count || 0) * 100 + Number(a.median_mos || 0);
      const scoreB = Number(b.deal_count || 0) * 100 + Number(b.median_mos || 0);
      return scoreB - scoreA;
    })
    .slice(0, 6);

  const totalDeals = rows.reduce((sum, x) => sum + Number(x.deal_count || 0), 0);
  const best = rows[0];
  if (summaryEl) {
    summaryEl.innerHTML = rows.length
      ? `
        <span><strong>${rows.length}</strong> khu có deal</span>
        <span><strong>${totalDeals}</strong> tin đang dưới định giá</span>
        <span>Tốt nhất: <strong>${escHtml(best.ward || '')}</strong> thấp hơn ${Number(best.median_mos || 0).toFixed(1)}%</span>
      `
      : '';
  }

  if (!rows.length) {
    root.innerHTML = `
      <div class="opportunity-empty">
        <strong>Chưa có khu vực đủ tín hiệu tốt</strong>
        <span>Nới bộ lọc phường, nguồn tin hoặc loại hình để Radar có thêm mẫu deal.</span>
      </div>
    `;
    return;
  }

  root.innerHTML = rows.map((x, index) => {
    const ward = x.ward || '';
    const dealCount = Number(x.deal_count || 0);
    const mos = Number(x.median_mos || 0);
    const signalRate = Number(x.signal_rate || 0);
    const totalCount = Number(x.total_count || 0);
    return `
      <article class="opportunity-row">
        <div class="opportunity-rank">${index + 1}</div>
        <div class="opportunity-main">
          <div class="opportunity-top">
            <h4>${escHtml(ward)}</h4>
            <span>${escHtml(_opportunityAction(mos, dealCount))}</span>
          </div>
          <div class="opportunity-metrics">
            <div><strong>${dealCount}</strong><span>deal</span></div>
            <div><strong>-${mos.toFixed(1)}%</strong><span>so với định giá</span></div>
            <div><strong>${_fmtMarketPrice(x.avg_price)}</strong><span>giá/m² TB</span></div>
          </div>
          <p>${dealCount} / ${totalCount} tin hợp lệ đang là signal (${signalRate.toFixed(1)}%). Dùng để chọn khu đáng xem trước, không phải so giá tổng giữa các phường.</p>
        </div>
        <button type="button" class="opportunity-btn" data-ward="${escHtml(ward)}" onclick="_viewOpportunityWard(this.dataset.ward)">Xem deal</button>
      </article>
    `;
  }).join('');
}

function _fmtIndicatorNumber(value, digits = 0) {
  const n = Number(value);
  if (!Number.isFinite(n)) return '-';
  return n.toLocaleString('vi-VN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  });
}

function _fmtIndicatorPct(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return '-';
  return `${n.toLocaleString('vi-VN', { maximumFractionDigits: n >= 10 ? 0 : 1 })}%`;
}

function _indicatorBadge(levelKey, level) {
  return `<span class="indicator-badge level-${escHtml(levelKey || 'normal')}">${escHtml(level || '')}</span>`;
}

function _renderDistressRatio(rows, summary) {
  const body = document.getElementById('distressRatioBody');
  const summaryEl = document.getElementById('distressRatioSummary');
  if (!body) return;

  if (summaryEl) {
    const hotspots = Number((summary && summary.distress_hotspots) || 0);
    const scanned = Number((summary && summary.wards_scanned) || 0);
    summaryEl.innerHTML = `
      <span><strong>${hotspots}</strong> khu vực áp lực cao</span>
      <span>Ngưỡng săn ép giá: từ 25%, vùng rất mạnh: từ 35%</span>
      <span>${scanned} khu vực được quét</span>
    `;
  }

  if (!rows || !rows.length) {
    body.innerHTML = `<tr><td colspan="6" class="indicator-empty-row">Chưa đủ dữ liệu giảm giá theo khu vực.</td></tr>`;
    return;
  }

  body.innerHTML = rows.map((x) => {
    const ratio = Number(x.ratio_pct || 0);
    const meterWidth = Math.max(2, Math.min(100, ratio));
    return `
      <tr>
        <td><strong>${escHtml(x.ward || '')}</strong></td>
        <td>${_fmtIndicatorNumber(x.total_count)}</td>
        <td>${_fmtIndicatorNumber(x.distress_count)}</td>
        <td>
          <div class="indicator-meter"><span class="level-${escHtml(x.level_key || 'normal')}" style="width:${meterWidth}%"></span></div>
          <b>${_fmtIndicatorPct(ratio)}</b>
        </td>
        <td>${_indicatorBadge(x.level_key, x.level)}</td>
        <td class="indicator-action">${escHtml(x.action || '')}</td>
      </tr>
    `;
  }).join('');
}

function _renderSupplyAnomaly(rows, summary) {
  const body = document.getElementById('supplyAnomalyBody');
  const summaryEl = document.getElementById('supplyAnomalySummary');
  if (!body) return;

  if (summaryEl) {
    const month = (summary && summary.current_month) || '';
    const hotspots = Number((summary && summary.supply_hotspots) || 0);
    const prev = ((summary && summary.previous_months) || []).join(', ');
    summaryEl.innerHTML = `
      <span><strong>${hotspots}</strong> khu vực tăng cung</span>
      <span>Tháng đang đo: ${escHtml(month || '-')}</span>
      <span>Nền so sánh: ${escHtml(prev || '-')}</span>
    `;
  }

  if (!rows || !rows.length) {
    body.innerHTML = `<tr><td colspan="6" class="indicator-empty-row">Chưa đủ dữ liệu nguồn cung theo tháng.</td></tr>`;
    return;
  }

  body.innerHTML = rows.map((x) => {
    const delta = Number(x.delta || 0);
    const growthText = x.growth_pct === null || x.growth_pct === undefined
      ? (Number(x.current_count || 0) > 0 ? 'Mới bật' : '-')
      : `${delta >= 0 ? '+' : ''}${_fmtIndicatorPct(x.growth_pct)}`;
    return `
      <tr>
        <td><strong>${escHtml(x.ward || '')}</strong></td>
        <td>${_fmtIndicatorNumber(x.current_count)}</td>
        <td>${_fmtIndicatorNumber(x.prev_avg, 1)}</td>
        <td>
          <b class="${delta > 0 ? 'indicator-up' : 'indicator-flat'}">${escHtml(growthText)}</b>
          <small>${delta >= 0 ? '+' : ''}${_fmtIndicatorNumber(delta, 1)} tin</small>
        </td>
        <td>${_indicatorBadge(x.level_key, x.level)}</td>
        <td class="indicator-action">${escHtml(x.action || '')}</td>
      </tr>
    `;
  }).join('');
}

async function loadMarketIndicators(useCache = true) {
  const distressContainer = document.getElementById('distressRatioContainer');
  const supplyContainer = document.getElementById('supplyAnomalyContainer');
  if (!distressContainer && !supplyContainer) return;
  if (!['vip', 'admin'].includes(window.USER_TIER || 'guest')) {
    _renderDistressRatio([], {});
    _renderSupplyAnomaly([], {});
    return;
  }
  if (distressContainer) distressContainer.classList.add('loading');
  if (supplyContainer) supplyContainer.classList.add('loading');
  const runId = ++marketIndicatorRunSeq;
  try {
    const data = await fetchJSONCached('marketIndicators', `/api/market-indicators?${currentFilters}`, useCache);
    if (runId !== marketIndicatorRunSeq) return;
    _renderDistressRatio(data.distress_ratio || [], data.summary || {});
    _renderSupplyAnomaly(data.supply_anomaly || [], data.summary || {});
  } catch (err) {
    if (err.name !== 'AbortError') console.error('Market indicators error:', err);
    _renderDistressRatio([], {});
    _renderSupplyAnomaly([], {});
  } finally {
    if (runId === marketIndicatorRunSeq) {
      if (distressContainer) distressContainer.classList.remove('loading');
      if (supplyContainer) supplyContainer.classList.remove('loading');
    }
  }
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
