const API_BASE = 'http://127.0.0.1:8080';
const REFRESH_MS = 60000;
let allRows = [];
let autoRefresh = true;
let refreshTimer = null;

const el = (id) => document.getElementById(id);

const fmtPct = (v) => {
  const n = Number(v);
  return Number.isFinite(n) ? `${n.toFixed(2)}%` : '--';
};

const fmtMoney = (v) => {
  const n = Number(v);
  if (!Number.isFinite(n)) return '--';
  if (n >= 1e12) return `$${(n / 1e12).toFixed(2)}T`;
  if (n >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(2)}M`;
  return `$${n.toFixed(2)}`;
};

async function fetchJson(path) {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function loadDashboard() {
  el('statusText').textContent = '加载中…';
  try {
    const [manifestData, latestData, snapshotsData] = await Promise.all([
      fetchJson('/api/manifest'),
      fetchJson('/api/latest-display'),
      fetchJson('/api/snapshots')
    ]);

    const manifest = manifestData.manifest || {};
    allRows = latestData.rows || [];
    renderMeta(manifest, allRows);
    renderSnapshotOptions(snapshotsData.snapshots || [], manifest.latest_snapshot_id);
    renderDynamicFilters(allRows);
    applyFilters();
    el('statusText').textContent = `已加载 ${allRows.length} 条记录`;
  } catch (err) {
    console.error(err);
    el('statusText').textContent = `加载失败：${err.message}`;
  }
}

function renderMeta(manifest, rows) {
  el('snapshotId').textContent = manifest.latest_snapshot_id || '--';
  el('capturedAt').textContent = manifest.captured_at_utc || '--';
  el('filteredCount').textContent = manifest.count_filtered ?? '--';
  el('top15Count').textContent = manifest.top15_count ?? rows.length;
  const leader = rows[0] || {};
  el('leaderSymbol').textContent = leader.symbol || '--';
  el('leaderChange').textContent = leader.change_24h_pct ? fmtPct(leader.change_24h_pct) : '--';
}

function renderSnapshotOptions(snapshots, latestId) {
  const select = el('snapshotFilter');
  const current = select.value;
  select.innerHTML = '<option value="latest">最新</option>';
  snapshots.forEach((id) => {
    const opt = document.createElement('option');
    opt.value = id;
    opt.textContent = id === latestId ? `${id}（当前）` : id;
    select.appendChild(opt);
  });
  if ([...select.options].some(opt => opt.value === current)) select.value = current;
}

function renderDynamicFilters(rows) {
  fillSelect(el('sectorFilter'), uniqueValues(rows.map(r => r.sector_primary).filter(Boolean)));
  fillSelect(el('riskFilter'), uniqueValues(rows.flatMap(r => splitTags(r.risk_flags))));
}

function fillSelect(select, values) {
  const existingFirst = select.querySelector('option[value=""]');
  select.innerHTML = '';
  if (existingFirst) select.appendChild(existingFirst);
  else {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = '全部';
    select.appendChild(opt);
  }
  values.forEach((value) => {
    const opt = document.createElement('option');
    opt.value = value;
    opt.textContent = value;
    select.appendChild(opt);
  });
}

function uniqueValues(items) {
  return [...new Set(items)].sort((a, b) => String(a).localeCompare(String(b)));
}

function splitTags(v) {
  if (!v) return [];
  return String(v).split('|').map(x => x.trim()).filter(Boolean);
}

function applyFilters() {
  const sector = el('sectorFilter').value;
  const risk = el('riskFilter').value;
  const activity = el('activityFilter').value;
  const keyword = el('searchInput').value.trim().toLowerCase();

  const filtered = allRows.filter((row) => {
    if (sector && row.sector_primary !== sector) return false;
    if (risk && !splitTags(row.risk_flags).includes(risk)) return false;
    if (activity && row.activity_bucket !== activity) return false;
    if (keyword) {
      const hay = [row.symbol, row.name, row.sector_primary, row.risk_flags, row.narrative_tags, row.narrative_summary]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
      if (!hay.includes(keyword)) return false;
    }
    return true;
  });

  renderSummaryCards(filtered);
  renderLeaderList(filtered.slice(0, 5));
  renderTable(filtered);
  el('statusText').textContent = `当前显示 ${filtered.length} / ${allRows.length} 条`;
}

function renderSummaryCards(rows) {
  const wrap = el('summaryCards');
  const sectors = uniqueValues(rows.map(r => r.sector_primary).filter(Boolean)).length;
  const avgChange = rows.length ? rows.reduce((s, r) => s + Number(r.change_24h_pct || 0), 0) / rows.length : 0;
  const highRisk = rows.filter(r => splitTags(r.risk_flags).length > 0).length;
  const veryActive = rows.filter(r => ['VeryHigh', 'High'].includes(r.activity_bucket)).length;
  const cards = [
    ['板块数', sectors],
    ['平均涨幅', fmtPct(avgChange)],
    ['高风险标签币种', highRisk],
    ['高活跃币种', veryActive]
  ];
  wrap.innerHTML = cards.map(([label, value]) => `
    <article class="stat-card">
      <span>${label}</span>
      <strong>${value}</strong>
    </article>
  `).join('');
}

function renderLeaderList(rows) {
  const wrap = el('leaderList');
  wrap.innerHTML = rows.map((row) => `
    <article class="leader-item">
      <div>
        <strong>#${row.rank_in_top15} ${row.symbol}</strong>
        <p>${row.name}</p>
      </div>
      <div class="leader-metrics">
        <span class="up">${fmtPct(row.change_24h_pct)}</span>
        <small>${fmtMoney(row.volume_24h_usd)}</small>
      </div>
    </article>
  `).join('');
}

function renderTable(rows) {
  const tbody = el('tableBody');
  tbody.innerHTML = rows.map((row) => `
    <tr>
      <td>${row.rank_in_top15}</td>
      <td>
        <div class="name-cell">
          <strong>${row.symbol}</strong>
          <span>${row.name}</span>
        </div>
      </td>
      <td><span class="pill">${row.sector_primary || '--'}</span></td>
      <td>${row.market_cap_band || '--'}</td>
      <td class="num ${Number(row.change_24h_pct) >= 0 ? 'up' : 'down'}">${fmtPct(row.change_24h_pct)}</td>
      <td class="num">${fmtMoney(row.volume_24h_usd)}</td>
      <td>${row.activity_bucket || '--'}</td>
      <td><span class="risk">${row.risk_flags || '-'}</span></td>
    </tr>
  `).join('');
}

function toggleAutoRefresh() {
  autoRefresh = !autoRefresh;
  el('autoRefreshBtn').textContent = `自动刷新：${autoRefresh ? '开' : '关'}`;
  scheduleRefresh();
}

function scheduleRefresh() {
  if (refreshTimer) clearInterval(refreshTimer);
  if (autoRefresh) refreshTimer = setInterval(loadDashboard, REFRESH_MS);
}

el('refreshBtn').addEventListener('click', loadDashboard);
el('autoRefreshBtn').addEventListener('click', toggleAutoRefresh);
['sectorFilter', 'riskFilter', 'activityFilter'].forEach((id) => el(id).addEventListener('change', applyFilters));
el('searchInput').addEventListener('input', applyFilters);
el('snapshotFilter').addEventListener('change', () => {
  el('statusText').textContent = '当前版本仅接最新数据，历史快照切换将在下一版接入。';
});

loadDashboard();
scheduleRefresh();
