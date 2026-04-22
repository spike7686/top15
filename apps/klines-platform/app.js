const FIXED_START = '2024-01-01T08:00';
const FIXED_END = '2026-03-01T08:00';

const form = document.getElementById('query-form');
const statusEl = document.getElementById('status');
const cacheInfoEl = document.getElementById('cache-info');
const tableBody = document.querySelector('#result-table tbody');
const resultCount = document.getElementById('result-count');
const pageIndicator = document.getElementById('page-indicator');
const viewBtn = document.getElementById('view-btn');
const downloadBtn = document.getElementById('download-btn');
const prevBtn = document.getElementById('prev-btn');
const nextBtn = document.getElementById('next-btn');

let lastQuery = null;
let currentPage = 1;
let totalPages = 1;

function setStatus(message, type = 'muted') {
  statusEl.className = `status ${type}`;
  statusEl.textContent = message;
}

function renderCache(items) {
  cacheInfoEl.innerHTML = '';
  if (!items.length) {
    cacheInfoEl.innerHTML = '<div class="cache-item"><strong>暂无数据文件</strong><p>当前平台是只读展示模式。后续如需获取数据，再接回拉取逻辑。</p></div>';
    return;
  }
  for (const item of items) {
    const div = document.createElement('div');
    div.className = 'cache-item';
    div.innerHTML = `
      <strong>${item.symbol} · ${item.interval}</strong>
      <p>本地范围：${item.first_open_time_bjt || '-'} ~ ${item.last_open_time_bjt || '-'}</p>
      <p>本地行数：${item.row_count}</p>
      <p>文件：${item.file_name}</p>
    `;
    cacheInfoEl.appendChild(div);
  }
}

function renderRows(rows) {
  tableBody.innerHTML = '';
  resultCount.textContent = `${rows.length} 行`;
  for (const row of rows) {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${row.open_time_bjt}</td>
      <td>${row.open}</td>
      <td>${row.high}</td>
      <td>${row.low}</td>
      <td>${row.close}</td>
      <td>${row.volume}</td>
      <td>${row.ema5}</td>
      <td>${row.ema21}</td>
      <td>${row.ema144}</td>
    `;
    tableBody.appendChild(tr);
  }
}

function updatePager(meta) {
  currentPage = meta.page;
  totalPages = meta.total_pages;
  pageIndicator.textContent = `第 ${meta.page} 页 / 共 ${meta.total_pages} 页`;
  prevBtn.disabled = meta.page <= 1;
  nextBtn.disabled = meta.page >= meta.total_pages;
}

async function loadCacheStatus() {
  const res = await fetch('/api/cache-status');
  const data = await res.json();
  renderCache(data.items || []);
}

async function runQuery(page = 1) {
  viewBtn.disabled = true;
  setStatus('正在查询本地展示数据，请稍候...');
  const payload = {
    symbol: form.symbol.value,
    interval: form.interval.value,
    page,
    page_size: Number(form.page_size.value),
    start_bjt: FIXED_START,
    end_bjt: FIXED_END,
  };
  try {
    const res = await fetch('/api/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || '查询失败');
    renderRows(data.rows || []);
    updatePager(data.pagination);
    await loadCacheStatus();
    lastQuery = payload;
    setStatus(`完成：总计 ${data.pagination.total_rows} 行，本页 ${data.rows.length} 行。`, 'success');
  } catch (err) {
    setStatus(`失败：${err.message}`, 'error');
  } finally {
    viewBtn.disabled = false;
  }
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  await runQuery(1);
});

prevBtn.addEventListener('click', async () => {
  if (currentPage > 1) await runQuery(currentPage - 1);
});

nextBtn.addEventListener('click', async () => {
  if (currentPage < totalPages) await runQuery(currentPage + 1);
});

downloadBtn.addEventListener('click', () => {
  if (!lastQuery) {
    setStatus('请先查看一次数据，再下载当前筛选结果。', 'error');
    return;
  }
  const params = new URLSearchParams(lastQuery).toString();
  window.open(`/api/download?${params}`, '_blank');
});

loadCacheStatus().catch((err) => setStatus(`数据状态加载失败：${err.message}`, 'error'));
