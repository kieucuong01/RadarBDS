// Market opportunity, market indicators, and trend chart rendering.
let opportunityMatrixInstance = null;

async function loadMarketCharts(useCache = true) {
  const opportunityContainer = document.getElementById('opportunityListContainer');
  const matrixContainer = document.getElementById('opportunityMatrixContainer');
  if (opportunityContainer) opportunityContainer.classList.add('loading');
  if (matrixContainer) matrixContainer.classList.add('loading');
  try {
    const data = await fetchJSONCached('market', `/api/heatmap?${currentFilters}`, useCache);
    renderOpportunityList(data);
    renderOpportunityMatrix(data);
  } catch (err) {
    if (err.name !== 'AbortError') console.error("Market charts error:", err);
  } finally {
    if (opportunityContainer) opportunityContainer.classList.remove('loading');
    if (matrixContainer) matrixContainer.classList.remove('loading');
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

function _opportunityMatrixTier(mos, dealCount) {
  if (mos >= 25 && dealCount >= 3) {
    return { key: 'priority', label: 'Ưu tiên xem trước', color: '#10b981', border: '#047857' };
  }
  if (mos >= 15 || dealCount >= 8) {
    return { key: 'watch', label: 'Có thể lọc sâu', color: '#f59e0b', border: '#b45309' };
  }
  return { key: 'neutral', label: 'Theo dõi thêm', color: '#64748b', border: '#475569' };
}

function _matrixBubbleSize(totalCount) {
  const total = Number(totalCount || 0);
  if (!Number.isFinite(total) || total <= 0) return 7;
  return Math.max(7, Math.min(24, Math.sqrt(total) * 1.6));
}

function _hexToRgba(hex, alpha) {
  const clean = String(hex || '').replace('#', '');
  if (clean.length !== 6) return hex;
  const r = parseInt(clean.slice(0, 2), 16);
  const g = parseInt(clean.slice(2, 4), 16);
  const b = parseInt(clean.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function _sampleCountLabel(count) {
  const n = Number(count || 0);
  if (!Number.isFinite(n) || n <= 0) return 'không rõ số mẫu';
  if (n <= 3) return `ít mẫu: từ ${n} tin`;
  return `từ ${n} tin`;
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

function renderOpportunityMatrix(data) {
  const canvas = document.getElementById('opportunityMatrixChart');
  const insightEl = document.getElementById('opportunityMatrixInsight');
  if (!canvas) return;

  if (opportunityMatrixInstance) {
    opportunityMatrixInstance.destroy();
    opportunityMatrixInstance = null;
  }

  const rows = (data || [])
    .filter(d => Number(d.total_count || 0) > 0)
    .map((d) => {
      const mos = Number(d.median_mos || 0);
      const dealCount = Number(d.deal_count || 0);
      const totalCount = Number(d.total_count || 0);
      const tier = _opportunityMatrixTier(mos, dealCount);
      return {
        x: mos,
        y: dealCount,
        r: _matrixBubbleSize(totalCount),
        ward: d.ward || '',
        totalCount,
        signalRate: Number(d.signal_rate || 0),
        avgPrice: Number(d.avg_price || 0),
        tier
      };
    })
    .filter(d => d.x > 0 || d.y > 0)
    .sort((a, b) => (b.y * 100 + b.x) - (a.y * 100 + a.x));

  if (insightEl) {
    const best = rows[0];
    insightEl.innerHTML = best
      ? `
        <span><strong>${escHtml(best.ward)}</strong> nổi bật nhất</span>
        <span>${best.y} deal, MOS trung vị ${best.x.toFixed(1)}%</span>
        <span>Cỡ bong bóng = số tin hợp lệ trong khu</span>
      `
      : '<span>Chưa đủ dữ liệu để dựng ma trận cơ hội.</span>';
  }

  if (!rows.length) return;

  const maxMos = Math.max(30, ...rows.map(d => d.x));
  const maxDeals = Math.max(10, ...rows.map(d => d.y));
  const rootStyle = getComputedStyle(document.documentElement);
  const gridColor = rootStyle.getPropertyValue('--border').trim() || 'rgba(148,163,184,.25)';
  const textColor = rootStyle.getPropertyValue('--text-muted').trim() || '#64748b';

  opportunityMatrixInstance = new Chart(canvas.getContext('2d'), {
    type: 'bubble',
    data: {
      datasets: [{
        label: 'Khu vực',
        data: rows,
        backgroundColor: rows.map(d => `${d.tier.color}55`),
        borderColor: rows.map(d => d.tier.border),
        borderWidth: 1.5,
        hoverBorderWidth: 2.5
      }]
    },
    options: {
      animation: { duration: 0 },
      responsive: true,
      maintainAspectRatio: false,
      parsing: false,
      onClick: (event, elements) => {
        if (!elements || !elements.length) return;
        const point = rows[elements[0].index];
        if (point && point.ward) _viewOpportunityWard(point.ward);
      },
      onHover: (event, elements) => {
        event.native.target.style.cursor = elements && elements.length ? 'pointer' : 'default';
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: (items) => (items[0] && items[0].raw && items[0].raw.ward) || '',
            label: (item) => {
              const d = item.raw || {};
              return [
                `${d.tier ? d.tier.label : 'Khu vực'}`,
                `Deal: ${d.y || 0}/${d.totalCount || 0} tin (${(d.signalRate || 0).toFixed(1)}%)`,
                `MOS trung vị: ${(d.x || 0).toFixed(1)}%`,
                `Giá TB: ${_fmtMarketPrice(d.avgPrice)}`
              ];
            }
          }
        }
      },
      scales: {
        x: {
          min: 0,
          suggestedMax: Math.ceil(maxMos / 5) * 5,
          title: { display: true, text: 'Độ rẻ so với định giá AI (MOS trung vị)', color: textColor, font: { weight: '700' } },
          grid: { color: gridColor },
          ticks: {
            color: textColor,
            callback: (value) => `${value}%`
          }
        },
        y: {
          min: 0,
          suggestedMax: Math.ceil(maxDeals * 1.15),
          title: { display: true, text: 'Số deal đang thấp hơn định giá', color: textColor, font: { weight: '700' } },
          grid: { color: gridColor },
          ticks: { color: textColor, precision: 0 }
        }
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

function _areaRiskTone(score) {
  const n = Number(score || 0);
  if (n >= 70) return 'danger';
  if (n >= 50) return 'warning';
  if (n >= 32) return 'watch';
  return 'normal';
}

function _fmtSignedNumber(value, digits = 1) {
  const n = Number(value || 0);
  if (!Number.isFinite(n)) return '-';
  return `${n >= 0 ? '+' : ''}${_fmtIndicatorNumber(n, digits)}`;
}

function renderAreaRiskRadar(rows, summary) {
  const root = document.getElementById('areaRiskRadar');
  const summaryEl = document.getElementById('areaRiskRadarSummary');
  if (!root) return;

  const items = (rows || [])
    .filter(x => x && x.ward)
    .slice(0, 8);

  if (summaryEl) {
    const hotspots = Number((summary && summary.area_risk_hotspots) || 0);
    const scanned = Number((summary && summary.wards_scanned) || 0);
    summaryEl.innerHTML = `
      <span><strong>${hotspots}</strong> khu rủi ro cao</span>
      <span>Điểm rủi ro gộp từ giảm giá và nguồn cung</span>
      <span>${scanned} khu vực được quét</span>
    `;
  }

  if (!items.length) {
    root.innerHTML = `
      <div class="opportunity-empty area-risk-empty">
        <strong>Chưa đủ dữ liệu rủi ro khu vực</strong>
        <span>Nới bộ lọc hoặc chờ thêm tin mới để Radar có nền so sánh tốt hơn.</span>
      </div>
    `;
    return;
  }

  root.innerHTML = items.map((x, index) => {
    const riskScore = Math.max(0, Math.min(100, Number(x.risk_score || 0)));
    const tone = _areaRiskTone(riskScore);
    const mos = Number(x.median_mos || 0);
    const deals = Number(x.deal_count || 0);
    const total = Number(x.total_count || 0);
    return `
      <article class="area-risk-row risk-${tone}">
        <div class="area-risk-rank">${index + 1}</div>
        <div class="area-risk-main">
          <div class="area-risk-top">
            <h4>${escHtml(x.ward || '')}</h4>
            <span class="indicator-badge level-${tone}">${escHtml(x.verdict || '')}</span>
          </div>
          <div class="risk-score-strip" aria-label="Điểm rủi ro ${riskScore}/100">
            <span style="width:${Math.max(4, riskScore)}%"></span>
          </div>
          <div class="area-risk-metrics">
            <div><strong>${riskScore}</strong><span>rủi ro</span></div>
            <div><strong>${_fmtIndicatorPct(x.distress_ratio_pct)}</strong><span>áp lực giảm</span></div>
            <div><strong>${_fmtSignedNumber(x.supply_delta, 1)}</strong><span>cung mới</span></div>
            <div><strong>${mos ? mos.toFixed(1) + '%' : '-'}</strong><span>MOS median</span></div>
            <div><strong>${deals}/${total || '-'}</strong><span>deal/tin</span></div>
          </div>
          <p>${escHtml(x.action || '')}</p>
        </div>
        <button type="button" class="opportunity-btn" data-ward="${escHtml(x.ward || '')}" onclick="_viewOpportunityWard(this.dataset.ward)">Xem deal</button>
      </article>
    `;
  }).join('');
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
  const riskContainer = document.getElementById('areaRiskRadarContainer');
  if (!distressContainer && !supplyContainer && !riskContainer) return;
  if (!['vip', 'admin'].includes(window.USER_TIER || 'guest')) {
    renderAreaRiskRadar([], {});
    _renderDistressRatio([], {});
    _renderSupplyAnomaly([], {});
    return;
  }
  if (riskContainer) riskContainer.classList.add('loading');
  if (distressContainer) distressContainer.classList.add('loading');
  if (supplyContainer) supplyContainer.classList.add('loading');
  const runId = ++marketIndicatorRunSeq;
  try {
    const data = await fetchJSONCached('marketIndicators', `/api/market-indicators?${currentFilters}`, useCache);
    if (runId !== marketIndicatorRunSeq) return;
    renderAreaRiskRadar(data.area_risk_radar || [], data.summary || {});
    _renderDistressRatio(data.distress_ratio || [], data.summary || {});
    _renderSupplyAnomaly(data.supply_anomaly || [], data.summary || {});
  } catch (err) {
    if (err.name !== 'AbortError') console.error('Market indicators error:', err);
    renderAreaRiskRadar([], {});
    _renderDistressRatio([], {});
    _renderSupplyAnomaly([], {});
  } finally {
    if (runId === marketIndicatorRunSeq) {
      if (riskContainer) riskContainer.classList.remove('loading');
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
    const sampleMap = {};
    data.forEach((d) => {
      dataMap[d.week] = d.median_ppm2;
      sampleMap[d.week] = Number(d.sample_count || 0);
    });
    const wardData = sortedKeys.map(w => dataMap[w] || null);
    const sampleCounts = sortedKeys.map(w => sampleMap[w] || 0);

    const color = colors[i % colors.length];
    datasets.push({
      label: ward,
      data: wardData,
      sampleCounts,
      borderColor: color,
      backgroundColor: color + '10',
      borderWidth: 3,
      tension: 0.4,
      fill: false,
      pointRadius: (ctx) => {
        if (sortedKeys.length > 30 || ctx.raw === null) return 0;
        return (ctx.dataset.sampleCounts[ctx.dataIndex] || 0) <= 3 ? 3 : 4;
      },
      pointHoverRadius: 8,
      pointBackgroundColor: (ctx) => {
        const count = (ctx.dataset.sampleCounts && ctx.dataset.sampleCounts[ctx.dataIndex]) || 0;
        return count > 3 ? color : _hexToRgba(color, 0.32);
      },
      pointBorderColor: (ctx) => {
        const count = (ctx.dataset.sampleCounts && ctx.dataset.sampleCounts[ctx.dataIndex]) || 0;
        return count > 3 ? color : _hexToRgba(color, 0.48);
      },
      segment: {
        borderColor: (ctx) => {
          const dataset = ctx.chart.data.datasets[ctx.datasetIndex] || {};
          const counts = dataset.sampleCounts || [];
          const lowSample = (counts[ctx.p0DataIndex] || 0) <= 3 || (counts[ctx.p1DataIndex] || 0) <= 3;
          return lowSample ? _hexToRgba(color, 0.42) : color;
        }
      },
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
          cornerRadius: 8,
          callbacks: {
            label: (ctx) => {
              const value = Number(ctx.raw || 0);
              const count = (ctx.dataset.sampleCounts && ctx.dataset.sampleCounts[ctx.dataIndex]) || 0;
              return `${ctx.dataset.label}: median ${value.toLocaleString('vi-VN', { maximumFractionDigits: 1 })} tr/m² (${_sampleCountLabel(count)})`;
            }
          }
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
