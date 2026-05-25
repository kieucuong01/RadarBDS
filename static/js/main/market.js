// Heatmap, market indicators, price-gap, and trend chart rendering.
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
