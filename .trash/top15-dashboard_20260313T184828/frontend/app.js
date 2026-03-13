const fmtPct = (v) => (v === null || v === undefined || v === '' ? '--' : `${Number(v).toFixed(2)}%`);
const fmtMoney = (v) => {
  const n = Number(v);
  if (!Number.isFinite(n)) return '--';
  if (n >= 1e12) return `$${(n / 1e12).toFixed(2)}T`;
  if (n >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(2)}M`;
  return `$${n.toFixed(2)}`;
};

async function loadDashboard() {
  const status = document.getElementById('statusText');
  status.textContent = '加载中…';
  try {
    const [manifestRes, latestRes] = await Promise.all([
      fetch('/api/manifest'),
      fetch('/api/latest-display')
    ]);
    const manifestData = await manifestRes.json();
    const latestData = await latestRes.json();

    const manifest = manifestData.manifest || {};
    const rows = latestData.rows || [];

    document.getElementById('snapshotId').textContent = manifest.latest_snapshot_id || '--';
    document.getElementById('capturedAt').textContent = manifest.captured_at_utc || '--';
    document.getElementById('filteredCount').textContent = manifest.count_filtered ?? '--';

    renderLeaders(rows.slice(0, 5));
    renderTable(rows);
    status.textContent = `已加载 ${rows.length} 条记录`;
  } catch (err) {
    console.error(err);
    status.textContent = `加载失败：${err.message}`;
  }
}

function renderLeaders(rows) {
  const el = document.getElementById('leaderCards');
  el.innerHTML = rows.map(row => `
    <article class="card">
      <div class="card-top">
        <span class="rank">#${row.rank_in_top15}</span>
        <span class="sector">${row.sector_primary || '--'}</span>
      </div>
      <h3>${row.symbol}</h3>
      <p>${row.name}</p>
      <div class="metrics">
        <div><span>涨跌</span><strong>${fmtPct(row.change_24h_pct)}</strong></div>
        <div><span>成交额</span><strong>${fmtMoney(row.volume_24h_usd)}</strong></div>
        <div><span>市值</span><strong>${fmtMoney(row.market_cap_usd)}</strong></div>
      </div>
    </article>
  `).join('');
}

function renderTable(rows) {
  const el = document.getElementById('tableBody');
  el.innerHTML = rows.map(row => `
    <tr>
      <td>${row.rank_in_top15}</td>
      <td>
        <div class="name-cell">
          <strong>${row.symbol}</strong>
          <span>${row.name}</span>
        </div>
      </td>
      <td>${row.sector_primary || '--'}</td>
      <td>${row.market_cap_band || '--'}</td>
      <td class="num ${Number(row.change_24h_pct) > 0 ? 'up' : 'down'}">${fmtPct(row.change_24h_pct)}</td>
      <td class="num">${fmtMoney(row.volume_24h_usd)}</td>
      <td>${row.activity_bucket || '--'}</td>
      <td><span class="risk">${row.risk_flags || '-'}</span></td>
    </tr>
  `).join('');
}

document.getElementById('refreshBtn').addEventListener('click', loadDashboard);
loadDashboard();
