const API_BASE = '';
const REFRESH_MS = 60000;
const PAPER_SETTINGS_KEY = 'top15-paper-settings-v2';
const PAPER_POSITIONS_KEY = 'top15-paper-positions-v2';
const AUTO_TRADER_SETTINGS_KEY = 'top15-auto-trader-settings-v1';
const AUTO_TRADER_STATE_KEY = 'top15-auto-trader-state-v1';
const DEFAULT_WORKSPACE_TAB = 'short';
const DEFAULT_LIVE_TRADER_CAPITAL_USD = 4941;

const DEFAULT_PAPER_SETTINGS = {
  accountUsd: 10000,
  riskPct: 5,
  maxConcurrent: 3,
  maxGrossPct: 200,
  leverage: 2,
  profileId: 'structure_r1_h12'
};

const DEFAULT_AUTO_TRADER_SETTINGS = {
  enabled: true,
  initialEquityUsd: 10000,
  riskPct: 5,
  maxConcurrent: 3,
  maxGrossPct: 200,
  leverage: 2,
  minTier: 'standard'
};

const FALLBACK_SHORT_EXECUTION_PROFILES = {
  structure_r1_h12: {
    id: 'structure_r1_h12',
    label: '结构止损 1.0R / 12h',
    signalLabel: 'structure',
    useStructureStop: true,
    tpR: 1,
    maxHoldHours: 12,
    sampleCount: 10,
    rawSampleCount: 17,
    winRate: 0.8,
    meanR: 0.3297,
    profitFactor: 4.1408,
    tpRate: 0.4,
    slRate: 0.1,
    timeoutRate: 0.5,
    medianHours: 8.7618,
    meanStopPct: 2.6133,
    medianStopPct: 2.669,
    medianNotionalPct: 187.3361,
    stopWindowMinPct: 0.8,
    stopWindowMaxPct: 4.5,
    riskBudgetPct: 5,
    meanPnlPct: 1.6485
  }
};

const FALLBACK_SHADOW_STRATEGIES = {
  A_post_confirm_weak_turn: {
    code: 'A',
    label: 'A / 严格后确认转弱',
    signal_name: 'post_confirm_weak_turn',
    description: '当前正式规则：确认锚点成立后，等 1h 趋势转弱、无突破、24h 涨幅回到 3% 到 8% 再做结构空。',
    entry_filters: ['no_breakout_1h', 'chg_3_8']
  },
  B_no_breakout_fade: {
    code: 'B',
    label: 'B / NoBreakout Fade',
    signal_name: 'no_breakout_fade',
    description: '仍在交叉候选池内，30m 排名和交叉分同步转弱，且 1h 已无突破结构。',
    entry_filters: [],
    target_r_multiple: 1
  },
  B_no_breakout_fade_wide: {
    code: 'B+',
    label: 'B+ / NoBreakout Wide',
    signal_name: 'no_breakout_fade_wide',
    description: 'B 对照组：结构止损窗口放宽到 3%~20%，止盈改为 1.5R，专门验证大波动回撤能否带来更大跌幅。',
    entry_filters: [],
    stop_window_min_pct: 3,
    stop_window_max_pct: 20,
    target_r_multiple: 1.5
  },
  B_no_breakout_fade_wide_hold: {
    code: 'B++',
    label: 'B++ / NoBreakout Hold-Split',
    signal_name: 'no_breakout_fade_wide_hold',
    description: 'B+ 的持仓拆分版：入场仍要求 NoBreakout + 30m 转弱，但持仓只看重新走强、突破恢复或回到前高，不因 entry 条件自然衰减而提前离场。',
    entry_filters: [],
    stop_window_min_pct: 3,
    stop_window_max_pct: 20,
    target_r_multiple: 1.5
  },
  C_overheat_fade: {
    code: 'C',
    label: 'C / Overheat Fade',
    signal_name: 'overheat_fade',
    description: '仍在交叉候选池内，24h 涨幅和换手已过热，30m 动能开始转弱。',
    entry_filters: [],
    target_r_multiple: 1
  },
  C_overheat_fade_wide: {
    code: 'C+',
    label: 'C+ / Overheat Wide',
    signal_name: 'overheat_fade_wide',
    description: 'C 对照组：结构止损窗口放宽到 3%~20%，止盈改为 1.5R，优先捕捉过热后的一段大跌幅。',
    entry_filters: [],
    stop_window_min_pct: 3,
    stop_window_max_pct: 20,
    target_r_multiple: 1.5
  },
  C_overheat_fade_wide_hold: {
    code: 'C++',
    label: 'C++ / Overheat Hold-Split',
    signal_name: 'overheat_fade_wide_hold',
    description: 'C+ 的持仓拆分版：入场仍要求过热 + 30m 转弱，但持仓不再要求继续过热或继续 overlap，只在重新走强或回到前高时提前退出。',
    entry_filters: [],
    stop_window_min_pct: 3,
    stop_window_max_pct: 20,
    target_r_multiple: 1.5
  },
  D_extreme_overheat_fade: {
    code: 'D',
    label: 'D / Extreme Overheat Fade',
    signal_name: 'extreme_overheat_fade',
    description: '仍在交叉候选池内，进入极端过热区后，darkhorse 和 overlap 分数同时转弱。',
    entry_filters: [],
    target_r_multiple: 1
  },
  D_extreme_overheat_fade_wide: {
    code: 'D+',
    label: 'D+ / Extreme Wide',
    signal_name: 'extreme_overheat_fade_wide',
    description: 'D 对照组：结构止损窗口放宽到 3%~20%，止盈改为 1.5R，专门测试极端过热后的大幅回撤。',
    entry_filters: [],
    stop_window_min_pct: 3,
    stop_window_max_pct: 20,
    target_r_multiple: 1.5
  },
  D_extreme_overheat_fade_wide_hold: {
    code: 'D++',
    label: 'D++ / Extreme Hold-Split',
    signal_name: 'extreme_overheat_fade_wide_hold',
    description: 'D+ 的持仓拆分版：入场仍要求极端过热 + 极端转弱，但持仓只在重新增强或回到前高时退出，不因极端过热消退而离场。',
    entry_filters: [],
    stop_window_min_pct: 3,
    stop_window_max_pct: 20,
    target_r_multiple: 1.5
  }
};

const FALLBACK_SHORT_STRATEGY_CONFIG = {
  strategy_version: 'post_confirm_weak_turn_v1',
    paper_trader_version: 'server_paper_trader_v5_shadow_books_controls',
  strategy: {
    signal_name: 'post_confirm_weak_turn',
    display_name: '后确认转弱开空',
    anchor: {
      recent_overlap_field: 'recent_overlap_candidate_2h',
      recent_overlap_window_hours: 2,
      min_top15_persistence_hours: 1
    },
    weakening: {
      trend_1h_values: ['Range', 'Down', 'StrongDown'],
      overlap_score_delta_30m_max: 0,
      breakout_1h_required: 'NoBreakout',
      change_24h_min_pct: 3,
      change_24h_max_pct: 8
    },
    confirmations: {
      default: {
        basis_rate_delta_vs_mean_1h_max: 0,
        top_trader_position_lsr_change_1h_pct_max: 0
      },
      historical_sniper: {
        oi_change_1h_pct_min_exclusive: 0,
        basis_rate_latest_max: -0.006,
        top_trader_account_lsr_latest_min: 1.18
      },
      live_sniper: {
        oi_change_1h_pct_min_exclusive: 0,
        perp_premium_pct_vs_spot_max: -0.4
      }
    }
  },
  structure: {
    profile_id: 'structure_r1_h12',
    profile_label: '结构止损 1.0R / 12h',
    front_high_lookback_h: 2,
    vol_lookback_h: 1,
    atr_period: 14,
    stop_buffer_mult: 0.35,
    min_buffer_pct: 0.15,
    stop_window_min_pct: 0.8,
    stop_window_max_pct: 4.5,
    tp_r: 1,
    max_hold_hours: 12
  },
  risk: {
    initial_equity_usd: 10000,
    risk_pct: 5,
    max_concurrent: 3,
    max_gross_pct: 200,
    leverage: 2,
    min_tier: 'standard'
  },
  research: {
    focus_signal_name: 'post_confirm_weak_turn',
    focus_signal_definition: 'Current overlap_candidate=true or recent 2h overlap_candidate=true, then trend_1h turns to Range/Down/StrongDown and overlap_score_delta_30m <= 0.',
    entry_filters: ['no_breakout_1h', 'chg_3_8']
  },
  shadow_layers: FALLBACK_SHADOW_STRATEGIES
};

let shortStrategyConfig = FALLBACK_SHORT_STRATEGY_CONFIG;

let allRows = [];
let latestManifest = {};
let autoRefresh = true;
let refreshTimer = null;
let algoPanelOpen = false;
let paperSettings = loadPaperSettings();
let paperPositions = loadPaperPositions();
let autoTraderSettings = loadAutoTraderSettings();
let autoTraderState = loadAutoTraderState();
let serverPaperTrader = null;
let liveTraderTestnet = null;
let liveTraderAccounts = [];
let selectedLiveTraderAccountId = null;
let selectedLiveTraderAccountDetail = null;
let selectedLiveTraderAccountDetailError = null;
let liveTraderAccountsLoadError = null;
let activeWorkspaceTab = DEFAULT_WORKSPACE_TAB;
let openAutoCurveStrategyId = null;
const autoCurveHistoryCache = new Map();
const liveCurveHistoryCache = new Map();
const liveAccountCurveHistoryCache = new Map();

const el = (id) => document.getElementById(id);
const setControlValue = (id, value) => {
  const node = el(id);
  if (node) node.value = value;
  return node;
};
const setText = (id, value) => {
  const node = el(id);
  if (node) node.textContent = value;
  return node;
};
const readControlValue = (id, fallback = '') => {
  const node = el(id);
  return node ? node.value : fallback;
};

function setWorkspaceTab(tabId = DEFAULT_WORKSPACE_TAB) {
  activeWorkspaceTab = ['short', 'overview', 'live', 'mainnet'].includes(tabId) ? tabId : DEFAULT_WORKSPACE_TAB;
  document.querySelectorAll('.workspace-tab').forEach((button) => {
    const isActive = button.dataset.tabTarget === activeWorkspaceTab;
    button.classList.toggle('is-active', isActive);
    button.setAttribute('aria-selected', String(isActive));
  });
  document.querySelectorAll('[data-workspace-panel]').forEach((panel) => {
    panel.classList.toggle('is-active', panel.dataset.workspacePanel === activeWorkspaceTab);
  });
}

const ALGO_MARKDOWN = `# 结构特征层 + 黑马筛选层 + 持续走强筛选层 + 交叉确认层算法说明

## 一、目标
这套算法不是黑箱预测模型，而是“规则型、多因子、可解释”的研究框架。
目标是把 TOP15 中的标的拆成：
1. 数据层：当前价格、成交额、活跃度、K线历史、在榜时间
2. 特征层：趋势、突破、回撤、动量、换手、结构强弱
3. 结论层：黑马分、持续走强分、交叉确认分

---

## 二、数据层
### 过滤规则
- 24h 成交额 > 1500 万美元
- 剔除稳定币
- 时间统一按北京时间展示
- 仅保留 Binance 现货可交易标的

### 数据源
- 主源：CoinPaprika（价格、成交额、市值、涨跌幅）
- 复核：Binance 24h ticker（成交笔数、报价成交额、活跃度）
- K线：Binance 1h / 4h / 1d，最近 7 天
- 历史在榜：本地 history.csv / history.jsonl

### 时间确认字段
- top15_persistence_hours
- top15_presence_ratio_24h
- top15_presence_snapshots_24h
- top15_snapshot_count_24h

---

## 三、结构特征层
- 趋势：trend_1d / trend_4h / trend_1h
- 突破：breakout_1h / breakout_4h
- 回撤：max_drawdown_7d_pct
- 结构结论：structure_score / structure_grade / structure_state

---

## 四、黑马筛选层
回答：
“这个币值不值得作为重点黑马候选，是否有机会冲进前五并维持？”

输出字段：
- darkhorse_score
- top5_potential
- sustainability
- risk_reward_profile
- darkhorse_tag

---

## 五、持续走强筛选层
回答：
“在观察窗口内，这个币是不是更可能继续保持强势，而不是一日游？”

输出字段：
- persistence_score
- persistence_label
- continuation_risk
- continuation_evidence

---

## 六、交叉确认层
回答：
“这个币是否已经同时满足黑马、持续走强和在榜时间确认，属于更值得重点跟踪的趋势候选？”

### 基础门槛
- darkhorse_score >= 7
- persistence_score >= 5
- top15_persistence_hours >= 1
- continuation_risk != High
- trend_1d / trend_4h 不转弱

### 输出字段
- overlap_gate_pass
- overlap_score
- overlap_label
- overlap_rank_signal
- overlap_candidate
- overlap_evidence

### overlap_score 核心思想
- 黑马强：加分
- 持续走强强：加分
- 在榜持续时间够长：加分
- 24h 在榜占比高：加分
- 中周期趋势向上：加分
- 回撤过深 / 延续风险高：减分

---

## 七、页面中如何阅读
- 黑马候选榜：看爆发力
- 持续走强候选榜：看延续性
- 交叉确认候选榜：看最终趋势确认度
- 反向做空研究：只看交叉确认后动能衰减的末端回落

这意味着页面不是只告诉你“谁涨得快”，而是告诉你“谁更可能成为更高质量的趋势候选，以及哪些候选在确认后开始失速，适合研究反向做空”。`;

function toNum(value) {
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

function toBool(value) {
  return value === true || value === 'True' || value === 'true' || value === 1 || value === '1';
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

const fmtPct = (v) => {
  const n = toNum(v);
  return n !== null ? `${n.toFixed(2)}%` : '--';
};

const fmtSignedPct = (v) => {
  const n = toNum(v);
  if (n === null) return '--';
  return `${n > 0 ? '+' : ''}${n.toFixed(2)}%`;
};

const fmtSignedPctCompact = (v) => {
  const n = toNum(v);
  if (n === null) return '--';
  const digits = Math.abs(n) < 0.1 ? 4 : 2;
  return `${n > 0 ? '+' : ''}${n.toFixed(digits)}%`;
};

const fmtMoney = (v) => {
  const n = toNum(v);
  if (n === null) return '--';
  if (Math.abs(n) >= 1e12) return `$${(n / 1e12).toFixed(2)}T`;
  if (Math.abs(n) >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (Math.abs(n) >= 1e6) return `$${(n / 1e6).toFixed(2)}M`;
  if (Math.abs(n) >= 1) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(6)}`;
};

const fmtSignedMoney = (v) => {
  const n = toNum(v);
  if (n === null) return '--';
  return `${n > 0 ? '+' : ''}${fmtMoney(n)}`;
};

const fmtNum = (v) => {
  const n = toNum(v);
  return n !== null ? n.toFixed(2) : '--';
};

const fmtSignedNum = (v) => {
  const n = toNum(v);
  return n !== null ? `${n > 0 ? '+' : ''}${n.toFixed(2)}` : '--';
};

const fmtHours = (v) => {
  const n = toNum(v);
  return n !== null ? `${n.toFixed(2)}h` : '--';
};

const fmtRatio = (v) => {
  const n = toNum(v);
  return n !== null ? `${(n * 100).toFixed(1)}%` : '--';
};

const fmtPathClass = (v) => {
  if (!v) return '--';
  const map = {
    FastRank_FastConfirm: '快推进 / 快确认',
    FastRank_SlowConfirm: '快推进 / 慢确认',
    SlowRank_FastConfirm: '慢推进 / 快确认',
    SlowRank_SlowConfirm: '慢推进 / 慢确认',
    HighVolatile_ConfirmLate: '高波动 / 晚确认',
    StableAdvance_ConfirmMid: '稳推进 / 中段确认',
    Unclassified: '待归类'
  };
  return map[v] || v;
};

const fmtPathTone = (v) => {
  const key = String(v || '');
  if (key.includes('FastConfirm')) return 'up';
  if (key.includes('SlowConfirm') || key.includes('HighVolatile')) return 'risk';
  return '';
};

const fmtSnapshotTime = (cst, utc) => {
  if (cst) {
    const dt = new Date(cst);
    if (!Number.isNaN(dt.getTime())) {
      return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')} ${String(dt.getHours()).padStart(2, '0')}:${String(dt.getMinutes()).padStart(2, '0')}:${String(dt.getSeconds()).padStart(2, '0')} GMT+8`;
    }
    return `${cst} GMT+8`;
  }
  if (utc) {
    const dt = new Date(utc);
    if (!Number.isNaN(dt.getTime())) {
      const cstDt = new Date(dt.getTime() + 8 * 60 * 60 * 1000);
      return `${cstDt.getUTCFullYear()}-${String(cstDt.getUTCMonth() + 1).padStart(2, '0')}-${String(cstDt.getUTCDate()).padStart(2, '0')} ${String(cstDt.getUTCHours()).padStart(2, '0')}:${String(cstDt.getUTCMinutes()).padStart(2, '0')}:${String(cstDt.getUTCSeconds()).padStart(2, '0')} GMT+8`;
    }
  }
  return '--';
};

function fmtLocalDateTime(value) {
  if (!value) return '--';
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return '--';
  return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')} ${String(dt.getHours()).padStart(2, '0')}:${String(dt.getMinutes()).padStart(2, '0')}`;
}

function safeReadStorage(key, fallback) {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return fallback;
    return JSON.parse(raw);
  } catch (err) {
    console.warn('storage read failed', err);
    return fallback;
  }
}

function safeWriteStorage(key, value) {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch (err) {
    console.warn('storage write failed', err);
  }
}

function normalizeShortStrategyConfig(value) {
  const input = value && typeof value === 'object' ? value : {};
  const fallback = FALLBACK_SHORT_STRATEGY_CONFIG;
  return {
    ...fallback,
    ...input,
    strategy: {
      ...fallback.strategy,
      ...(input.strategy || {}),
      anchor: {
        ...fallback.strategy.anchor,
        ...((input.strategy || {}).anchor || {})
      },
      weakening: {
        ...fallback.strategy.weakening,
        ...((input.strategy || {}).weakening || {})
      },
      confirmations: {
        ...fallback.strategy.confirmations,
        ...((input.strategy || {}).confirmations || {}),
        default: {
          ...fallback.strategy.confirmations.default,
          ...((((input.strategy || {}).confirmations || {}).default) || {})
        },
        historical_sniper: {
          ...fallback.strategy.confirmations.historical_sniper,
          ...((((input.strategy || {}).confirmations || {}).historical_sniper) || {})
        },
        live_sniper: {
          ...fallback.strategy.confirmations.live_sniper,
          ...((((input.strategy || {}).confirmations || {}).live_sniper) || {})
        }
      }
    },
    structure: {
      ...fallback.structure,
      ...(input.structure || {})
    },
    risk: {
      ...fallback.risk,
      ...(input.risk || {})
    },
    research: {
      ...fallback.research,
      ...(input.research || {})
    }
  };
}

function defaultPaperSettings() {
  const risk = shortStrategyConfig.risk || {};
  const structure = shortStrategyConfig.structure || {};
  return {
    ...DEFAULT_PAPER_SETTINGS,
    accountUsd: toNum(risk.initial_equity_usd) ?? DEFAULT_PAPER_SETTINGS.accountUsd,
    riskPct: toNum(risk.risk_pct) ?? DEFAULT_PAPER_SETTINGS.riskPct,
    maxConcurrent: Math.round(toNum(risk.max_concurrent) ?? DEFAULT_PAPER_SETTINGS.maxConcurrent),
    maxGrossPct: toNum(risk.max_gross_pct) ?? DEFAULT_PAPER_SETTINGS.maxGrossPct,
    leverage: toNum(risk.leverage) ?? DEFAULT_PAPER_SETTINGS.leverage,
    profileId: structure.profile_id || DEFAULT_PAPER_SETTINGS.profileId
  };
}

function defaultAutoTraderSettings() {
  const risk = shortStrategyConfig.risk || {};
  return {
    ...DEFAULT_AUTO_TRADER_SETTINGS,
    initialEquityUsd: toNum(risk.initial_equity_usd) ?? DEFAULT_AUTO_TRADER_SETTINGS.initialEquityUsd,
    riskPct: toNum(risk.risk_pct) ?? DEFAULT_AUTO_TRADER_SETTINGS.riskPct,
    maxConcurrent: Math.round(toNum(risk.max_concurrent) ?? DEFAULT_AUTO_TRADER_SETTINGS.maxConcurrent),
    maxGrossPct: toNum(risk.max_gross_pct) ?? DEFAULT_AUTO_TRADER_SETTINGS.maxGrossPct,
    leverage: toNum(risk.leverage) ?? DEFAULT_AUTO_TRADER_SETTINGS.leverage,
    minTier: risk.min_tier || DEFAULT_AUTO_TRADER_SETTINGS.minTier
  };
}

function getShortExecutionProfiles() {
  const fallbackProfiles = FALLBACK_SHORT_EXECUTION_PROFILES;
  const structure = shortStrategyConfig.structure || {};
  const risk = shortStrategyConfig.risk || {};
  const fallbackId = Object.keys(fallbackProfiles)[0];
  const profileId = structure.profile_id || fallbackId;
  const base = fallbackProfiles[profileId] || fallbackProfiles[fallbackId];
  return {
    [profileId]: {
      ...base,
      id: profileId,
      label: structure.profile_label || base.label,
      signalLabel: (shortStrategyConfig.strategy || {}).signal_name || base.signalLabel,
      tpR: toNum(structure.tp_r) ?? base.tpR,
      maxHoldHours: toNum(structure.max_hold_hours) ?? base.maxHoldHours,
      stopWindowMinPct: toNum(structure.stop_window_min_pct) ?? base.stopWindowMinPct,
      stopWindowMaxPct: toNum(structure.stop_window_max_pct) ?? base.stopWindowMaxPct,
      riskBudgetPct: toNum(risk.risk_pct) ?? base.riskBudgetPct
    }
  };
}

function buildShortResearchCards() {
  const strategy = shortStrategyConfig.strategy || {};
  const anchor = strategy.anchor || {};
  const weakening = strategy.weakening || {};
  const historicalSniper = (strategy.confirmations || {}).historical_sniper || {};
  const liveSniper = (strategy.confirmations || {}).live_sniper || {};
  const defaults = defaultPaperSettings();
  return [
    {
      title: '结构主策略',
      kicker: '后确认转弱执行模板',
      selected: true,
      lines: [
        `触发骨架：${strategy.signal_name || 'post_confirm_weak_turn'} + no_breakout_1h + chg_3_8，不在第一次冲榜时提前埋伏。`,
        `执行：前高(${toNum(shortStrategyConfig.structure?.front_high_lookback_h) ?? 2}h) + ${fmtNum(shortStrategyConfig.structure?.stop_buffer_mult)} x ATR14(1h) 做结构止损，止盈 ${fmtNum(shortStrategyConfig.structure?.tp_r)}R，最长持有 ${fmtHours(shortStrategyConfig.structure?.max_hold_hours)}。`,
        `默认风控：单笔风险 ${fmtPct(defaults.riskPct)} 账户权益，默认总名义敞口上限 ${fmtPct(defaults.maxGrossPct)}，可交易止损窗 ${fmtPct(shortStrategyConfig.structure?.stop_window_min_pct)} 到 ${fmtPct(shortStrategyConfig.structure?.stop_window_max_pct)}。`
      ]
    },
    {
      title: '主触发层',
      kicker: '标准开空入场层',
      lines: [
        `必须先满足：当前 overlap_candidate = true，或最近 ${fmtHours(anchor.recent_overlap_window_hours)} 内曾进入 overlap_candidate；随后 trend_1h 转为 ${(weakening.trend_1h_values || []).join(' / ')}，且 overlap_score_delta_30m <= ${fmtNum(weakening.overlap_score_delta_30m_max)}。`,
        `再过滤：breakout_1h = ${weakening.breakout_1h_required || 'NoBreakout'}，24h 涨幅在 ${fmtPct(weakening.change_24h_min_pct)} 到 ${fmtPct(weakening.change_24h_max_pct)}。`,
        '这层成立后才进入“标准开空”，否则只保留在“观察层”。'
      ]
    },
    {
      title: '默认确认层',
      kicker: '已有历史支撑 n=5',
      lines: [
        `优先确认：basis_rate_delta_vs_mean_1h <= ${fmtNum(((strategy.confirmations || {}).default || {}).basis_rate_delta_vs_mean_1h_max)}，说明贴水在走弱；或 top_trader_position_lsr_change_1h_pct < ${fmtNum(((strategy.confirmations || {}).default || {}).top_trader_position_lsr_change_1h_pct_max)}，说明仓位拥挤开始撤退。`,
        '这两个过滤子集历史上都是 n=5，胜率 80%，平均约 +0.79R。',
        '当前实时流里这些字段未持续补齐时，页面会标成“待补采”，不会强行打高分。'
      ]
    },
    {
      title: '高置信层',
      kicker: '窄样本强确认 n=3',
      lines: [
        `最强历史确认：oi_change_1h_pct > ${fmtNum(historicalSniper.oi_change_1h_pct_min_exclusive)} 且 basis_rate_latest <= ${fmtNum(historicalSniper.basis_rate_latest_max)}，或 top_trader_account_lsr_latest >= ${fmtNum(historicalSniper.top_trader_account_lsr_latest_min)}。`,
        '这组历史子集都是 n=3，胜率 100%，平均 1.0R。',
        `当前在线替代层采用 OI 1h 扩张 + perp premium 深贴水(${fmtPct(liveSniper.perp_premium_pct_vs_spot_max)})；funding <= 0 只做加分，不单独触发。`
      ]
    },
    {
      title: '排除项',
      kicker: '不要硬等错误确认',
      lines: [
        '不要把 liq_long_flush_5m 当成主触发，它在历史里 win_rate 只有 33.3%，mean_R 为负。',
        `不是所有转弱都能空，结构止损必须落在 ${fmtPct(shortStrategyConfig.structure?.stop_window_min_pct)} 到 ${fmtPct(shortStrategyConfig.structure?.stop_window_max_pct)} 的可交易窗口内。`,
        '当前页面模拟仓位只做研究记录，不接交易所，也不计真实滑点与借币成本。'
      ]
    }
  ];
}

function loadPaperSettings() {
  const raw = safeReadStorage(PAPER_SETTINGS_KEY, {});
  return sanitizePaperSettings(raw);
}

function sanitizePaperSettings(value) {
  const defaults = defaultPaperSettings();
  const profiles = getShortExecutionProfiles();
  const next = { ...defaults, ...(value || {}) };
  if (toNum(next.riskPct) === 0.25) next.riskPct = defaults.riskPct;
  if (toNum(next.maxGrossPct) === 30) next.maxGrossPct = defaults.maxGrossPct;
  next.accountUsd = clamp(toNum(next.accountUsd) || defaults.accountUsd, 100, 100000000);
  next.riskPct = clamp(toNum(next.riskPct) || defaults.riskPct, 0.1, 10);
  next.maxConcurrent = clamp(Math.round(toNum(next.maxConcurrent) || defaults.maxConcurrent), 1, 20);
  next.maxGrossPct = clamp(toNum(next.maxGrossPct) || defaults.maxGrossPct, 5, 300);
  next.leverage = clamp(toNum(next.leverage) || defaults.leverage, 1, 20);
  if (!profiles[next.profileId]) next.profileId = defaults.profileId;
  return next;
}

function loadPaperPositions() {
  const raw = safeReadStorage(PAPER_POSITIONS_KEY, []);
  if (!Array.isArray(raw)) return [];
  return raw.map((item) => ({ ...item })).filter((item) => item && item.id && item.symbol);
}

function loadAutoTraderSettings() {
  const raw = safeReadStorage(AUTO_TRADER_SETTINGS_KEY, {});
  return sanitizeAutoTraderSettings(raw);
}

function sanitizeAutoTraderSettings(value) {
  const defaults = defaultAutoTraderSettings();
  const next = { ...defaults, ...(value || {}) };
  next.enabled = Boolean(next.enabled);
  if (toNum(next.riskPct) === 0.25) next.riskPct = defaults.riskPct;
  if (toNum(next.maxGrossPct) === 30) next.maxGrossPct = defaults.maxGrossPct;
  next.initialEquityUsd = clamp(toNum(next.initialEquityUsd) || defaults.initialEquityUsd, 100, 100000000);
  next.riskPct = clamp(toNum(next.riskPct) || defaults.riskPct, 0.1, 10);
  next.maxConcurrent = clamp(Math.round(toNum(next.maxConcurrent) || defaults.maxConcurrent), 1, 20);
  next.maxGrossPct = clamp(toNum(next.maxGrossPct) || defaults.maxGrossPct, 5, 300);
  next.leverage = clamp(toNum(next.leverage) || defaults.leverage, 1, 20);
  next.minTier = ['standard', 'sniper'].includes(next.minTier) ? next.minTier : defaults.minTier;
  return next;
}

function freshAutoTraderState() {
  return {
    startingEquityUsd: autoTraderSettings.initialEquityUsd,
    orders: [],
    events: [],
    lastProcessedSnapshotId: null,
    lastProcessedAt: null,
    createdAt: new Date().toISOString()
  };
}

function loadAutoTraderState() {
  const raw = safeReadStorage(AUTO_TRADER_STATE_KEY, null);
  return sanitizeAutoTraderState(raw);
}

function sanitizeAutoTraderState(value) {
  const base = freshAutoTraderState();
  if (!value || typeof value !== 'object') return base;
  const next = { ...base, ...value };
  next.startingEquityUsd = clamp(toNum(next.startingEquityUsd) || autoTraderSettings.initialEquityUsd, 100, 100000000);
  next.orders = Array.isArray(next.orders)
    ? next.orders.map((item) => ({ ...item })).filter((item) => item && item.id && item.symbol)
    : [];
  next.events = Array.isArray(next.events)
    ? next.events.map((item) => ({ ...item })).filter((item) => item && item.id)
    : [];
  return next;
}

function savePaperSettings() {
  safeWriteStorage(PAPER_SETTINGS_KEY, paperSettings);
}

function savePaperPositions() {
  safeWriteStorage(PAPER_POSITIONS_KEY, paperPositions);
}

function saveAutoTraderSettings() {
  safeWriteStorage(AUTO_TRADER_SETTINGS_KEY, autoTraderSettings);
}

function saveAutoTraderState() {
  safeWriteStorage(AUTO_TRADER_STATE_KEY, autoTraderState);
}

function currentProfile() {
  const profiles = getShortExecutionProfiles();
  const defaults = defaultPaperSettings();
  return profiles[paperSettings.profileId] || profiles[defaults.profileId] || Object.values(profiles)[0];
}

function getCurrentPrice(row) {
  return toNum(row.binance_last_price) || toNum(row.price_usd) || null;
}

function getRowBySymbol(symbol) {
  return allRows.find((row) => row.symbol === symbol) || null;
}

function calcShortPnlPct(entryPrice, exitPrice) {
  const entry = toNum(entryPrice);
  const exit = toNum(exitPrice);
  if (entry === null || exit === null || entry <= 0) return null;
  return ((entry - exit) / entry) * 100;
}

function splitTags(v) {
  if (!v) return [];
  return String(v).split('|').map((x) => x.trim()).filter(Boolean);
}

function uniqueValues(items) {
  return [...new Set(items)].sort((a, b) => String(a).localeCompare(String(b)));
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

async function fetchJson(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, options);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

function getShadowStrategyDefs() {
  const configured = shortStrategyConfig.shadow_layers && typeof shortStrategyConfig.shadow_layers === 'object'
    ? shortStrategyConfig.shadow_layers
    : {};
  const defs = {};
  Object.entries(FALLBACK_SHADOW_STRATEGIES).forEach(([strategyId, fallbackDef]) => {
    defs[strategyId] = { ...fallbackDef, ...(configured[strategyId] || {}) };
  });
  return defs;
}

function emptyServerStrategyBook(strategyId, def = {}) {
  const risk = shortStrategyConfig.risk || {};
  const structure = shortStrategyConfig.structure || {};
  return {
    strategy_id: strategyId,
    strategy_code: def.code || '--',
    strategy_label: def.label || strategyId,
    description: def.description || '',
    entry_live: true,
    entry_armed_snapshot_id: null,
    entry_armed_at: null,
    config: {
      strategy_id: strategyId,
      strategy_code: def.code || '--',
      strategy_label: def.label || strategyId,
      signal_name: def.signal_name || strategyId,
      entry_filters: Array.isArray(def.entry_filters) ? [...def.entry_filters] : [],
      initial_equity_usd: toNum(risk.initial_equity_usd) ?? 10000,
      risk_pct: toNum(risk.risk_pct) ?? 5,
      max_concurrent: Math.round(toNum(risk.max_concurrent) ?? 3),
      max_gross_pct: toNum(risk.max_gross_pct) ?? 200,
      leverage: toNum(risk.leverage) ?? 2,
      max_hold_hours: toNum(structure.max_hold_hours) ?? 12,
      stop_window_min_pct: toNum(def.stop_window_min_pct) ?? toNum(structure.stop_window_min_pct) ?? 0.8,
      stop_window_max_pct: toNum(def.stop_window_max_pct) ?? toNum(structure.stop_window_max_pct) ?? 4.5,
      target_r_multiple: toNum(def.target_r_multiple) ?? 1
    },
    summary: {
      starting_equity_usd: toNum(risk.initial_equity_usd) ?? 10000,
      equity_usd: toNum(risk.initial_equity_usd) ?? 10000,
      realized_pnl_usd: 0,
      unrealized_pnl_usd: 0,
      open_gross_usd: 0,
      gross_cap_usd: 0,
      open_count: 0,
      closed_count: 0,
      win_count: 0,
      loss_count: 0,
      total_realized_r: 0,
      total_order_count: 0,
      win_rate: null,
      equity_peak_usd: toNum(risk.initial_equity_usd) ?? 10000,
      max_drawdown_usd: 0,
      max_drawdown_pct: 0,
      equity_change_last_snapshot_usd: 0,
      equity_change_last_snapshot_pct: 0,
      curve_point_count: 0
    },
    open_orders: [],
    recent_closed_orders: [],
    recent_events: [],
    recent_equity_curve: []
  };
}

function aggregateServerBookSummary(strategyBooks) {
  const books = Object.values(strategyBooks || {});
  const startingEquityUsd = books.reduce((sum, book) => sum + (toNum(book.summary?.starting_equity_usd) || 0), 0);
  const equityUsd = books.reduce((sum, book) => sum + (toNum(book.summary?.equity_usd) || 0), 0);
  const realizedPnlUsd = books.reduce((sum, book) => sum + (toNum(book.summary?.realized_pnl_usd) || 0), 0);
  const unrealizedPnlUsd = books.reduce((sum, book) => sum + (toNum(book.summary?.unrealized_pnl_usd) || 0), 0);
  const openGrossUsd = books.reduce((sum, book) => sum + (toNum(book.summary?.open_gross_usd) || 0), 0);
  const grossCapUsd = books.reduce((sum, book) => sum + (toNum(book.summary?.gross_cap_usd) || 0), 0);
  const openCount = books.reduce((sum, book) => sum + (toNum(book.summary?.open_count) || 0), 0);
  const closedCount = books.reduce((sum, book) => sum + (toNum(book.summary?.closed_count) || 0), 0);
  const winCount = books.reduce((sum, book) => sum + (toNum(book.summary?.win_count) || 0), 0);
  const lossCount = books.reduce((sum, book) => sum + (toNum(book.summary?.loss_count) || 0), 0);
  const totalRealizedR = books.reduce((sum, book) => sum + (toNum(book.summary?.total_realized_r) || 0), 0);
  const totalOrderCount = books.reduce((sum, book) => sum + (toNum(book.summary?.total_order_count) || 0), 0);
  const equityChangeLastSnapshotUsd = books.reduce((sum, book) => sum + (toNum(book.summary?.equity_change_last_snapshot_usd) || 0), 0);
  return {
    starting_equity_usd: startingEquityUsd,
    equity_usd: equityUsd,
    realized_pnl_usd: realizedPnlUsd,
    unrealized_pnl_usd: unrealizedPnlUsd,
    open_gross_usd: openGrossUsd,
    gross_cap_usd: grossCapUsd,
    open_count: openCount,
    closed_count: closedCount,
    win_count: winCount,
    loss_count: lossCount,
    total_realized_r: totalRealizedR,
    total_order_count: totalOrderCount,
    win_rate: closedCount ? winCount / closedCount : null,
    equity_peak_usd: null,
    max_drawdown_usd: 0,
    max_drawdown_pct: null,
    equity_change_last_snapshot_usd: equityChangeLastSnapshotUsd,
    equity_change_last_snapshot_pct: null,
    curve_point_count: 0,
    strategy_book_count: books.length
  };
}

function getSummaryOrderCount(summary = {}) {
  return Math.round(toNum(summary.total_order_count) ?? ((toNum(summary.open_count) || 0) + (toNum(summary.closed_count) || 0)));
}

function fmtCurveChange(summary = {}) {
  const usd = toNum(summary.equity_change_last_snapshot_usd);
  const pct = toNum(summary.equity_change_last_snapshot_pct);
  const usdText = fmtSignedMoney(usd);
  const pctText = pct === null ? '--' : fmtSignedPct(pct);
  return `${usdText} ｜ ${pctText}`;
}

function fmtDrawdownStat(summary = {}) {
  const usd = toNum(summary.max_drawdown_usd);
  const pct = toNum(summary.max_drawdown_pct);
  const usdText = fmtMoney(usd);
  const pctText = pct === null ? '--' : fmtPct(pct);
  return `${usdText} ｜ ${pctText}`;
}

const MINI_CURVE_LOOKBACK_HOURS = 4;
const MINI_CURVE_FALLBACK_POINT_LIMIT = 96;
const FULL_CURVE_POINT_LIMIT = 144;

function normalizeEquitySeries(rows = [], limit = MINI_CURVE_FALLBACK_POINT_LIMIT) {
  const series = [...rows]
    .map((row) => ({
      ts: new Date(row.captured_at_utc || row.captured_at_cst || 0).getTime(),
      equity: toNum(row.equity_usd)
    }))
    .filter((item) => Number.isFinite(item.ts) && item.equity !== null)
    .sort((a, b) => a.ts - b.ts);

  if (!limit || series.length <= limit) return series;
  return series.slice(-limit);
}

function pickRecentSeriesByHours(rows = [], hours = MINI_CURVE_LOOKBACK_HOURS, fallbackLimit = MINI_CURVE_FALLBACK_POINT_LIMIT) {
  const series = normalizeEquitySeries(rows, 0);
  if (!series.length) return [];
  const latestTs = series[series.length - 1].ts;
  const cutoffTs = latestTs - hours * 60 * 60 * 1000;
  const recent = series.filter((item) => item.ts >= cutoffTs);
  if (recent.length) return recent;
  return series.slice(-fallbackLimit);
}

function fmtHourMinute(value) {
  if (!Number.isFinite(value)) return '--';
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return '--';
  return `${String(dt.getHours()).padStart(2, '0')}:${String(dt.getMinutes()).padStart(2, '0')}`;
}

function fmtMonthDayHour(value) {
  if (!Number.isFinite(value)) return '--';
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return '--';
  return `${dt.getMonth() + 1}/${dt.getDate()} ${String(dt.getHours()).padStart(2, '0')}:00`;
}

function getAutoTraderCurveSource(strategyId = 'aggregate') {
  const data = normalizeServerPaperTrader(serverPaperTrader);
  if (strategyId === 'aggregate') {
    return {
      strategyId: 'aggregate',
      strategyLabel: '多策略合计',
      subtitle: '服务端自动模拟总收益率曲线',
      startingEquity: toNum(data.summary?.starting_equity_usd) || 0,
      rows: data.recent_equity_curve || [],
      summary: data.summary || {}
    };
  }
  const book = getNormalizedStrategyBooks(data).find((item) => item.strategy_id === strategyId);
  if (!book) return null;
  return {
    strategyId: book.strategy_id,
    strategyLabel: book.strategy_label,
    subtitle: `${book.config?.signal_name || '--'} ｜ 全历史收益率曲线`,
    startingEquity: toNum(book.summary?.starting_equity_usd) || 0,
    rows: book.recent_equity_curve || [],
    summary: book.summary || {}
  };
}

async function fetchAutoTraderCurveHistory(strategyId = 'aggregate', intervalHours = 4) {
  const cacheKey = `${strategyId}:${intervalHours}`;
  if (autoCurveHistoryCache.has(cacheKey)) return autoCurveHistoryCache.get(cacheKey);
  const payload = await fetchJson(`/api/paper-trader-curve?strategy_id=${encodeURIComponent(strategyId)}&interval_hours=${encodeURIComponent(intervalHours)}`);
  const rows = Array.isArray(payload?.rows) ? payload.rows : [];
  autoCurveHistoryCache.set(cacheKey, rows);
  return rows;
}

function buildAutoCurveLaunchCard({ strategyId, strategyLabel, summary = {}, subtitle = '' }) {
  return `
    <article class="candidate-card auto-config-card auto-book-card">
      <div class="candidate-main">
        <div>
          <div class="candidate-title">${strategyLabel} <span>${subtitle || '收益图入口'}</span></div>
          <div class="candidate-tags">
            <span class="pill subtle">当前权益 ${fmtMoney(summary.equity_usd)}</span>
            <span class="pill subtle">收益 ${fmtSignedMoney((toNum(summary.equity_usd) || 0) - (toNum(summary.starting_equity_usd) || 0))}</span>
          </div>
        </div>
        <div class="candidate-score">
          <strong>${fmtRatio(summary.win_rate)}</strong>
          <small>胜率</small>
        </div>
      </div>
      <div class="candidate-meta">
        <span>最大回撤：${fmtDrawdownStat(summary)}</span>
        <span>订单量：${getSummaryOrderCount(summary)}</span>
        <span>已平：${summary.closed_count ?? 0}</span>
        <span>开仓：${summary.open_count ?? 0}</span>
      </div>
      <div class="auto-curve-actions">
        <button type="button" class="ghost" data-action="open-auto-curve" data-strategy-id="${strategyId}">查看全历史收益图</button>
        <span class="auto-curve-action-note">全历史 ｜ 每 4 小时一个点</span>
      </div>
    </article>
  `;
}

function buildAutoCurveViewer(source) {
  const series = normalizeEquitySeries(source?.rows || [], 0);
  if (!series.length || !source?.startingEquity) {
    return '<article class="candidate-card curve-viewer-card"><div class="curve-viewer-empty">当前没有足够的权益数据，无法生成收益图。</div></article>';
  }

  const width = 980;
  const height = 420;
  const padLeft = 68;
  const padRight = 18;
  const padTop = 34;
  const padBottom = 52;
  const plotWidth = width - padLeft - padRight;
  const plotHeight = height - padTop - padBottom;
  const pointsRaw = series.map((item) => ({
    ts: item.ts,
    equity: item.equity,
    returnPct: ((item.equity - source.startingEquity) / source.startingEquity) * 100
  }));
  const latest = pointsRaw[pointsRaw.length - 1];
  const maxReturn = Math.max(...pointsRaw.map((item) => item.returnPct), 0);
  const minReturn = Math.min(...pointsRaw.map((item) => item.returnPct), 0);
  const padPct = Math.max((maxReturn - minReturn) * 0.14, 0.35);
  const domainMax = maxReturn + padPct;
  const domainMin = minReturn - padPct;
  const domainSpan = Math.max(domainMax - domainMin, 0.5);
  const startTs = pointsRaw[0].ts;
  const endTs = pointsRaw[pointsRaw.length - 1].ts;
  const timeSpan = Math.max(endTs - startTs, 1);
  const toX = (ts) => padLeft + ((ts - startTs) / timeSpan) * plotWidth;
  const toY = (value) => padTop + ((domainMax - value) / domainSpan) * plotHeight;
  const svgPoints = pointsRaw.map((item) => ({
    ...item,
    x: toX(item.ts),
    y: toY(item.returnPct)
  }));
  const path = svgPoints.map((pt, idx) => `${idx === 0 ? 'M' : 'L'}${pt.x.toFixed(2)},${pt.y.toFixed(2)}`).join(' ');

  const yTicks = Array.from({ length: 6 }, (_, idx) => domainMax - (domainSpan / 5) * idx);
  const hourTicks = [];
  let tickTs = Math.floor(startTs / (4 * 3600000)) * (4 * 3600000);
  if (tickTs < startTs) tickTs += 4 * 3600000;
  while (tickTs <= endTs) {
    hourTicks.push(tickTs);
    tickTs += 4 * 3600000;
  }

  return `
    <article class="candidate-card curve-viewer-card">
      <div class="curve-viewer-meta">
        <span>当前收益率 ${fmtSignedPctCompact(latest.returnPct)}</span>
        <span>窗口最高 ${fmtSignedPctCompact(maxReturn)}</span>
        <span>窗口最低 ${fmtSignedPctCompact(minReturn)}</span>
        <span>起点 ${fmtLocalDateTime(startTs)}</span>
        <span>终点 ${fmtLocalDateTime(endTs)}</span>
        <span>${svgPoints.length} 个点 / 4h</span>
      </div>
      <svg class="curve-viewer-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${source.strategyLabel} return curve">
        <text x="${padLeft}" y="20" class="curve-viewer-axis-title">收益率 (%)</text>
        ${yTicks.map((tick) => `
          <g>
            <line x1="${padLeft}" y1="${toY(tick).toFixed(2)}" x2="${(width - padRight).toFixed(2)}" y2="${toY(tick).toFixed(2)}" class="curve-viewer-grid"></line>
            <text x="${padLeft - 10}" y="${(toY(tick) + 4).toFixed(2)}" text-anchor="end" class="curve-viewer-label">${fmtSignedPctCompact(tick)}</text>
          </g>
        `).join('')}
        ${hourTicks.map((tick) => `
          <g>
            <line x1="${toX(tick).toFixed(2)}" y1="${padTop}" x2="${toX(tick).toFixed(2)}" y2="${(height - padBottom).toFixed(2)}" class="curve-viewer-grid"></line>
            <text x="${toX(tick).toFixed(2)}" y="${(height - 18).toFixed(2)}" text-anchor="middle" class="curve-viewer-label">${fmtMonthDayHour(tick)}</text>
          </g>
        `).join('')}
        <line x1="${padLeft}" y1="${toY(0).toFixed(2)}" x2="${(width - padRight).toFixed(2)}" y2="${toY(0).toFixed(2)}" class="curve-viewer-zero"></line>
        <line x1="${padLeft}" y1="${padTop}" x2="${padLeft}" y2="${(height - padBottom).toFixed(2)}" class="curve-viewer-axis"></line>
        <line x1="${padLeft}" y1="${(height - padBottom).toFixed(2)}" x2="${(width - padRight).toFixed(2)}" y2="${(height - padBottom).toFixed(2)}" class="curve-viewer-axis"></line>
        <path d="${path}" class="curve-viewer-line"></path>
        ${svgPoints.map((pt) => `<circle cx="${pt.x.toFixed(2)}" cy="${pt.y.toFixed(2)}" r="2.1" class="curve-viewer-dot"></circle>`).join('')}
      </svg>
    </article>
  `;
}

async function openAutoCurveModal(strategyId = 'aggregate') {
  const source = getAutoTraderCurveSource(strategyId);
  if (!source) return;
  const modal = el('autoCurveModal');
  const title = el('autoCurveModalTitle');
  const subtitle = el('autoCurveModalSubtitle');
  const body = el('autoCurveModalBody');
  if (!modal || !title || !subtitle || !body) return;

  openAutoCurveStrategyId = strategyId;
  title.textContent = `${source.strategyLabel} ｜ 全历史收益率曲线`;
  subtitle.textContent = `${source.subtitle} ｜ 全历史数据按 4 小时采样一个点`;
  body.innerHTML = '<article class="candidate-card curve-viewer-card"><div class="curve-viewer-empty">加载历史收益曲线中…</div></article>';
  modal.classList.add('is-open');
  modal.setAttribute('aria-hidden', 'false');
  document.body.classList.add('modal-open');

  try {
    const rows = await fetchAutoTraderCurveHistory(strategyId, 4);
    if (openAutoCurveStrategyId !== strategyId) return;
    body.innerHTML = buildAutoCurveViewer({ ...source, rows });
  } catch (err) {
    if (openAutoCurveStrategyId !== strategyId) return;
    body.innerHTML = `<article class="candidate-card curve-viewer-card"><div class="curve-viewer-empty">加载历史收益曲线失败：${err.message}</div></article>`;
  }
}

function closeAutoCurveModal() {
  const modal = el('autoCurveModal');
  const body = el('autoCurveModalBody');
  if (body) body.innerHTML = '';
  if (modal) {
    modal.classList.remove('is-open');
    modal.setAttribute('aria-hidden', 'true');
  }
  document.body.classList.remove('modal-open');
  openAutoCurveStrategyId = null;
}

async function openLiveCurveModal() {
  const data = normalizeLiveTraderTestnet(liveTraderTestnet);
  const modal = el('autoCurveModal');
  const title = el('autoCurveModalTitle');
  const subtitle = el('autoCurveModalSubtitle');
  const body = el('autoCurveModalBody');
  if (!modal || !title || !subtitle || !body) return;

  openAutoCurveStrategyId = 'live:testnet';
  title.textContent = '测试网实盘 ｜ 全历史资金曲线';
  subtitle.textContent = '全历史数据按 4 小时采样一个点';
  body.innerHTML = '<article class="candidate-card curve-viewer-card"><div class="curve-viewer-empty">加载测试网历史资金曲线中…</div></article>';
  modal.classList.add('is-open');
  modal.setAttribute('aria-hidden', 'false');
  document.body.classList.add('modal-open');

  try {
    const rows = await fetchLiveTraderCurveHistory(4);
    if (openAutoCurveStrategyId !== 'live:testnet') return;
    body.innerHTML = buildAutoCurveViewer({
      strategyLabel: '测试网实盘',
      startingEquity: data.starting_capital_usd,
      rows,
    });
  } catch (err) {
    if (openAutoCurveStrategyId !== 'live:testnet') return;
    body.innerHTML = `<article class="candidate-card curve-viewer-card"><div class="curve-viewer-empty">加载测试网历史资金曲线失败：${err.message}</div></article>`;
  }
}

function buildEquitySparkline(rows = [], startingEquity = 0) {
  const series = normalizeEquitySeries(rows, FULL_CURVE_POINT_LIMIT);

  if (!series.length) return '';

  const width = 320;
  const height = 92;
  const padX = 8;
  const padY = 8;
  const values = series.map((item) => item.equity);
  const min = Math.min(...values, startingEquity || values[0]);
  const max = Math.max(...values, startingEquity || values[0]);
  const range = Math.max(max - min, Math.abs(max) * 0.01, 1);
  const stepX = series.length > 1 ? (width - padX * 2) / (series.length - 1) : 0;
  const toY = (value) => height - padY - ((value - min) / range) * (height - padY * 2);
  const points = series.map((item, idx) => ({
    x: padX + stepX * idx,
    y: toY(item.equity),
    equity: item.equity
  }));
  const path = points.map((pt, idx) => `${idx === 0 ? 'M' : 'L'}${pt.x.toFixed(2)},${pt.y.toFixed(2)}`).join(' ');
  const area = `${path} L${points[points.length - 1].x.toFixed(2)},${(height - padY).toFixed(2)} L${points[0].x.toFixed(2)},${(height - padY).toFixed(2)} Z`;
  const latest = points[points.length - 1];
  const toneClass = ((latest?.equity || 0) - (startingEquity || 0)) >= 0 ? 'up' : 'down';
  const gradientId = `equitySparkFill-${Math.abs(Math.round((latest?.equity || 0) * 100))}-${series.length}-${Math.abs(Math.round(series[0]?.ts || 0))}`;

  return `
    <article class="candidate-card equity-sparkline-card">
      <div class="equity-sparkline-head">
        <div>
          <strong class="${toneClass}">${fmtMoney(latest?.equity)}</strong>
          <small>最新权益 ｜ 相对本金 ${fmtSignedMoney((latest?.equity || 0) - (startingEquity || 0))}</small>
        </div>
        <div class="equity-sparkline-meta">
          <span>起点 ${fmtMoney(startingEquity)}</span>
          <span>高点 ${fmtMoney(Math.max(...values))}</span>
          <span>点数 ${series.length}</span>
        </div>
      </div>
      <svg class="equity-sparkline-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="equity sparkline">
        <defs>
          <linearGradient id="${gradientId}" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stop-color="rgba(79,140,255,0.35)"></stop>
            <stop offset="100%" stop-color="rgba(79,140,255,0.02)"></stop>
          </linearGradient>
        </defs>
        <line x1="${padX}" y1="${toY(startingEquity || values[0])}" x2="${width - padX}" y2="${toY(startingEquity || values[0])}" class="equity-sparkline-baseline"></line>
        <path d="${area}" fill="url(#${gradientId})" class="equity-sparkline-area"></path>
        <path d="${path}" fill="none" class="equity-sparkline-line ${toneClass}"></path>
        <circle cx="${latest.x.toFixed(2)}" cy="${latest.y.toFixed(2)}" r="3.5" class="equity-sparkline-dot ${toneClass}"></circle>
      </svg>
    </article>
  `;
}

function buildEquitySparklineMini(rows = [], startingEquity = 0) {
  const series = pickRecentSeriesByHours(rows, MINI_CURVE_LOOKBACK_HOURS, MINI_CURVE_FALLBACK_POINT_LIMIT);

  if (!series.length) {
    return '<div class="auto-book-sparkline-empty">暂无权益曲线数据</div>';
  }

  const width = 360;
  const height = 112;
  const padX = 8;
  const padY = 10;
  const pnls = series.map((item) => item.equity - startingEquity);
  const minPnl = Math.min(...pnls, 0);
  const maxPnl = Math.max(...pnls, 0);
  const maxAbs = Math.max(Math.abs(minPnl), Math.abs(maxPnl), Math.max(Math.abs(startingEquity) * 0.002, 1));
  const stepX = series.length > 1 ? (width - padX * 2) / (series.length - 1) : 0;
  const toY = (value) => height - padY - ((value + maxAbs) / (maxAbs * 2)) * (height - padY * 2);
  const points = series.map((item, idx) => ({
    x: padX + stepX * idx,
    y: toY(item.equity - startingEquity),
    equity: item.equity,
    pnl: item.equity - startingEquity
  }));
  const path = points.map((pt, idx) => `${idx === 0 ? 'M' : 'L'}${pt.x.toFixed(2)},${pt.y.toFixed(2)}`).join(' ');
  const baselineY = toY(0);
  const guideUpperY = toY(maxAbs * 0.5);
  const guideLowerY = toY(-maxAbs * 0.5);
  const area = `${path} L${points[points.length - 1].x.toFixed(2)},${baselineY.toFixed(2)} L${points[0].x.toFixed(2)},${baselineY.toFixed(2)} Z`;
  const latest = points[points.length - 1];
  const latestPnl = latest?.pnl || 0;
  const latestEquity = latest?.equity || startingEquity;
  const peakPnl = Math.max(...pnls, 0);
  const troughPnl = Math.min(...pnls, 0);
  const pnlRange = peakPnl - troughPnl;
  const toneClass = latestPnl >= 0 ? 'up' : 'down';
  const baseId = `equitySparkMini-${Math.abs(Math.round(latestEquity * 100))}-${series.length}-${Math.abs(Math.round(series[0]?.ts || 0))}`;
  const posGradientId = `${baseId}-pos`;
  const negGradientId = `${baseId}-neg`;
  const posClipId = `${baseId}-clip-pos`;
  const negClipId = `${baseId}-clip-neg`;
  const startTs = series[0]?.ts;
  const endTs = series[series.length - 1]?.ts;

  return `
    <div class="auto-book-sparkline">
      <div class="auto-book-sparkline-head">
        <div>
          <strong class="${toneClass}">${fmtSignedMoney(latestPnl)}</strong>
          <small>近 ${MINI_CURVE_LOOKBACK_HOURS} 小时收益曲线 ｜ 当前权益 ${fmtMoney(latestEquity)}</small>
        </div>
        <div class="auto-book-sparkline-axis-note">本金线 ${fmtMoney(startingEquity)}</div>
      </div>
      <div class="auto-book-sparkline-meta">
        <span>窗口最高收益 ${fmtSignedMoney(peakPnl)}</span>
        <span>窗口最低收益 ${fmtSignedMoney(troughPnl)}</span>
        <span>窗口振幅 ${fmtMoney(pnlRange)}</span>
        <span>${fmtHourMinute(startTs)} → ${fmtHourMinute(endTs)}</span>
        <span>${series.length} 点 / 5m</span>
      </div>
      <svg class="auto-book-sparkline-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="strategy pnl curve">
        <defs>
          <linearGradient id="${posGradientId}" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stop-color="rgba(52,211,153,0.42)"></stop>
            <stop offset="100%" stop-color="rgba(52,211,153,0.04)"></stop>
          </linearGradient>
          <linearGradient id="${negGradientId}" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stop-color="rgba(248,113,113,0.06)"></stop>
            <stop offset="100%" stop-color="rgba(248,113,113,0.38)"></stop>
          </linearGradient>
          <clipPath id="${posClipId}">
            <rect x="0" y="0" width="${width}" height="${baselineY.toFixed(2)}"></rect>
          </clipPath>
          <clipPath id="${negClipId}">
            <rect x="0" y="${baselineY.toFixed(2)}" width="${width}" height="${Math.max(height - baselineY, 0).toFixed(2)}"></rect>
          </clipPath>
        </defs>
        <line x1="${padX}" y1="${guideUpperY.toFixed(2)}" x2="${width - padX}" y2="${guideUpperY.toFixed(2)}" class="equity-sparkline-guide"></line>
        <line x1="${padX}" y1="${baselineY.toFixed(2)}" x2="${width - padX}" y2="${baselineY.toFixed(2)}" class="equity-sparkline-axis"></line>
        <line x1="${padX}" y1="${guideLowerY.toFixed(2)}" x2="${width - padX}" y2="${guideLowerY.toFixed(2)}" class="equity-sparkline-guide"></line>
        <text x="${width - padX}" y="${(guideUpperY - 4).toFixed(2)}" text-anchor="end" class="equity-sparkline-scale up">${fmtSignedMoney(maxAbs * 0.5)}</text>
        <text x="${width - padX}" y="${(baselineY - 4).toFixed(2)}" text-anchor="end" class="equity-sparkline-scale">${fmtSignedMoney(0)}</text>
        <text x="${width - padX}" y="${(guideLowerY - 4).toFixed(2)}" text-anchor="end" class="equity-sparkline-scale down">${fmtSignedMoney(maxAbs * -0.5)}</text>
        <path d="${area}" fill="url(#${posGradientId})" clip-path="url(#${posClipId})" class="equity-pnl-area-positive"></path>
        <path d="${area}" fill="url(#${negGradientId})" clip-path="url(#${negClipId})" class="equity-pnl-area-negative"></path>
        <path d="${path}" fill="none" class="equity-sparkline-line ${toneClass}"></path>
        <circle cx="${latest.x.toFixed(2)}" cy="${latest.y.toFixed(2)}" r="3" class="equity-sparkline-dot ${toneClass}"></circle>
      </svg>
      <div class="auto-book-sparkline-foot">
        <span>${fmtHourMinute(startTs)}</span>
        <span class="up">上方 = 盈利 / 下方 = 亏损</span>
        <span>${fmtHourMinute(endTs)}</span>
      </div>
    </div>
  `;
}

function emptyServerPaperTrader() {
  const risk = shortStrategyConfig.risk || {};
  const structure = shortStrategyConfig.structure || {};
  const defs = getShadowStrategyDefs();
  const strategyBooks = Object.fromEntries(
    Object.entries(defs).map(([strategyId, def]) => [strategyId, emptyServerStrategyBook(strategyId, def)])
  );
  return {
    version: null,
    config: {
      initial_equity_usd: toNum(risk.initial_equity_usd) ?? 10000,
      risk_pct: toNum(risk.risk_pct) ?? 5,
      max_concurrent: Math.round(toNum(risk.max_concurrent) ?? 3),
      max_gross_pct: toNum(risk.max_gross_pct) ?? 200,
      leverage: toNum(risk.leverage) ?? 2,
      max_hold_hours: toNum(structure.max_hold_hours) ?? 12,
      strategy_ids: Object.keys(defs),
      stop_window_min_pct: toNum(structure.stop_window_min_pct) ?? 0.8,
      stop_window_max_pct: toNum(structure.stop_window_max_pct) ?? 4.5
    },
    last_processed_snapshot_id: null,
    last_processed_at: null,
    summary: aggregateServerBookSummary(strategyBooks),
    open_orders: [],
    recent_closed_orders: [],
    recent_events: [],
    recent_equity_curve: [],
    strategy_books: strategyBooks
  };
}

function normalizeServerPaperTrader(payload) {
  const base = emptyServerPaperTrader();
  if (!payload || typeof payload !== 'object') return base;
  const defs = getShadowStrategyDefs();
  const strategyBooks = {};
  Object.entries(defs).forEach(([strategyId, def]) => {
    const bookBase = emptyServerStrategyBook(strategyId, def);
    const legacyBookPayload = !payload.strategy_books && strategyId === 'A_post_confirm_weak_turn'
      ? {
          strategy_id: strategyId,
          strategy_code: def.code,
          strategy_label: def.label,
          description: def.description,
          config: { ...(payload.config || {}), signal_name: def.signal_name, entry_filters: def.entry_filters || [] },
          summary: payload.summary || {},
          open_orders: payload.open_orders || [],
          recent_closed_orders: payload.recent_closed_orders || [],
          recent_events: payload.recent_events || [],
          recent_equity_curve: payload.recent_equity_curve || []
        }
      : null;
    const rawBook = (payload.strategy_books && payload.strategy_books[strategyId]) || legacyBookPayload || {};
    strategyBooks[strategyId] = {
      ...bookBase,
      ...rawBook,
      config: { ...bookBase.config, ...(rawBook.config || {}) },
      summary: { ...bookBase.summary, ...(rawBook.summary || {}) },
      open_orders: Array.isArray(rawBook.open_orders) ? rawBook.open_orders.map((item) => ({ ...item })) : [],
      recent_closed_orders: Array.isArray(rawBook.recent_closed_orders) ? rawBook.recent_closed_orders.map((item) => ({ ...item })) : [],
      recent_events: Array.isArray(rawBook.recent_events) ? rawBook.recent_events.map((item) => ({ ...item })) : [],
      recent_equity_curve: Array.isArray(rawBook.recent_equity_curve) ? rawBook.recent_equity_curve.map((item) => ({ ...item })) : []
    };
  });
  const fallbackSummary = aggregateServerBookSummary(strategyBooks);
  return {
    ...base,
    ...payload,
    config: { ...base.config, ...(payload.config || {}) },
    summary: { ...fallbackSummary, ...(payload.summary || {}) },
    open_orders: Array.isArray(payload.open_orders) ? payload.open_orders.map((item) => ({ ...item })) : [],
    recent_closed_orders: Array.isArray(payload.recent_closed_orders) ? payload.recent_closed_orders.map((item) => ({ ...item })) : [],
    recent_events: Array.isArray(payload.recent_events) ? payload.recent_events.map((item) => ({ ...item })) : [],
    recent_equity_curve: Array.isArray(payload.recent_equity_curve) ? payload.recent_equity_curve.map((item) => ({ ...item })) : [],
    strategy_books: strategyBooks
  };
}

function emptyLiveTraderTestnet() {
  return {
    ok: true,
    version: null,
    account_id: null,
    account_label: 'binance_c_strategy_testnet',
    strategy_id: 'C_overheat_fade',
    enabled: false,
    snapshot_id: null,
    last_run_at: null,
    starting_capital_usd: DEFAULT_LIVE_TRADER_CAPITAL_USD,
    account: {
      equity_usd: DEFAULT_LIVE_TRADER_CAPITAL_USD,
      available_balance_usd: DEFAULT_LIVE_TRADER_CAPITAL_USD,
      open_gross_usd: 0,
      gross_cap_usd: null
    },
    summary: {
      starting_capital_usd: DEFAULT_LIVE_TRADER_CAPITAL_USD,
      equity_usd: DEFAULT_LIVE_TRADER_CAPITAL_USD,
      total_pnl_usd: 0,
      realized_pnl_usd: 0,
      unrealized_pnl_usd: 0,
      roi_pct: 0,
      open_count: 0,
      closed_count: 0,
      total_order_count: 0,
      win_count: 0,
      loss_count: 0,
      win_rate: null,
      equity_peak_usd: DEFAULT_LIVE_TRADER_CAPITAL_USD,
      max_drawdown_usd: 0,
      max_drawdown_pct: null,
      equity_change_last_snapshot_usd: 0,
      equity_change_last_snapshot_pct: 0,
      curve_point_count: 0,
      recent_event_count: 0
    },
    positions: [],
    recent_events: [],
    recent_equity_curve: [],
    runtime: {
      candidate_count: null,
      candidate_preview: [],
      warnings: [],
      opened: [],
      closed: [],
      failed: []
    }
  };
}

function normalizeLiveTraderTestnet(payload) {
  const base = emptyLiveTraderTestnet();
  if (!payload || typeof payload !== 'object') return base;
  const startingCapitalUsd = toNum(payload.starting_capital_usd) ?? base.starting_capital_usd;
  const account = { ...base.account, ...(payload.account || {}) };
  const summary = {
    ...base.summary,
    ...(payload.summary || {}),
    starting_capital_usd: toNum(payload.summary?.starting_capital_usd) ?? startingCapitalUsd
  };
  const positions = Array.isArray(payload.positions) ? payload.positions.map((item) => ({ ...item })) : [];
  const recentEvents = Array.isArray(payload.recent_events) ? payload.recent_events.map((item) => ({ ...item })) : [];
  const accountEquityUsd = toNum(account.equity_usd);
  const accountAvailableBalanceUsd = toNum(account.available_balance_usd);
  const summaryEquityUsd = toNum(summary.equity_usd) ?? accountEquityUsd;
  const totalPnlUsd = toNum(summary.total_pnl_usd) ?? (summaryEquityUsd !== null ? summaryEquityUsd - startingCapitalUsd : null);
  return {
    ...base,
    ...payload,
    account_id: payload.account_id || base.account_id,
    starting_capital_usd: startingCapitalUsd,
    account: {
      equity_usd: accountEquityUsd,
      available_balance_usd: accountAvailableBalanceUsd,
      open_gross_usd: toNum(account.open_gross_usd) ?? 0,
      gross_cap_usd: toNum(account.gross_cap_usd)
    },
    summary: {
      ...summary,
      equity_usd: summaryEquityUsd,
      total_pnl_usd: totalPnlUsd,
      realized_pnl_usd: toNum(summary.realized_pnl_usd),
      unrealized_pnl_usd: toNum(summary.unrealized_pnl_usd),
      roi_pct: toNum(summary.roi_pct) ?? (totalPnlUsd !== null && startingCapitalUsd ? (totalPnlUsd / startingCapitalUsd * 100) : null),
      open_count: Math.round(toNum(summary.open_count) ?? positions.length),
      closed_count: Math.round(toNum(summary.closed_count) ?? 0),
      total_order_count: Math.round(toNum(summary.total_order_count) ?? 0),
      win_count: Math.round(toNum(summary.win_count) ?? 0),
      loss_count: Math.round(toNum(summary.loss_count) ?? 0),
      win_rate: toNum(summary.win_rate),
      equity_peak_usd: toNum(summary.equity_peak_usd),
      max_drawdown_usd: toNum(summary.max_drawdown_usd) ?? 0,
      max_drawdown_pct: toNum(summary.max_drawdown_pct),
      equity_change_last_snapshot_usd: toNum(summary.equity_change_last_snapshot_usd) ?? 0,
      equity_change_last_snapshot_pct: toNum(summary.equity_change_last_snapshot_pct),
      curve_point_count: Math.round(toNum(summary.curve_point_count) ?? 0),
      recent_event_count: Math.round(toNum(summary.recent_event_count) ?? recentEvents.length)
    },
    positions,
    recent_events: recentEvents,
    recent_equity_curve: Array.isArray(payload.recent_equity_curve) ? payload.recent_equity_curve.map((item) => ({ ...item })) : [],
    runtime: {
      ...base.runtime,
      ...(payload.runtime || {}),
      candidate_preview: Array.isArray(payload.runtime?.candidate_preview) ? payload.runtime.candidate_preview.map((item) => ({ ...item })) : [],
      warnings: Array.isArray(payload.runtime?.warnings) ? [...payload.runtime.warnings] : [],
      opened: Array.isArray(payload.runtime?.opened) ? payload.runtime.opened.map((item) => ({ ...item })) : [],
      closed: Array.isArray(payload.runtime?.closed) ? payload.runtime.closed.map((item) => ({ ...item })) : [],
      failed: Array.isArray(payload.runtime?.failed) ? payload.runtime.failed.map((item) => ({ ...item })) : []
    }
  };
}

async function fetchLiveTraderCurveHistory(intervalHours = 4) {
  const cacheKey = String(intervalHours);
  if (liveCurveHistoryCache.has(cacheKey)) return liveCurveHistoryCache.get(cacheKey);
  const payload = await fetchJson(`/api/live-trader-testnet-curve?interval_hours=${encodeURIComponent(intervalHours)}`);
  const rows = Array.isArray(payload?.rows) ? payload.rows : [];
  liveCurveHistoryCache.set(cacheKey, rows);
  return rows;
}

function normalizeLiveTraderAccounts(items) {
  const normalized = Array.isArray(items) ? items.map((item) => normalizeLiveTraderTestnet(item)) : [];
  normalized.sort((a, b) => String(a.account_label || '').localeCompare(String(b.account_label || '')));
  if (normalized.length && !normalized.some((item) => item.account_id === selectedLiveTraderAccountId)) {
    selectedLiveTraderAccountId = normalized[0].account_id || null;
  }
  return normalized;
}

function selectedLiveTraderAccount() {
  if (!liveTraderAccounts.length) return null;
  const summary = liveTraderAccounts.find((item) => item.account_id === selectedLiveTraderAccountId) || liveTraderAccounts[0] || null;
  if (!summary) return null;
  if (!selectedLiveTraderAccountDetail || selectedLiveTraderAccountDetail.account_id !== summary.account_id) return summary;
  return {
    ...summary,
    ...selectedLiveTraderAccountDetail,
    account: {
      ...(summary.account || {}),
      ...(selectedLiveTraderAccountDetail.account || {}),
    },
    summary: {
      ...(summary.summary || {}),
      ...(selectedLiveTraderAccountDetail.summary || {}),
    },
    runtime: {
      ...(summary.runtime || {}),
      ...(selectedLiveTraderAccountDetail.runtime || {}),
    },
    positions: Array.isArray(selectedLiveTraderAccountDetail.positions) ? selectedLiveTraderAccountDetail.positions : [],
    recent_events: Array.isArray(selectedLiveTraderAccountDetail.recent_events) ? selectedLiveTraderAccountDetail.recent_events : [],
  };
}

async function fetchLiveTraderAccountDetail(accountId) {
  const payload = await fetchJson(`/api/live-trader-account?id=${encodeURIComponent(accountId || '')}`);
  return normalizeLiveTraderTestnet(payload?.account);
}

async function refreshSelectedLiveTraderAccountDetail() {
  const accountId = selectedLiveTraderAccountId;
  if (!accountId) {
    selectedLiveTraderAccountDetail = null;
    selectedLiveTraderAccountDetailError = null;
    return;
  }
  try {
    selectedLiveTraderAccountDetail = await fetchLiveTraderAccountDetail(accountId);
    selectedLiveTraderAccountDetailError = null;
  } catch (err) {
    selectedLiveTraderAccountDetail = null;
    selectedLiveTraderAccountDetailError = err.message;
  }
}

async function fetchLiveTraderAccountCurveHistory(accountId, intervalHours = 4) {
  const cacheKey = `${accountId || ''}:${intervalHours}`;
  if (liveAccountCurveHistoryCache.has(cacheKey)) return liveAccountCurveHistoryCache.get(cacheKey);
  const payload = await fetchJson(`/api/live-trader-account-curve?id=${encodeURIComponent(accountId || '')}&interval_hours=${encodeURIComponent(intervalHours)}`);
  const rows = Array.isArray(payload?.rows) ? payload.rows : [];
  liveAccountCurveHistoryCache.set(cacheKey, rows);
  return rows;
}

function getNormalizedStrategyBooks(data = normalizeServerPaperTrader(serverPaperTrader)) {
  const defs = getShadowStrategyDefs();
  return Object.keys(defs)
    .map((strategyId) => data.strategy_books?.[strategyId])
    .filter(Boolean)
    .sort((a, b) => String(a.strategy_code || '').localeCompare(String(b.strategy_code || '')));
}

function renderWorkspaceTabMeta(rows = allRows) {
  const shortCandidates = getShortCandidates(rows);
  const standardCount = shortCandidates.filter((item) => item.tier === 'standard').length;
  const sniperCount = shortCandidates.filter((item) => item.tier === 'sniper').length;
  const confirmedCount = rows.filter((row) => toBool(row.overlap_candidate)).length;
  const highPotentialCount = rows.filter((row) => ['VeryHigh', 'High'].includes(row.top5_potential)).length;
  const serverOpenCount = normalizeServerPaperTrader(serverPaperTrader).summary?.open_count ?? 0;

  const shortMeta = el('workspaceShortMeta');
  if (shortMeta) {
    shortMeta.textContent = `标准 ${standardCount} ｜ 狙击 ${sniperCount} ｜ 服务端 ${serverOpenCount}`;
  }

  const overviewMeta = el('workspaceOverviewMeta');
  if (overviewMeta) {
    overviewMeta.textContent = `交叉 ${confirmedCount} ｜ 高潜 ${highPotentialCount} ｜ 当前 ${rows.length}`;
  }

  const liveMeta = el('workspaceLiveMeta');
  if (liveMeta) {
    const live = normalizeLiveTraderTestnet(liveTraderTestnet);
    liveMeta.textContent = `持仓 ${live.summary?.open_count ?? 0} ｜ 盈亏 ${fmtSignedMoney(live.summary?.total_pnl_usd)} ｜ 本金 ${fmtMoney(live.starting_capital_usd)}`;
  }

  const mainnetMeta = el('workspaceMainnetMeta');
  if (mainnetMeta) {
    const enabledCount = liveTraderAccounts.filter((item) => item.enabled).length;
    const openCount = liveTraderAccounts.reduce((sum, item) => sum + (item.summary?.open_count ?? 0), 0);
    mainnetMeta.textContent = `账户 ${liveTraderAccounts.length} ｜ 已启用 ${enabledCount} ｜ 持仓 ${openCount}`;
  }
}

function shortTierRank(tier) {
  return {
    sniper: 3,
    standard: 2,
    watch: 1
  }[tier] || 0;
}

function shortTierLabel(tier) {
  return {
    sniper: '高置信狙击',
    standard: '标准开空',
    watch: '观察'
  }[tier] || '--';
}

function hasShortField(value) {
  return value !== undefined && value !== null && value !== '';
}

function splitShortBlockers(value) {
  if (Array.isArray(value)) return value.filter(Boolean);
  if (!hasShortField(value)) return [];
  return String(value)
    .split('|')
    .map((item) => item.trim())
    .filter(Boolean);
}

function deriveShortAnchorLabel(anchorState, overlap, recentOverlap, anchorWindowHours) {
  if (anchorState === 'current_confirmed' || overlap) return '当前确认';
  if (anchorState === 'recent_confirmed' || recentOverlap) return `近${fmtHours(anchorWindowHours)}确认`;
  return '未确认';
}

function deriveWeakeningState(baseSignal, standardReady, sniperReady, overlapAnchorActive) {
  if (sniperReady) return 'SniperReady';
  if (standardReady) return 'StandardReady';
  if (baseSignal) return 'WeakeningWatch';
  if (overlapAnchorActive) return 'AnchorActive';
  return 'Inactive';
}

function buildShortSignal(row) {
  const profile = currentProfile();
  const strategy = shortStrategyConfig.strategy || {};
  const anchor = strategy.anchor || {};
  const weakening = strategy.weakening || {};
  const confirmations = strategy.confirmations || {};
  const defaultConfirm = confirmations.default || {};
  const historicalSniper = confirmations.historical_sniper || {};
  const liveSniper = confirmations.live_sniper || {};
  const overlap = toBool(row.overlap_candidate);
  const recentOverlap = toBool(row.recent_overlap_candidate_2h);
  const anchorWindowHours = toNum(row.confirm_anchor_window_hours) ?? toNum(anchor.recent_overlap_window_hours) ?? 2;
  const fallbackOverlapAnchorActive = overlap || recentOverlap;
  const trend1h = String(row.trend_1h || '');
  const weakTrend = (weakening.trend_1h_values || ['Range', 'Down', 'StrongDown']).includes(trend1h);
  const overlapScoreDelta = toNum(row.overlap_score_delta_30m);
  const overlapDeltaWeak = overlapScoreDelta !== null && overlapScoreDelta <= (toNum(weakening.overlap_score_delta_30m_max) ?? 0);
  const noBreakout = String(row.breakout_1h || '') === String(weakening.breakout_1h_required || 'NoBreakout');
  const change24h = toNum(row.change_24h_pct);
  const changeMinPct = toNum(weakening.change_24h_min_pct) ?? 3;
  const changeMaxPct = toNum(weakening.change_24h_max_pct) ?? 8;
  const changeInRange = change24h !== null && change24h >= changeMinPct && change24h <= changeMaxPct;
  const top15Hours = toNum(row.top15_persistence_hours);
  const fallbackEnoughPersistence = (top15Hours !== null && top15Hours >= (toNum(anchor.min_top15_persistence_hours) ?? 1)) || fallbackOverlapAnchorActive;
  const structureStopPct = toNum(row.structure_stop_pct);
  const structureStopPrice = toNum(row.structure_stop_price);
  const structureTargetPrice = toNum(row.structure_target_price_r1);
  const frontHighPrice = toNum(row.structure_front_high_price);
  const atr1hPct = toNum(row.structure_atr_1h_pct);
  const stopWindowMinPct = profile.stopWindowMinPct ?? toNum(row.structure_stop_window_min_pct);
  const stopWindowMaxPct = profile.stopWindowMaxPct ?? toNum(row.structure_stop_window_max_pct);
  const stopTradable = structureStopPct !== null && structureStopPct >= stopWindowMinPct && structureStopPct <= stopWindowMaxPct;

  const oiChange1hPct = toNum(row.oi_change_1h_pct);
  const oiExpanding = oiChange1hPct !== null && oiChange1hPct > (toNum(historicalSniper.oi_change_1h_pct_min_exclusive) ?? 0);
  const perpPremiumPct = toNum(row.perp_premium_pct_vs_spot);
  const premiumDeepDiscount = perpPremiumPct !== null && perpPremiumPct <= (toNum(liveSniper.perp_premium_pct_vs_spot_max) ?? -0.4);
  const fundingLatest = toNum(row.funding_rate_latest);
  const fundingMean24h = toNum(row.funding_rate_mean_24h);
  const fundingNonPositive = fundingLatest !== null && fundingLatest <= 0;
  const fundingBelowMean = fundingLatest !== null && fundingMean24h !== null && fundingLatest <= fundingMean24h;

  const basisRateLatest = toNum(row.basis_rate_latest);
  const basisRateDeltaVsMean1h = toNum(row.basis_rate_delta_vs_mean_1h);
  const topTraderAccountLsrLatest = toNum(row.top_trader_account_lsr_latest);
  const topTraderPositionLsrChange1hPct = toNum(row.top_trader_position_lsr_change_1h_pct);
  const basisWeakening = basisRateDeltaVsMean1h !== null && basisRateDeltaVsMean1h <= (toNum(defaultConfirm.basis_rate_delta_vs_mean_1h_max) ?? 0);
  const topPositionUnwinding = topTraderPositionLsrChange1hPct !== null && topTraderPositionLsrChange1hPct < (toNum(defaultConfirm.top_trader_position_lsr_change_1h_pct_max) ?? 0);
  const basisExtremeDiscount = basisRateLatest !== null && basisRateLatest <= (toNum(historicalSniper.basis_rate_latest_max) ?? -0.006);
  const topAccountCrowded = topTraderAccountLsrLatest !== null && topTraderAccountLsrLatest >= (toNum(historicalSniper.top_trader_account_lsr_latest_min) ?? 1.18);

  const fallbackBaseSignal = fallbackOverlapAnchorActive && weakTrend && overlapDeltaWeak;
  const fallbackStandardReady = fallbackBaseSignal && noBreakout && changeInRange && fallbackEnoughPersistence && stopTradable;
  const fallbackHistoricalDefaultConfirm = basisWeakening || topPositionUnwinding;
  const fallbackHistoricalSniperConfirm = oiExpanding && (basisExtremeDiscount || topAccountCrowded);
  const fallbackLiveReplacementSniper = oiExpanding && premiumDeepDiscount;
  const fallbackSniperReady = fallbackStandardReady && (fallbackHistoricalSniperConfirm || fallbackLiveReplacementSniper);
  const fallbackTier = fallbackSniperReady ? 'sniper' : (fallbackStandardReady ? 'standard' : (fallbackBaseSignal ? 'watch' : null));

  const overlapAnchorActive = hasShortField(row.confirm_anchor_active) ? toBool(row.confirm_anchor_active) : fallbackOverlapAnchorActive;
  const enoughPersistence = fallbackEnoughPersistence;
  const baseSignal = hasShortField(row.short_base_signal) ? toBool(row.short_base_signal) : fallbackBaseSignal;
  const standardReady = hasShortField(row.short_standard_ready) ? toBool(row.short_standard_ready) : fallbackStandardReady;
  const sniperReady = hasShortField(row.short_sniper_ready) ? toBool(row.short_sniper_ready) : fallbackSniperReady;
  const historicalDefaultConfirm = hasShortField(row.short_historical_default_confirm)
    ? toBool(row.short_historical_default_confirm)
    : fallbackHistoricalDefaultConfirm;
  const historicalSniperConfirm = hasShortField(row.short_historical_sniper_confirm)
    ? toBool(row.short_historical_sniper_confirm)
    : fallbackHistoricalSniperConfirm;
  const liveReplacementSniper = hasShortField(row.short_live_replacement_sniper)
    ? toBool(row.short_live_replacement_sniper)
    : fallbackLiveReplacementSniper;
  const hasCollectorTier = hasShortField(row.short_setup_tier);
  const collectorTier = hasCollectorTier
    ? (String(row.short_setup_tier).trim() === 'none' ? null : String(row.short_setup_tier).trim())
    : null;
  const tier = hasCollectorTier ? collectorTier : fallbackTier;

  const fallbackBlockers = [];
  if (!fallbackOverlapAnchorActive) fallbackBlockers.push(`当前及近 ${fmtHours(anchorWindowHours)} 内未进入交叉确认`);
  if (!weakTrend) fallbackBlockers.push('1h 趋势尚未转弱');
  if (!overlapDeltaWeak) fallbackBlockers.push('30m 交叉分仍在上行');
  if (fallbackBaseSignal && !noBreakout) fallbackBlockers.push('1h 仍有突破结构');
  if (fallbackBaseSignal && !changeInRange) fallbackBlockers.push(`24h 涨幅不在 ${fmtPct(changeMinPct)} 到 ${fmtPct(changeMaxPct)}`);
  if (fallbackBaseSignal && !enoughPersistence) fallbackBlockers.push('确认锚点和在榜时长都不足');
  if (fallbackBaseSignal && structureStopPct === null) fallbackBlockers.push('缺少结构止损上下文');
  if (fallbackBaseSignal && structureStopPct !== null && !stopTradable) fallbackBlockers.push(`结构止损 ${fmtPct(structureStopPct)} 不在 ${fmtPct(stopWindowMinPct)} 到 ${fmtPct(stopWindowMaxPct)} 窗口`);
  if (fallbackStandardReady && !fallbackHistoricalDefaultConfirm) fallbackBlockers.push('默认确认层未点亮或字段待补采');
  if (fallbackStandardReady && !fallbackLiveReplacementSniper && !fallbackHistoricalSniperConfirm) fallbackBlockers.push('高置信层未点亮');

  const fallbackQualityScore = [
    fallbackOverlapAnchorActive,
    weakTrend,
    overlapDeltaWeak,
    noBreakout,
    changeInRange,
    fallbackEnoughPersistence,
    stopTradable,
    oiExpanding,
    premiumDeepDiscount,
    fallbackHistoricalDefaultConfirm,
    fallbackHistoricalSniperConfirm
  ].filter(Boolean).length;
  const qualityScore = toNum(row.short_setup_quality_score) ?? toNum(row.short_signal_quality_score) ?? fallbackQualityScore;

  const fallbackHistoricalDefaultStatus = fallbackHistoricalDefaultConfirm
    ? '已点亮'
    : ([basisRateDeltaVsMean1h, topTraderPositionLsrChange1hPct].every((value) => value === null) ? '待补采' : '未点亮');
  const fallbackHistoricalSniperStatus = fallbackHistoricalSniperConfirm
    ? '已点亮'
    : ([basisRateLatest, topTraderAccountLsrLatest].every((value) => value === null) ? '待补采' : '未点亮');
  const fallbackLiveReplacementStatus = fallbackLiveReplacementSniper
    ? '已点亮'
    : ([oiChange1hPct, perpPremiumPct].every((value) => value === null) ? '待补采' : '未点亮');
  const historicalDefaultStatus = row.short_historical_default_status || fallbackHistoricalDefaultStatus;
  const historicalSniperStatus = row.short_historical_sniper_status || fallbackHistoricalSniperStatus;
  const liveReplacementStatus = row.short_live_replacement_status || fallbackLiveReplacementStatus;

  const anchorState = row.confirm_anchor_state || (overlap ? 'current_confirmed' : (recentOverlap ? 'recent_confirmed' : 'inactive'));
  const anchorLabel = deriveShortAnchorLabel(anchorState, overlap, recentOverlap, anchorWindowHours);
  const fallbackSignalSummary = fallbackSniperReady
    ? `${anchorLabel}后的转弱已成立，且在线高置信替代确认点亮：OI 1h 扩张 + 永续贴水加深。`
    : (fallbackStandardReady
      ? `${anchorLabel}后的转弱满足结构止损标准开空。`
      : (fallbackBaseSignal
        ? `${anchorLabel}后的转弱观察阶段，先观察，不提前开空。`
        : '当前仍未形成可执行的后确认转弱信号。'));
  const signalSummary = row.short_signal_summary || fallbackSignalSummary;
  const blockers = splitShortBlockers(row.short_blockers);
  const resolvedBlockers = blockers.length || hasShortField(row.short_blockers) ? blockers : fallbackBlockers;
  const openable = hasShortField(row.short_setup_openable)
    ? toBool(row.short_setup_openable)
    : (hasShortField(row.short_signal_openable) ? toBool(row.short_signal_openable) : tier === 'standard' || tier === 'sniper');
  const weakeningState = row.weakening_state || deriveWeakeningState(baseSignal, standardReady, sniperReady, overlapAnchorActive);

  return {
    row,
    tier,
    profile,
    baseSignal,
    standardReady,
    sniperReady,
    overlap,
    recentOverlap,
    overlapAnchorActive,
    anchorState,
    anchorWindowHours,
    anchorLabel,
    weakTrend,
    overlapDeltaWeak,
    noBreakout,
    changeInRange,
    enoughPersistence,
    blockers: resolvedBlockers,
    qualityScore,
    weakeningState,
    collectorDriven: hasCollectorTier || hasShortField(row.short_signal_summary),
    trend1h,
    overlapScoreDelta,
    change24h,
    currentPrice: getCurrentPrice(row),
    structureStopPct,
    structureStopPrice,
    structureTargetPrice,
    frontHighPrice,
    atr1hPct,
    stopTradable,
    stopWindowMinPct,
    stopWindowMaxPct,
    oiChange1hPct,
    oiExpanding,
    perpPremiumPct,
    premiumDeepDiscount,
    fundingLatest,
    fundingMean24h,
    fundingNonPositive,
    fundingBelowMean,
    basisWeakening,
    topPositionUnwinding,
    basisExtremeDiscount,
    topAccountCrowded,
    historicalDefaultConfirm,
    historicalSniperConfirm,
    liveReplacementSniper,
    historicalDefaultStatus,
    historicalSniperStatus,
    liveReplacementStatus,
    openable,
    signalSummary
  };
}

function getShortCandidates(rows) {
  return rows
    .map((row) => buildShortSignal(row))
    .filter((item) => item.tier)
    .sort((a, b) => {
      const tierDiff = shortTierRank(b.tier) - shortTierRank(a.tier);
      if (tierDiff !== 0) return tierDiff;
      const scoreDiff = b.qualityScore - a.qualityScore;
      if (scoreDiff !== 0) return scoreDiff;
      const overlapDiff = (toNum(b.row.overlap_score) || -999) - (toNum(a.row.overlap_score) || -999);
      if (overlapDiff !== 0) return overlapDiff;
      return (toNum(a.structureStopPct) || 999) - (toNum(b.structureStopPct) || 999);
    });
}

function openPositions() {
  return paperPositions.filter((position) => position.status === 'open');
}

function closedPositions() {
  return paperPositions.filter((position) => position.status === 'closed');
}

function computePortfolioPlan(profile = currentProfile(), signal = null) {
  const settings = paperSettings;
  const open = openPositions();
  const openGrossUsd = open.reduce((sum, position) => sum + (toNum(position.sizeUsd) || 0), 0);
  const grossCapUsd = settings.accountUsd * settings.maxGrossPct / 100;
  const remainingGrossUsd = Math.max(0, grossCapUsd - openGrossUsd);
  const availableSlots = Math.max(0, settings.maxConcurrent - open.length);
  const riskUsd = settings.accountUsd * settings.riskPct / 100;
  const stopPct = signal?.structureStopPct ?? profile.medianStopPct ?? null;
  const riskSizedNotionalUsd = stopPct && stopPct > 0 ? riskUsd / (stopPct / 100) : 0;
  const sizeUsd = Math.max(0, Math.min(riskSizedNotionalUsd, remainingGrossUsd));
  const marginUsd = settings.leverage > 0 ? sizeUsd / settings.leverage : sizeUsd;
  return {
    accountUsd: settings.accountUsd,
    riskUsd,
    grossCapUsd,
    openGrossUsd,
    remainingGrossUsd,
    availableSlots,
    stopPct,
    riskSizedNotionalUsd,
    sizeUsd,
    marginUsd
  };
}

function findOpenPosition(symbol) {
  return openPositions().find((position) => position.symbol === symbol) || null;
}

function canOpenShort(symbol, signal = buildShortSignal(getRowBySymbol(symbol) || {}), profile = currentProfile()) {
  const existing = findOpenPosition(symbol);
  if (existing) return { ok: false, reason: '该币已有模拟空单' };
  if (!signal.openable) return { ok: false, reason: signal.tier === 'watch' ? '当前仅观察，不开模拟空单' : '当前未满足标准开空条件' };
  if (!signal.stopTradable) return { ok: false, reason: '结构止损不在可交易窗口' };
  const plan = computePortfolioPlan(profile, signal);
  if (plan.availableSlots <= 0) return { ok: false, reason: '已达到最大并发仓位' };
  if (plan.sizeUsd <= 0) return { ok: false, reason: '已达到总敞口上限' };
  if (!plan.stopPct) return { ok: false, reason: '结构止损不可用，无法计算仓位' };
  return { ok: true, plan };
}

function autoOpenOrders() {
  return autoTraderState.orders.filter((order) => order.status === 'open');
}

function autoClosedOrders() {
  return autoTraderState.orders.filter((order) => order.status === 'closed');
}

function findAutoOpenOrder(symbol) {
  return autoOpenOrders().find((order) => order.symbol === symbol) || null;
}

function pushAutoTraderEvent(type, order, detail, snapshotId) {
  const event = {
    id: `${type}-${order.symbol}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    type,
    symbol: order.symbol,
    name: order.name,
    tier: order.signalTier,
    snapshotId,
    detail,
    at: new Date().toISOString()
  };
  autoTraderState.events = [event, ...(autoTraderState.events || [])].slice(0, 80);
}

function autoTierAllowed(tier) {
  return shortTierRank(tier) >= shortTierRank(autoTraderSettings.minTier);
}

function computeAutoTraderMetrics() {
  const open = autoOpenOrders();
  const closed = autoClosedOrders();
  const realizedPnlUsd = closed.reduce((sum, order) => sum + (toNum(order.realizedPnlUsd) || 0), 0);
  const unrealizedPnlUsd = open.reduce((sum, order) => sum + (toNum(order.unrealizedPnlUsd) || 0), 0);
  const equityUsd = autoTraderState.startingEquityUsd + realizedPnlUsd + unrealizedPnlUsd;
  const openGrossUsd = open.reduce((sum, order) => sum + (toNum(order.sizeUsd) || 0), 0);
  const grossCapUsd = equityUsd * autoTraderSettings.maxGrossPct / 100;
  const remainingGrossUsd = Math.max(0, grossCapUsd - openGrossUsd);
  return {
    openCount: open.length,
    closedCount: closed.length,
    realizedPnlUsd,
    unrealizedPnlUsd,
    equityUsd,
    openGrossUsd,
    grossCapUsd,
    remainingGrossUsd
  };
}

function computeAutoOrderPlan(signal, metrics = computeAutoTraderMetrics()) {
  const availableSlots = Math.max(0, autoTraderSettings.maxConcurrent - metrics.openCount);
  const riskUsd = metrics.equityUsd * autoTraderSettings.riskPct / 100;
  const stopPct = signal?.structureStopPct ?? null;
  const riskSizedNotionalUsd = stopPct && stopPct > 0 ? riskUsd / (stopPct / 100) : 0;
  const sizeUsd = Math.max(0, Math.min(riskSizedNotionalUsd, metrics.remainingGrossUsd));
  const marginUsd = autoTraderSettings.leverage > 0 ? sizeUsd / autoTraderSettings.leverage : sizeUsd;
  return {
    ok: availableSlots > 0 && sizeUsd > 0 && stopPct !== null,
    availableSlots,
    riskUsd,
    stopPct,
    riskSizedNotionalUsd,
    sizeUsd,
    marginUsd
  };
}

function closeAutoOrderRecord(order, exitPrice, reasonCode, reasonText, snapshotId) {
  const realizedPnlPct = calcShortPnlPct(order.entryPrice, exitPrice);
  const realizedPnlUsd = realizedPnlPct === null ? null : (toNum(order.sizeUsd) || 0) * realizedPnlPct / 100;
  return {
    ...order,
    status: 'closed',
    closeTime: new Date().toISOString(),
    closePrice: exitPrice,
    closeReason: reasonCode,
    closeReasonDetail: reasonText,
    closeSnapshotId: snapshotId,
    realizedPnlPct,
    realizedPnlUsd,
    lastMarkPrice: exitPrice,
    unrealizedPnlPct: null,
    unrealizedPnlUsd: null
  };
}

function autoOrderExitDecision(order, row, signal, markPrice, ageHours) {
  if (row && markPrice !== null && toNum(order.targetPrice) !== null && markPrice <= order.targetPrice) {
    return { code: 'tp', text: `命中 1R 目标位 ${fmtMoney(order.targetPrice)}` , exitPrice: order.targetPrice };
  }
  if (row && markPrice !== null && toNum(order.stopPrice) !== null && markPrice >= order.stopPrice) {
    return { code: 'sl', text: `命中结构止损 ${fmtMoney(order.stopPrice)}`, exitPrice: order.stopPrice };
  }
  if (!row) {
    return { code: 'left_universe', text: '币种已离开当前 TOP15 快照视野，按上一标记价结束自动单。', exitPrice: toNum(order.lastMarkPrice) || toNum(order.entryPrice) };
  }
  if (markPrice === null) return null;
  if (!signal.overlapAnchorActive) {
    return { code: 'confirm_window_lost', text: `最近 ${fmtHours(signal.anchorWindowHours)} 的确认锚点已失效，结束自动单。`, exitPrice: markPrice };
  }
  if (!signal.weakTrend) {
    return { code: 'trend_rebound', text: '1h 动能重新转强，结束自动单。', exitPrice: markPrice };
  }
  if (!signal.overlapDeltaWeak) {
    return { code: 'score_rebound', text: '30m 交叉分重新转正，结束自动单。', exitPrice: markPrice };
  }
  if (!signal.noBreakout) {
    return { code: 'breakout_resume', text: '1h 再次出现突破结构，结束自动单。', exitPrice: markPrice };
  }
  if (ageHours >= (toNum(order.maxHoldHours) || 0)) {
    return { code: 'timeout', text: `达到最长持有 ${fmtHours(order.maxHoldHours)}，按当前标记价平仓。`, exitPrice: markPrice };
  }
  return null;
}

function syncAutoTraderOrders(rows, processExits = false, snapshotId = latestManifest.latest_snapshot_id || null) {
  let changed = false;
  autoTraderState.orders = autoTraderState.orders.map((order) => {
    if (order.status !== 'open') return order;

    const row = getRowBySymbol(order.symbol);
    const signal = row ? buildShortSignal(row) : null;
    const markPrice = row ? getCurrentPrice(row) : (toNum(order.lastMarkPrice) || null);
    const entryTime = new Date(order.entryTime || order.createdAt || Date.now());
    const ageHours = Number.isNaN(entryTime.getTime()) ? 0 : (Date.now() - entryTime.getTime()) / 3600000;
    const unrealizedPnlPct = markPrice !== null ? calcShortPnlPct(order.entryPrice, markPrice) : null;
    const unrealizedPnlUsd = unrealizedPnlPct === null ? null : (toNum(order.sizeUsd) || 0) * unrealizedPnlPct / 100;

    const next = {
      ...order,
      ageHours,
      lastMarkPrice: markPrice !== null ? markPrice : order.lastMarkPrice,
      lastSeenSnapshotId: row?.snapshot_id || snapshotId || order.lastSeenSnapshotId,
      lastSeenAt: row?.captured_at_utc || row?.captured_at_cst || latestManifest.captured_at_utc || order.lastSeenAt,
      unrealizedPnlPct,
      unrealizedPnlUsd
    };

    if (!processExits) return next;

    const decision = autoOrderExitDecision(next, row, signal, markPrice, ageHours);
    if (!decision) return next;

    changed = true;
    const closed = closeAutoOrderRecord(next, decision.exitPrice, decision.code, decision.text, snapshotId || row?.snapshot_id || next.lastSeenSnapshotId);
    pushAutoTraderEvent('close', closed, decision.text, closed.closeSnapshotId);
    return closed;
  });

  return changed;
}

function openAutoTraderOrders(rows, snapshotId) {
  if (!autoTraderSettings.enabled) return false;

  let changed = false;
  const candidates = getShortCandidates(rows).filter((item) => item.openable && autoTierAllowed(item.tier));
  candidates.forEach((item) => {
    if (findAutoOpenOrder(item.row.symbol)) return;

    const metrics = computeAutoTraderMetrics();
    const plan = computeAutoOrderPlan(item, metrics);
    if (!plan.ok) return;

    const order = {
      id: `auto-${item.row.symbol}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      symbol: item.row.symbol,
      name: item.row.name,
      status: 'open',
      createdAt: new Date().toISOString(),
      entryTime: new Date().toISOString(),
      entryPrice: item.currentPrice,
      lastMarkPrice: item.currentPrice,
      profileId: currentProfile().id,
      sizeUsd: plan.sizeUsd,
      riskUsd: plan.riskUsd,
      marginUsd: plan.marginUsd,
      leverage: autoTraderSettings.leverage,
      stopPct: item.structureStopPct,
      stopPrice: item.structureStopPrice,
      targetPrice: item.structureTargetPrice,
      frontHighPrice: item.frontHighPrice,
      atr1hPct: item.atr1hPct,
      maxHoldHours: currentProfile().maxHoldHours,
      ageHours: 0,
      snapshotId,
      openSnapshotId: snapshotId,
      signalTier: item.tier,
      signalSummary: item.signalSummary,
      openReason: `${shortTierLabel(item.tier)} ｜ ${item.signalSummary} ｜ 结构止损 ${fmtPct(item.structureStopPct)} ｜ 默认确认 ${item.historicalDefaultStatus} ｜ 在线替代层 ${item.liveReplacementStatus}`,
      lastSeenSnapshotId: snapshotId,
      lastSeenAt: item.row.captured_at_utc || item.row.captured_at_cst || latestManifest.captured_at_utc,
      unrealizedPnlPct: 0,
      unrealizedPnlUsd: 0
    };

    autoTraderState.orders = [order, ...autoTraderState.orders];
    pushAutoTraderEvent('open', order, order.openReason, snapshotId);
    changed = true;
  });

  return changed;
}

function processAutoTraderSnapshot(manifest, rows) {
  const snapshotId = manifest.latest_snapshot_id || rows[0]?.snapshot_id || null;
  const isNewSnapshot = snapshotId && snapshotId !== autoTraderState.lastProcessedSnapshotId;

  let changed = syncAutoTraderOrders(rows, Boolean(isNewSnapshot && autoTraderSettings.enabled), snapshotId);

  if (isNewSnapshot && autoTraderSettings.enabled) {
    changed = openAutoTraderOrders(rows, snapshotId) || changed;
    autoTraderState.lastProcessedSnapshotId = snapshotId;
    autoTraderState.lastProcessedAt = new Date().toISOString();
    changed = true;
  }

  if (changed) saveAutoTraderState();
}

function closePositionRecord(position, exitPrice, reason) {
  const realizedPnlPct = calcShortPnlPct(position.entryPrice, exitPrice);
  const realizedPnlUsd = realizedPnlPct === null ? null : (toNum(position.sizeUsd) || 0) * realizedPnlPct / 100;
  return {
    ...position,
    status: 'closed',
    closeTime: new Date().toISOString(),
    closePrice: exitPrice,
    closeReason: reason,
    realizedPnlPct,
    realizedPnlUsd,
    lastMarkPrice: exitPrice,
    unrealizedPnlPct: null,
    unrealizedPnlUsd: null
  };
}

function syncPaperPositions() {
  let changed = false;
  paperPositions = paperPositions.map((position) => {
    if (position.status !== 'open') return position;

    const row = getRowBySymbol(position.symbol);
    const markPrice = row ? getCurrentPrice(row) : (toNum(position.lastMarkPrice) || null);
    const entryTime = new Date(position.entryTime || position.createdAt || Date.now());
    const ageHours = Number.isNaN(entryTime.getTime()) ? 0 : (Date.now() - entryTime.getTime()) / 3600000;
    const tpPrice = toNum(position.targetPrice) ?? (toNum(position.entryPrice) !== null && toNum(position.tpPct) !== null ? position.entryPrice * (1 - position.tpPct / 100) : null);
    const slPrice = toNum(position.stopPrice) ?? (toNum(position.entryPrice) !== null && toNum(position.slPct) !== null ? position.entryPrice * (1 + position.slPct / 100) : null);
    const unrealizedPnlPct = markPrice !== null ? calcShortPnlPct(position.entryPrice, markPrice) : null;
    const unrealizedPnlUsd = unrealizedPnlPct === null ? null : (toNum(position.sizeUsd) || 0) * unrealizedPnlPct / 100;

    let next = {
      ...position,
      ageHours,
      lastMarkPrice: markPrice !== null ? markPrice : position.lastMarkPrice,
      lastSeenSnapshotId: row?.snapshot_id || latestManifest.latest_snapshot_id || position.lastSeenSnapshotId,
      lastSeenAt: row?.captured_at_utc || row?.captured_at_cst || latestManifest.captured_at_utc || position.lastSeenAt,
      unrealizedPnlPct,
      unrealizedPnlUsd
    };

    if (markPrice !== null && tpPrice !== null && markPrice <= tpPrice) {
      changed = true;
      return closePositionRecord(next, tpPrice, 'tp');
    }
    if (markPrice !== null && slPrice !== null && markPrice >= slPrice) {
      changed = true;
      return closePositionRecord(next, slPrice, 'sl');
    }
    if (ageHours >= (toNum(position.maxHoldHours) || 0) && markPrice !== null) {
      changed = true;
      return closePositionRecord(next, markPrice, 'timeout');
    }

    return next;
  });

  if (changed) savePaperPositions();
}

function hydratePaperControls() {
  setControlValue('paperAccountUsd', paperSettings.accountUsd);
  setControlValue('paperRiskPct', paperSettings.riskPct);
  setControlValue('paperMaxConcurrent', paperSettings.maxConcurrent);
  setControlValue('paperMaxGrossPct', paperSettings.maxGrossPct);
  setControlValue('paperLeverage', paperSettings.leverage);
}

function hydrateAutoTraderControls() {
  setControlValue('autoInitialEquityUsd', autoTraderSettings.initialEquityUsd);
  setControlValue('autoRiskPct', autoTraderSettings.riskPct);
  setControlValue('autoMaxConcurrent', autoTraderSettings.maxConcurrent);
  setControlValue('autoMaxGrossPct', autoTraderSettings.maxGrossPct);
  setControlValue('autoLeverage', autoTraderSettings.leverage);
  setControlValue('autoMinTierSelect', autoTraderSettings.minTier);
  setText('autoTraderToggleBtn', `自动执行：${autoTraderSettings.enabled ? '开' : '关'}`);
}

function renderShortProfileOptions() {
  const select = el('shortProfileSelect');
  if (!select) return;
  const profiles = getShortExecutionProfiles();
  select.innerHTML = Object.values(profiles).map((profile) => `
    <option value="${profile.id}">${profile.label}</option>
  `).join('');
  select.value = paperSettings.profileId;
}

async function loadDashboard() {
  el('statusText').textContent = '加载中…';
  try {
    const [manifestData, latestData, snapshotsData, paperTraderData, liveTraderData, liveAccountsData, strategyConfigData] = await Promise.all([
      fetchJson('/api/manifest'),
      fetchJson('/api/latest-analysis'),
      fetchJson('/api/snapshots'),
      fetchJson('/api/paper-trader'),
      fetchJson('/api/live-trader-testnet').catch(() => ({ live_trader_testnet: null })),
      fetchJson('/api/live-trader-accounts').catch((err) => ({ accounts: [], _error: err.message })),
      fetchJson('/api/short-strategy-config').catch(() => ({ config: FALLBACK_SHORT_STRATEGY_CONFIG }))
    ]);

    shortStrategyConfig = normalizeShortStrategyConfig(strategyConfigData.config || {});
    paperSettings = sanitizePaperSettings(paperSettings);
    autoTraderSettings = sanitizeAutoTraderSettings(autoTraderSettings);
    autoTraderState = sanitizeAutoTraderState(autoTraderState);
    renderShortProfileOptions();
    hydratePaperControls();
    hydrateAutoTraderControls();
    latestManifest = manifestData.manifest || {};
    allRows = latestData.rows || [];
    serverPaperTrader = normalizeServerPaperTrader(paperTraderData.paper_trader);
    liveTraderTestnet = normalizeLiveTraderTestnet(liveTraderData.live_trader_testnet);
    liveTraderAccountsLoadError = liveAccountsData?._error || null;
    liveTraderAccounts = normalizeLiveTraderAccounts(liveAccountsData.accounts || []);
    selectedLiveTraderAccountDetail = null;
    selectedLiveTraderAccountDetailError = null;
    await refreshSelectedLiveTraderAccountDetail();
    autoCurveHistoryCache.clear();
    liveCurveHistoryCache.clear();
    liveAccountCurveHistoryCache.clear();
    syncPaperPositions();
    renderMeta(latestManifest, allRows);
    renderSnapshotOptions(snapshotsData.snapshots || [], latestManifest.latest_snapshot_id);
    renderDynamicFilters(allRows);
    renderAlgoMarkdown();
    renderShortResearchCards();
    renderWorkspaceTabMeta(allRows);
    renderLiveTraderSummary();
    renderLiveTraderPositions();
    renderLiveTraderEvents();
    renderLiveAccountsSummary();
    renderLiveAccountsList();
    renderSelectedLiveAccountDetail();
    applyFilters();
    renderAutoTraderSummary();
    renderAutoTraderConfigSummary();
    renderAutoTraderOrderList();
    renderAutoTraderCurveList();
    if (openAutoCurveStrategyId === 'live:testnet') {
      openLiveCurveModal();
    } else if ((openAutoCurveStrategyId || '').startsWith('live:account:')) {
      openLiveAccountCurveModal(openAutoCurveStrategyId.replace('live:account:', ''));
    } else if (openAutoCurveStrategyId) {
      openAutoCurveModal(openAutoCurveStrategyId);
    }
    el('statusText').textContent = `已加载 ${allRows.length} 条分析记录`;
  } catch (err) {
    console.error(err);
    el('statusText').textContent = `加载失败：${err.message}`;
  }
}

function renderAlgoMarkdown() {
  const content = el('algoMarkdownContent');
  if (content) content.textContent = ALGO_MARKDOWN;
}

function renderShortResearchCards() {
  const wrap = el('shortResearchCards');
  const profile = currentProfile();
  const anchorWindowHours = toNum(shortStrategyConfig.strategy?.anchor?.recent_overlap_window_hours) ?? 2;
  const cards = buildShortResearchCards().map((card) => {
    if (!card.selected) return card;
    return {
      ...card,
      lines: [
        `账户默认风险 ${fmtPct(profile.riskBudgetPct)} ｜ 中位结构止损 ${fmtPct(profile.medianStopPct)} ｜ 中位名义仓位 ${fmtPct(profile.medianNotionalPct)}`,
        `当前已切换到“当前 overlap 或近 ${fmtHours(anchorWindowHours)} 曾 overlap 后转弱”的执行口径，统计样本待下一轮回测刷新。`,
        `止盈 1R ｜ 最长持有 ${fmtHours(profile.maxHoldHours)} ｜ 结构止损窗 ${fmtPct(profile.stopWindowMinPct)} 到 ${fmtPct(profile.stopWindowMaxPct)}`
      ]
    };
  });

  wrap.innerHTML = cards.map((card) => `
    <article class="short-strategy-card ${card.selected ? 'is-selected' : ''}">
      <small>${card.kicker}</small>
      <h3>${card.title}</h3>
      <ul>
        ${card.lines.map((line) => `<li>${line}</li>`).join('')}
      </ul>
    </article>
  `).join('');
}

function toggleAlgoPanel() {
  algoPanelOpen = !algoPanelOpen;
  const panel = el('algoMarkdownPanel');
  const btn = el('toggleAlgoBtn');
  if (!panel || !btn) return;
  panel.classList.toggle('hidden', !algoPanelOpen);
  btn.textContent = algoPanelOpen ? '收起算法详情' : '查看算法详情';
}

function renderMeta(manifest, rows) {
  el('snapshotId').textContent = manifest.latest_snapshot_id || '--';
  const fallbackRow = rows[0] || {};
  el('capturedAt').textContent = fmtSnapshotTime(manifest.captured_at_cst || fallbackRow.captured_at_cst, manifest.captured_at_utc || fallbackRow.captured_at_utc);
  el('filteredCount').textContent = manifest.count_filtered ?? '--';
  el('top15Count').textContent = manifest.top15_count ?? rows.length;
  const leader = sortOverlap(rows)[0] || sortDarkhorse(rows)[0] || rows[0] || {};
  el('leaderSymbol').textContent = leader.symbol || '--';
  el('leaderChange').textContent = leader.overlap_rank_signal || leader.darkhorse_tag || '--';
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
  if ([...select.options].some((opt) => opt.value === current)) select.value = current;
}

function renderDynamicFilters(rows) {
  fillSelect(el('sectorFilter'), uniqueValues(rows.map((r) => r.sector_primary).filter(Boolean)));
  fillSelect(el('riskFilter'), uniqueValues(rows.flatMap((r) => splitTags(r.risk_flags))));
}

function sortDarkhorse(rows) {
  return [...rows].sort((a, b) => {
    const scoreDiff = (toNum(b.darkhorse_score) || -999) - (toNum(a.darkhorse_score) || -999);
    if (scoreDiff !== 0) return scoreDiff;
    return (toNum(b.persistence_score) || -999) - (toNum(a.persistence_score) || -999);
  });
}

function sortPersistence(rows) {
  return [...rows].sort((a, b) => {
    const scoreDiff = (toNum(b.persistence_score) || -999) - (toNum(a.persistence_score) || -999);
    if (scoreDiff !== 0) return scoreDiff;
    return (toNum(b.darkhorse_score) || -999) - (toNum(a.darkhorse_score) || -999);
  });
}

function sortOverlap(rows) {
  return [...rows].sort((a, b) => {
    const candidateDiff = Number(toBool(b.overlap_candidate)) - Number(toBool(a.overlap_candidate));
    if (candidateDiff !== 0) return candidateDiff;
    const scoreDiff = (toNum(b.overlap_score) || -999) - (toNum(a.overlap_score) || -999);
    if (scoreDiff !== 0) return scoreDiff;
    return (toNum(b.top15_persistence_hours) || -999) - (toNum(a.top15_persistence_hours) || -999);
  });
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
      const hay = [
        row.symbol, row.name, row.sector_primary, row.risk_flags, row.narrative_tags,
        row.narrative_summary, row.darkhorse_tag, row.top5_potential, row.structure_state,
        row.risk_reward_profile, row.persistence_label, row.continuation_evidence,
        row.overlap_label, row.overlap_rank_signal, row.overlap_evidence
      ].filter(Boolean).join(' ').toLowerCase();
      if (!hay.includes(keyword)) return false;
    }
    return true;
  });

  renderWorkspaceTabMeta(filtered);
  renderSummaryCards(filtered);
  renderDarkhorseList(filtered);
  renderPersistenceList(filtered);
  renderOverlapLists(filtered);
  renderShortCandidates(filtered);
  renderPaperPositionSummary();
  renderPaperPositionList();
  renderAutoTraderSummary();
  renderAutoTraderConfigSummary();
  renderAutoTraderOrderList();
  renderAutoTraderCurveList();
  renderLiveTraderSummary();
  renderLiveTraderPositions();
  renderLiveTraderEvents();
  renderEvidenceList(filtered);
  renderLeaderList(filtered);
  renderPathResearchList(filtered);
  renderTable(filtered);
  el('statusText').textContent = `当前显示 ${filtered.length} / ${allRows.length} 条`;
}

function renderSummaryCards(rows) {
  const wrap = el('summaryCards');
  const sectors = uniqueValues(rows.map((r) => r.sector_primary).filter(Boolean)).length;
  const avgChange = rows.length ? rows.reduce((sum, row) => sum + (toNum(row.change_24h_pct) || 0), 0) / rows.length : 0;
  const highPotential = rows.filter((row) => ['VeryHigh', 'High'].includes(row.top5_potential)).length;
  const overlapCount = rows.filter((row) => toBool(row.overlap_candidate)).length;
  const standardShortCount = getShortCandidates(rows).filter((item) => item.openable).length;
  const cards = [
    ['板块数', sectors],
    ['平均涨幅', fmtPct(avgChange)],
    ['高潜力黑马数', highPotential],
    ['交叉确认候选数', overlapCount],
    ['可开空候选数', standardShortCount]
  ];
  wrap.innerHTML = cards.map(([label, value]) => `
    <article class="stat-card">
      <span>${label}</span>
      <strong>${value}</strong>
    </article>
  `).join('');
}

function renderDarkhorseList(rows) {
  const wrap = el('candidateList');
  const sorted = sortDarkhorse(rows);
  wrap.innerHTML = sorted.map((row, idx) => `
    <article class="candidate-card candidate-card-darkhorse">
      <div class="candidate-main">
        <div>
          <div class="candidate-title">#${idx + 1} ${row.symbol} <span>${row.name}</span></div>
          <div class="candidate-tags">
            <span class="pill">${row.darkhorse_tag || '--'}</span>
            <span class="pill subtle">前五潜力 ${row.top5_potential || '--'}</span>
            <span class="pill subtle">持续性 ${row.sustainability || '--'}</span>
          </div>
        </div>
        <div class="candidate-score">
          <strong>${fmtNum(row.darkhorse_score)}</strong>
          <small>黑马分</small>
        </div>
      </div>
      <div class="candidate-meta">
        <span>价格：${fmtMoney(row.price_usd)}</span>
        <span>24h涨跌：${fmtPct(row.change_24h_pct)}</span>
        <span>结构：${row.structure_grade || '--'} / ${row.structure_state || '--'}</span>
        <span>风险收益：${row.risk_reward_profile || '--'}</span>
      </div>
    </article>
  `).join('');
}

function renderPersistenceList(rows) {
  const wrap = el('persistenceList');
  const sorted = sortPersistence(rows);
  wrap.innerHTML = sorted.map((row, idx) => `
    <article class="candidate-card candidate-card-persistence">
      <div class="candidate-main">
        <div>
          <div class="candidate-title">#${idx + 1} ${row.symbol} <span>${row.name}</span></div>
          <div class="candidate-tags">
            <span class="pill persistence-pill">${row.persistence_label || '--'}</span>
            <span class="pill subtle">延续风险 ${row.continuation_risk || '--'}</span>
            <span class="pill subtle">活跃度 ${row.activity_bucket || '--'}</span>
          </div>
        </div>
        <div class="candidate-score">
          <strong>${fmtNum(row.persistence_score)}</strong>
          <small>持续走强分</small>
        </div>
      </div>
      <div class="candidate-meta">
        <span>价格：${fmtMoney(row.price_usd)}</span>
        <span>1d/4h/1h：${row.trend_1d || '--'} / ${row.trend_4h || '--'} / ${row.trend_1h || '--'}</span>
        <span>回撤：${fmtPct(row.max_drawdown_7d_pct)}</span>
        <span>突破：${row.breakout_4h || '--'} / ${row.breakout_1h || '--'}</span>
      </div>
      <div class="candidate-evidence-inline">${row.continuation_evidence || '--'}</div>
    </article>
  `).join('');
}

function overlapCard(row, idx, mode) {
  const extraClass = mode === 'confirmed' ? 'candidate-card-overlap-active' : 'candidate-card-overlap-watch';
  return `
    <article class="candidate-card candidate-card-overlap ${extraClass}">
      <div class="candidate-main">
        <div>
          <div class="candidate-title">#${idx + 1} ${row.symbol} <span>${row.name}</span></div>
          <div class="candidate-tags">
            <span class="pill overlap-pill">${row.overlap_rank_signal || '--'}</span>
            <span class="pill subtle">${row.overlap_label || '--'}</span>
            <span class="pill subtle">门槛 ${toBool(row.overlap_gate_pass) ? '已通过' : '未通过'}</span>
            <span class="pill subtle ${fmtPathTone(row.path_class_v2)}">${fmtPathClass(row.path_class_v2)}</span>
          </div>
        </div>
        <div class="candidate-score">
          <strong>${fmtNum(row.overlap_score)}</strong>
          <small>交叉确认分</small>
        </div>
      </div>
      <div class="candidate-meta">
        <span>黑马分：${fmtNum(row.darkhorse_score)}</span>
        <span>持续走强分：${fmtNum(row.persistence_score)}</span>
        <span>连续在榜：${fmtHours(row.top15_persistence_hours)}</span>
        <span>24h在榜占比：${fmtRatio(row.top15_presence_ratio_24h)}</span>
        <span>到确认：${fmtHours(row.entry_to_confirmation_hours)}</span>
        <span>确认滞后Top5：${fmtHours(row.confirmation_lag_vs_top5_h)}</span>
        <span>确认前波动区间：${fmtNum(row.pre_confirmation_rank_range)}</span>
        <span>确认前波动标准差：${fmtNum(row.pre_confirmation_rank_std)}</span>
      </div>
      <div class="candidate-evidence-inline">${row.overlap_evidence || '--'}</div>
    </article>
  `;
}

function renderOverlapLists(rows) {
  const confirmedWrap = el('overlapConfirmedList');
  const watchWrap = el('overlapWatchList');
  const sorted = sortOverlap(rows);
  const confirmed = sorted.filter((row) => toBool(row.overlap_candidate));
  const watch = sorted.filter((row) => !toBool(row.overlap_candidate)).slice(0, 8);

  confirmedWrap.innerHTML = confirmed.length
    ? confirmed.map((row, idx) => overlapCard(row, idx, 'confirmed')).join('')
    : '<article class="candidate-card empty-card"><div class="candidate-title">当前暂无正式交叉候选</div><div class="candidate-evidence-inline">原因通常是：在榜时长尚未达到 1 小时，或黑马/持续走强门槛尚未同时满足。</div></article>';

  watchWrap.innerHTML = watch.length
    ? watch.map((row, idx) => overlapCard(row, idx, 'watch')).join('')
    : '<article class="candidate-card empty-card"><div class="candidate-title">当前暂无观察中样本</div></article>';
}

function shortCandidateCard(item, idx) {
  const { row, profile, currentPrice } = item;
  const plan = computePortfolioPlan(profile, item);
  const tierLabel = shortTierLabel(item.tier);
  const tierClass = {
    sniper: 'candidate-card-short-sniper',
    standard: 'candidate-card-short-standard',
    watch: 'candidate-card-short-watch'
  }[item.tier] || '';
  const tierPillClass = {
    sniper: 'short-pill-sniper',
    standard: 'short-pill-standard',
    watch: 'short-pill-watch'
  }[item.tier] || 'subtle';
  const signalText = item.signalSummary;
  const profileText = `执行模板：${profile.label} ｜ 风险 ${fmtPct(paperSettings.riskPct)} 账户权益 ｜ 1R 目标位 ${fmtMoney(item.structureTargetPrice)}`;
  const confirmText = `默认确认：${item.historicalDefaultStatus} ｜ 高置信层：${item.historicalSniperStatus} ｜ 在线替代层：${item.liveReplacementStatus}`;
  const livePerpText = `在线字段：OI 1h ${item.oiChange1hPct === null ? '--' : fmtSignedPct(item.oiChange1hPct)} ｜ perp premium ${item.perpPremiumPct === null ? '--' : fmtSignedPct(item.perpPremiumPct)} ｜ funding ${item.fundingLatest === null ? '--' : fmtSignedPctCompact(item.fundingLatest)}`;

  return `
    <article class="candidate-card candidate-card-short ${tierClass}">
      <div class="candidate-main">
        <div>
          <div class="candidate-title">#${idx + 1} ${row.symbol} <span>${row.name}</span></div>
          <div class="candidate-tags">
            <span class="pill ${tierPillClass}">${tierLabel}</span>
            <span class="pill subtle">确认锚点 ${item.anchorLabel}</span>
            <span class="pill subtle">1h ${row.trend_1h || '--'}</span>
            <span class="pill subtle">30m 交叉分 ${fmtSignedNum(row.overlap_score_delta_30m)}</span>
            <span class="pill subtle">1h 突破 ${row.breakout_1h || '--'}</span>
            <span class="pill subtle">24h ${fmtPct(row.change_24h_pct)}</span>
            <span class="pill subtle">结构止损 ${item.structureStopPct === null ? '--' : fmtPct(item.structureStopPct)}</span>
          </div>
        </div>
        <div class="candidate-score">
          <strong>${fmtNum(row.overlap_score)}</strong>
          <small>交叉确认分</small>
        </div>
      </div>
      <div class="candidate-meta">
        <span>当前价：${fmtMoney(currentPrice)}</span>
        <span>黑马 / 持续：${fmtNum(row.darkhorse_score)} / ${fmtNum(row.persistence_score)}</span>
        <span>在榜时长：${fmtHours(row.top15_persistence_hours)}</span>
        <span>路径：${fmtPathClass(row.path_class_v2)}</span>
        <span>前高锚点：${fmtMoney(item.frontHighPrice)}</span>
        <span>结构止损：${fmtMoney(item.structureStopPrice)}</span>
        <span>1R 目标位：${fmtMoney(item.structureTargetPrice)}</span>
        <span>ATR14(1h)：${item.atr1hPct === null ? '--' : fmtPct(item.atr1hPct)}</span>
        <span>建议名义仓位：${fmtMoney(plan.sizeUsd)}</span>
        <span>单笔风险预算：${fmtMoney(plan.riskUsd)}</span>
        <span>保证金占用：${fmtMoney(plan.marginUsd)}</span>
        <span>剩余总敞口：${fmtMoney(plan.remainingGrossUsd)}</span>
      </div>
      <div class="candidate-evidence-inline">${signalText}</div>
      <div class="candidate-evidence-inline">${confirmText}</div>
      <div class="candidate-evidence-inline">${livePerpText}</div>
      <div class="candidate-evidence-inline">${profileText}</div>
      ${item.blockers.length ? `<div class="candidate-evidence-inline">未满足项：${item.blockers.join(' ｜ ')}</div>` : ''}
      <div class="candidate-evidence-inline">页面当前只保留候选研究与服务端自动模拟结果，不再展示浏览器本地模拟开仓。</div>
    </article>
  `;
}

function renderShortCandidates(rows) {
  const wrap = el('shortCandidateList');
  const candidates = getShortCandidates(rows);
  const sniperCount = candidates.filter((item) => item.tier === 'sniper').length;
  const standardCount = candidates.filter((item) => item.tier === 'standard').length;
  const watchCount = candidates.filter((item) => item.tier === 'watch').length;
  const anchorWindowHours = toNum(shortStrategyConfig.strategy?.anchor?.recent_overlap_window_hours) ?? 2;
  el('shortCandidateSummary').textContent = `观察 ${watchCount} ｜ 标准开空 ${standardCount} ｜ 高置信狙击 ${sniperCount}`;
  wrap.innerHTML = candidates.length
    ? candidates.map((item, idx) => shortCandidateCard(item, idx)).join('')
    : `<article class="candidate-card empty-card"><div class="candidate-title">当前暂无空头候选</div><div class="candidate-evidence-inline">要么当前及近 ${fmtHours(anchorWindowHours)} 内都没有确认锚点，要么候选仍保持 1h 强势，尚未进入后确认转弱段。</div></article>`;
}

function buildEvidenceSummary(row) {
  const bullets = [];
  bullets.push(`数据：价格 ${fmtMoney(row.price_usd)}，24h涨跌 ${fmtPct(row.change_24h_pct)}，24h成交额 ${fmtMoney(row.volume_24h_usd)}，活跃度 ${row.activity_bucket || '--'}`);
  bullets.push(`特征：1d=${row.trend_1d || '--'}，4h=${row.trend_4h || '--'}，1h=${row.trend_1h || '--'}，结构分 ${fmtNum(row.structure_score)}`);
  bullets.push(`持续走强：分数 ${fmtNum(row.persistence_score)}，等级 ${row.persistence_label || '--'}，风险 ${row.continuation_risk || '--'}，证据 ${row.continuation_evidence || '--'}`);
  bullets.push(`时间确认：连续在榜 ${fmtHours(row.top15_persistence_hours)}，24h在榜占比 ${fmtRatio(row.top15_presence_ratio_24h)}，快照 ${row.top15_presence_snapshots_24h || '--'}/${row.top15_snapshot_count_24h || '--'}`);
  bullets.push(`路径研究：分类 ${fmtPathClass(row.path_class_v2)}，到Top5 ${fmtHours(row.hours_to_top5)}，到确认 ${fmtHours(row.entry_to_confirmation_hours)}，确认滞后Top5 ${fmtHours(row.confirmation_lag_vs_top5_h)}`);
  bullets.push(`确认锚点：当前候选 ${toBool(row.overlap_candidate) ? '是' : '否'}，近2h曾确认 ${toBool(row.recent_overlap_candidate_2h) ? '是' : '否'}，距上次确认 ${fmtHours(row.hours_since_last_overlap_candidate)}`);
  bullets.push(`稳定性：确认前波动区间 ${fmtNum(row.pre_confirmation_rank_range)}，确认前标准差 ${fmtNum(row.pre_confirmation_rank_std)}，确认前Top5占比 ${fmtRatio(row.pre_confirmation_top5_presence_ratio)}，确认进度 ${fmtRatio(row.episode_confirmation_progress_ratio)}`);
  bullets.push(`交叉确认：分数 ${fmtNum(row.overlap_score)}，等级 ${row.overlap_label || '--'}，候选 ${toBool(row.overlap_candidate) ? '是' : '否'}，证据 ${row.overlap_evidence || '--'}`);
  return bullets;
}

function renderEvidenceList(rows) {
  const wrap = el('evidenceList');
  const merged = [];
  [...sortOverlap(rows).slice(0, 3), ...sortDarkhorse(rows).slice(0, 2), ...sortPersistence(rows).slice(0, 2)].forEach((row) => {
    if (!merged.find((item) => item.symbol === row.symbol)) merged.push(row);
  });
  wrap.innerHTML = merged.map((row) => {
    const bullets = buildEvidenceSummary(row);
    return `
      <article class="evidence-card">
        <div class="evidence-head">
          <strong>${row.symbol} | ${row.name}</strong>
          <span>${row.overlap_rank_signal || row.darkhorse_tag || row.persistence_label || '--'}</span>
        </div>
        <ul>
          ${bullets.map((item) => `<li>${item}</li>`).join('')}
        </ul>
      </article>
    `;
  }).join('');
}

function renderLeaderList(rows) {
  const wrap = el('leaderList');
  const overlapLeader = sortOverlap(rows)[0];
  const darkhorseLeader = sortDarkhorse(rows)[0];
  const persistenceLeader = sortPersistence(rows)[0];
  const list = [
    overlapLeader ? { title: '交叉榜首', row: overlapLeader, metric: fmtNum(overlapLeader.overlap_score), sub: overlapLeader.overlap_rank_signal || '--' } : null,
    darkhorseLeader ? { title: '黑马榜首', row: darkhorseLeader, metric: fmtNum(darkhorseLeader.darkhorse_score), sub: darkhorseLeader.darkhorse_tag || '--' } : null,
    persistenceLeader ? { title: '持续走强榜首', row: persistenceLeader, metric: fmtNum(persistenceLeader.persistence_score), sub: persistenceLeader.persistence_label || '--' } : null,
  ].filter(Boolean);

  wrap.innerHTML = list.map((item) => `
    <article class="leader-item leader-highlight">
      <div>
        <small class="leader-kicker">${item.title}</small>
        <strong>${item.row.symbol}</strong>
        <p>${item.sub}</p>
      </div>
      <div class="leader-metrics">
        <span class="up">${item.metric}</span>
        <small>${fmtMoney(item.row.price_usd)}</small>
      </div>
    </article>
  `).join('');
}

function renderPathResearchList(rows) {
  const wrap = el('pathResearchList');
  const sorted = [...rows].sort((a, b) => {
    const aConfirmed = Number(toBool(a.overlap_candidate));
    const bConfirmed = Number(toBool(b.overlap_candidate));
    if (bConfirmed !== aConfirmed) return bConfirmed - aConfirmed;
    const aClassified = Number((a.path_class_v2 || '') !== 'Unclassified');
    const bClassified = Number((b.path_class_v2 || '') !== 'Unclassified');
    if (bClassified !== aClassified) return bClassified - aClassified;
    const aLag = toNum(a.confirmation_lag_vs_top5_h) ?? 999;
    const bLag = toNum(b.confirmation_lag_vs_top5_h) ?? 999;
    if (aLag !== bLag) return aLag - bLag;
    return (toNum(b.overlap_score) || -999) - (toNum(a.overlap_score) || -999);
  }).slice(0, 8);

  wrap.innerHTML = sorted.length ? sorted.map((row, idx) => `
    <article class="candidate-card path-card">
      <div class="candidate-main">
        <div>
          <div class="candidate-title">#${idx + 1} ${row.symbol} <span>${row.name}</span></div>
          <div class="candidate-tags">
            <span class="pill ${fmtPathTone(row.path_class_v2)}">${fmtPathClass(row.path_class_v2)}</span>
            <span class="pill subtle">${toBool(row.overlap_candidate) ? '已正式确认' : '观察中'}</span>
            <span class="pill subtle">确认前Top5占比 ${fmtRatio(row.pre_confirmation_top5_presence_ratio)}</span>
          </div>
        </div>
        <div class="candidate-score">
          <strong>${fmtHours(row.entry_to_confirmation_hours)}</strong>
          <small>到确认</small>
        </div>
      </div>
      <div class="candidate-meta">
        <span>到Top10：${fmtHours(row.hours_to_top10)}</span>
        <span>到Top5：${fmtHours(row.hours_to_top5)}</span>
        <span>到Top3：${fmtHours(row.hours_to_top3)}</span>
        <span>滞后Top5：${fmtHours(row.confirmation_lag_vs_top5_h)}</span>
        <span>波动区间：${fmtNum(row.pre_confirmation_rank_range)}</span>
        <span>标准差：${fmtNum(row.pre_confirmation_rank_std)}</span>
        <span>确认进度：${fmtRatio(row.episode_confirmation_progress_ratio)}</span>
        <span>事件快照数：${row.episode_snapshot_count || '--'}</span>
      </div>
    </article>
  `).join('') : '<article class="candidate-card empty-card"><div class="candidate-title">当前暂无路径研究样本</div></article>';
}

function renderTable(rows) {
  const tbody = el('tableBody');
  const sorted = sortOverlap(rows);
  tbody.innerHTML = sorted.map((row) => `
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
      <td class="num ${(toNum(row.change_24h_pct) || 0) >= 0 ? 'up' : 'down'}">${fmtPct(row.change_24h_pct)}</td>
      <td class="num">${fmtMoney(row.volume_24h_usd)}</td>
      <td>
        <div class="name-cell">
          <strong>${row.structure_grade || '--'} / ${row.structure_state || '--'}</strong>
          <span>${row.trend_1d || '--'} · ${row.breakout_1h || '--'}</span>
        </div>
      </td>
      <td>
        <div class="name-cell">
          <strong>${fmtNum(row.darkhorse_score)} / ${row.top5_potential || '--'}</strong>
          <span>${row.darkhorse_tag || '--'} ｜ ${row.risk_reward_profile || '--'}</span>
        </div>
      </td>
      <td>
        <div class="name-cell">
          <strong>${fmtNum(row.persistence_score)} / ${row.persistence_label || '--'}</strong>
          <span>${row.continuation_risk || '--'} ｜ ${row.continuation_evidence || '--'}</span>
        </div>
      </td>
      <td>
        <div class="name-cell">
          <strong>${fmtNum(row.overlap_score)} / ${row.overlap_label || '--'}</strong>
          <span>${toBool(row.overlap_candidate) ? '已确认' : '未确认'} ｜ ${row.overlap_evidence || '--'}</span>
          <span class="${fmtPathTone(row.path_class_v2)}">${fmtPathClass(row.path_class_v2)} ｜ 滞后Top5 ${fmtHours(row.confirmation_lag_vs_top5_h)} ｜ 波动 ${fmtNum(row.pre_confirmation_rank_std)}</span>
        </div>
      </td>
    </tr>
  `).join('');
}

function renderPaperPositionSummary() {
  const wrap = el('paperPositionSummary');
  if (!wrap) return;
  const open = openPositions();
  const closed = closedPositions();
  const plan = computePortfolioPlan(currentProfile());
  const realizedPnlUsd = closed.reduce((sum, position) => sum + (toNum(position.realizedPnlUsd) || 0), 0);
  const unrealizedPnlUsd = open.reduce((sum, position) => sum + (toNum(position.unrealizedPnlUsd) || 0), 0);
  const cards = [
    ['开仓中', open.length],
    ['已平仓', closed.length],
    ['当前总敞口', `${fmtMoney(plan.openGrossUsd)} / ${fmtMoney(plan.grossCapUsd)}`],
    ['未实现盈亏', fmtSignedMoney(unrealizedPnlUsd)],
    ['已实现盈亏', fmtSignedMoney(realizedPnlUsd)]
  ];
  wrap.innerHTML = cards.map(([label, value]) => `
    <article class="paper-stat-card">
      <span>${label}</span>
      <strong>${value}</strong>
    </article>
  `).join('');
}

function positionCard(position) {
  const profiles = getShortExecutionProfiles();
  const isOpen = position.status === 'open';
  const pnlPct = isOpen ? position.unrealizedPnlPct : position.realizedPnlPct;
  const pnlUsd = isOpen ? position.unrealizedPnlUsd : position.realizedPnlUsd;
  const statusText = isOpen ? '持仓中' : `已平仓 · ${position.closeReason || '--'}`;
  const statusClass = (toNum(pnlPct) || 0) >= 0 ? 'up' : 'down';
  const priceText = isOpen ? `标记价 ${fmtMoney(position.lastMarkPrice)}` : `平仓价 ${fmtMoney(position.closePrice)}`;
  const targetText = toNum(position.targetPrice) !== null ? `1R 目标 ${fmtMoney(position.targetPrice)}` : `TP ${fmtPct(position.tpPct)}`;
  const stopText = toNum(position.stopPrice) !== null ? `结构止损 ${fmtMoney(position.stopPrice)}` : `SL ${fmtPct(position.slPct)}`;

  return `
    <article class="candidate-card candidate-card-short ${isOpen ? 'position-open' : 'position-closed'}">
      <div class="candidate-main">
        <div>
          <div class="candidate-title">${position.symbol} <span>${position.name || ''}</span></div>
          <div class="candidate-tags">
            <span class="pill ${isOpen ? 'short-pill-standard' : 'subtle'}">${statusText}</span>
            <span class="pill subtle">${profiles[position.profileId]?.label || position.profileId}</span>
            <span class="pill subtle">${shortTierLabel(position.signalTier)}</span>
            <span class="pill subtle">开仓 ${fmtLocalDateTime(position.entryTime)}</span>
          </div>
        </div>
        <div class="candidate-score">
          <strong class="${statusClass}">${fmtSignedPct(pnlPct)}</strong>
          <small>${fmtSignedMoney(pnlUsd)}</small>
        </div>
      </div>
      <div class="candidate-meta">
        <span>入场价：${fmtMoney(position.entryPrice)}</span>
        <span>${priceText}</span>
        <span>名义仓位：${fmtMoney(position.sizeUsd)}</span>
        <span>风险预算：${fmtMoney(position.riskUsd)}</span>
        <span>杠杆：${fmtNum(position.leverage)}x</span>
        <span>持仓时长：${fmtHours(position.ageHours)}</span>
        <span>${targetText}</span>
        <span>${stopText}</span>
        <span>止损距离：${fmtPct(position.stopPct)}</span>
        <span>前高锚点：${fmtMoney(position.frontHighPrice)}</span>
        <span>最长持有：${fmtHours(position.maxHoldHours)}</span>
      </div>
      <div class="candidate-evidence-inline">入场依据：${position.signalSummary || '--'}</div>
      ${isOpen ? '<div class="candidate-evidence-inline">当前模拟规则会在到达 1R 目标、结构止损或最长持有时间后自动平仓；由于页面按快照更新，不是逐笔撮合，价格命中只做近似处理。</div>' : ''}
      <div class="action-row">
        ${isOpen ? `<button class="ghost" data-action="close-short" data-position-id="${position.id}">手动平仓</button>` : '<button class="ghost" disabled>仓位已结束</button>'}
        <span class="action-note">${isOpen ? '手动平仓会按当前标记价结算这笔纸面仓位。' : `平仓时间：${fmtLocalDateTime(position.closeTime)}`}</span>
      </div>
    </article>
  `;
}

function renderPaperPositionList() {
  const wrap = el('paperPositionList');
  if (!wrap) return;
  const open = [...openPositions()].sort((a, b) => new Date(b.entryTime) - new Date(a.entryTime));
  const closed = [...closedPositions()].sort((a, b) => new Date(b.closeTime || 0) - new Date(a.closeTime || 0));
  const list = [...open, ...closed];
  wrap.innerHTML = list.length
    ? list.map((position) => positionCard(position)).join('')
    : '<article class="candidate-card empty-card"><div class="candidate-title">当前没有模拟仓位</div><div class="candidate-evidence-inline">在左侧候选池中点击“模拟开空”，页面会按结构止损、1R 目标和最长持有 12h 建立一笔纸面空单。</div></article>';
}

function renderAutoTraderSummary() {
  const wrap = el('autoTraderSummary');
  const data = normalizeServerPaperTrader(serverPaperTrader);
  const summary = data.summary || {};
  const books = getNormalizedStrategyBooks(data);
  const cards = [
    ['状态', data.last_processed_snapshot_id ? '服务器运行中' : '等待首轮'],
    ['多策略总权益', fmtMoney(summary.equity_usd)],
    ['已实现盈亏', fmtSignedMoney(summary.realized_pnl_usd)],
    ['未实现盈亏', fmtSignedMoney(summary.unrealized_pnl_usd)],
    ['上一跳变化', fmtCurveChange(summary)],
    ['最大回撤', fmtDrawdownStat(summary)],
    ['开仓中', summary.open_count ?? 0],
    ['已平仓', summary.closed_count ?? 0],
    ['订单量', getSummaryOrderCount(summary)],
    ['胜率', fmtRatio(summary.win_rate)],
    ['当前总敞口', `${fmtMoney(summary.open_gross_usd)} / ${fmtMoney(summary.gross_cap_usd)}`],
    ['累计实现R', fmtSignedNum(summary.total_realized_r)]
  ];
  const aggregateCards = cards.map(([label, value]) => `
    <article class="paper-stat-card auto-stat-card">
      <span>${label}</span>
      <strong>${value}</strong>
    </article>
  `).join('');
  const layerCards = books.map((book) => `
    <article class="paper-stat-card auto-stat-card auto-layer-stat-card">
      <span>${book.strategy_label}</span>
      <strong>${fmtMoney(book.summary?.equity_usd)}</strong>
      <small class="auto-layer-micro">曲线 ${fmtCurveChange(book.summary)} ｜ 回撤 ${fmtPct(book.summary?.max_drawdown_pct)} ｜ 订单 ${getSummaryOrderCount(book.summary)} ｜ 胜率 ${fmtRatio(book.summary?.win_rate)}</small>
    </article>
  `).join('');
  wrap.innerHTML = `${aggregateCards}${layerCards}`;

  const status = el('autoTraderStatusText');
    if (status) {
      status.textContent = data.last_processed_at
      ? `服务器上次执行 ${fmtLocalDateTime(data.last_processed_at)} ｜ 快照 ${data.last_processed_snapshot_id || '--'} ｜ 各策略账本已独立记账`
      : `等待服务器首个快照执行 ｜ 每层初始资金 ${fmtMoney(books[0]?.summary?.starting_equity_usd ?? 10000)}`;
    }
}

function renderAutoTraderConfigSummary() {
  const wrap = el('autoTraderConfigSummary');
  if (!wrap) return;
  const data = normalizeServerPaperTrader(serverPaperTrader);
  const config = data.config || {};
  const books = getNormalizedStrategyBooks(data);
  wrap.innerHTML = `
    <article class="candidate-card auto-config-card">
      <div class="candidate-main">
        <div>
          <div class="candidate-title">服务端执行参数 <span>${data.version || 'server_paper_trader'}</span></div>
          <div class="candidate-tags">
            <span class="pill subtle">多层影子规则并行账本</span>
            <span class="pill subtle">层数 ${books.length}</span>
          </div>
        </div>
        <div class="candidate-score">
          <strong>${fmtMoney(data.summary?.starting_equity_usd)}</strong>
          <small>总研究本金</small>
        </div>
      </div>
      <div class="candidate-meta">
        <span>单笔风险：${fmtPct(config.risk_pct)}</span>
        <span>最大并发：${config.max_concurrent ?? '--'}</span>
        <span>最大总敞口：${fmtPct(config.max_gross_pct)}</span>
        <span>杠杆：${fmtNum(config.leverage)}x</span>
        <span>最长持有：${fmtHours(config.max_hold_hours)}</span>
        <span>结构止损窗：${fmtPct(config.stop_window_min_pct)} ~ ${fmtPct(config.stop_window_max_pct)}</span>
      </div>
      <div class="auto-curve-actions">
        <button type="button" class="ghost" data-action="open-auto-curve" data-strategy-id="aggregate">查看多策略全历史收益图</button>
        <span class="auto-curve-action-note">默认不渲染图，按需加载全历史 4h 采样图</span>
      </div>
      <div class="candidate-evidence-inline">当前页面只读展示服务器自动执行结果。实际开平仓决策由采集器落盘后立即调用服务端模拟引擎完成，不依赖浏览器本地状态。</div>
    </article>
    ${books.map((book) => `
      <article class="candidate-card auto-config-card auto-book-card">
        <div class="candidate-main">
          <div>
            <div class="candidate-title">${book.strategy_label} <span>${book.config?.signal_name || '--'}</span></div>
            <div class="candidate-tags">
              <span class="pill subtle">过滤 ${Array.isArray(book.config?.entry_filters) && book.config.entry_filters.length ? book.config.entry_filters.join(' + ') : 'none'}</span>
              <span class="pill subtle">初始资金 ${fmtMoney(book.summary?.starting_equity_usd)}</span>
            </div>
          </div>
          <div class="candidate-score">
            <strong>${fmtSignedMoney((toNum(book.summary?.equity_usd) || 0) - (toNum(book.summary?.starting_equity_usd) || 0))}</strong>
            <small>累计权益变化</small>
          </div>
        </div>
        <div class="candidate-meta">
          <span>当前权益：${fmtMoney(book.summary?.equity_usd)}</span>
          <span>上一跳：${fmtCurveChange(book.summary)}</span>
          <span>最大回撤：${fmtDrawdownStat(book.summary)}</span>
          <span>订单量：${getSummaryOrderCount(book.summary)}</span>
          <span>胜率：${fmtRatio(book.summary?.win_rate)}</span>
          <span>已平：${book.summary?.closed_count ?? 0}</span>
          <span>开仓：${book.summary?.open_count ?? 0}</span>
          <span>已实现：${fmtSignedMoney(book.summary?.realized_pnl_usd)}</span>
          <span>未实现：${fmtSignedMoney(book.summary?.unrealized_pnl_usd)}</span>
          <span>累计R：${fmtSignedNum(book.summary?.total_realized_r)}</span>
        </div>
        <div class="auto-curve-actions">
          <button type="button" class="ghost" data-action="open-auto-curve" data-strategy-id="${book.strategy_id}">查看全历史收益图</button>
          <span class="auto-curve-action-note">全历史 ｜ 每 4 小时一个点</span>
        </div>
        <div class="candidate-evidence-inline">${book.description || '影子规则与正式规则并行运行，用于比较哪一层更适合做主策略。'}</div>
      </article>
    `).join('')}
  `;
}

function autoOrderCard(order) {
  const isOpen = String(order.status || '') === 'open';
  const pnlPct = isOpen ? toNum(order.unrealized_pnl_pct ?? order.unrealizedPnlPct) : toNum(order.realized_pnl_pct ?? order.realizedPnlPct);
  const pnlUsd = isOpen ? toNum(order.unrealized_pnl_usd ?? order.unrealizedPnlUsd) : toNum(order.realized_pnl_usd ?? order.realizedPnlUsd);
  const statusClass = (toNum(pnlPct) || 0) >= 0 ? 'up' : 'down';
  const headerPill = isOpen ? 'short-pill-standard' : 'subtle';
  const snapshotText = isOpen
    ? `开仓快照 ${order.open_snapshot_id || order.openSnapshotId || order.snapshot_id || order.snapshotId || '--'}`
    : `开仓 ${order.open_snapshot_id || order.openSnapshotId || '--'} ｜ 平仓 ${order.close_snapshot_id || order.closeSnapshotId || '--'}`;
  const entryPrice = toNum(order.entry_price ?? order.entryPrice);
  const markPrice = toNum(order.last_mark_price ?? order.lastMarkPrice);
  const closePrice = toNum(order.close_price ?? order.closePrice);
  const sizeUsd = toNum(order.size_usd ?? order.sizeUsd);
  const riskUsd = toNum(order.risk_usd ?? order.riskUsd);
  const stopPrice = toNum(order.stop_price ?? order.stopPrice);
  const targetPrice = toNum(order.target_price ?? order.targetPrice);
  const targetRMultiple = toNum(order.target_r_multiple ?? order.targetRMultiple) ?? 1;
  const stopPct = toNum(order.stop_pct ?? order.stopPct);
  const ageHours = toNum(order.age_hours ?? order.ageHours);
  const signalTier = order.signal_tier || order.signalTier;
  const symbol = order.symbol || '--';
  const name = order.name || '';
  const openReason = order.open_reason || order.openReason || order.signal_summary || order.signalSummary || '--';
  const closeReason = order.close_reason_detail || order.closeReasonDetail || order.close_reason || order.closeReason || '--';
  const strategyCode = order.strategy_code || order.strategyCode || '--';
  const strategyLabel = order.strategy_label || order.strategyLabel || '--';
  const signalTierLabel = ['sniper', 'standard', 'watch'].includes(String(signalTier || ''))
    ? shortTierLabel(signalTier)
    : (signalTier || '--');

  return `
    <article class="candidate-card candidate-card-short ${isOpen ? 'position-open' : 'position-closed'}">
      <div class="candidate-main">
        <div>
          <div class="candidate-title">${symbol} <span>${name}</span></div>
          <div class="candidate-tags">
            <span class="pill ${headerPill}">${isOpen ? '自动持仓中' : '自动已平仓'}</span>
            <span class="pill subtle">${strategyCode} ｜ ${strategyLabel}</span>
            <span class="pill subtle">${signalTierLabel}</span>
            <span class="pill subtle">${snapshotText}</span>
          </div>
        </div>
        <div class="candidate-score">
          <strong class="${statusClass}">${fmtSignedPct(pnlPct)}</strong>
          <small>${fmtSignedMoney(pnlUsd)}</small>
        </div>
      </div>
      <div class="candidate-meta">
        <span>入场价：${fmtMoney(entryPrice)}</span>
        <span>${isOpen ? `标记价 ${fmtMoney(markPrice)}` : `平仓价 ${fmtMoney(closePrice)}`}</span>
        <span>名义仓位：${fmtMoney(sizeUsd)}</span>
        <span>风险预算：${fmtMoney(riskUsd)}</span>
        <span>结构止损：${fmtMoney(stopPrice)}</span>
        <span>${fmtNum(targetRMultiple)}R 目标：${fmtMoney(targetPrice)}</span>
        <span>止损距离：${fmtPct(stopPct)}</span>
        <span>持仓时长：${fmtHours(ageHours)}</span>
      </div>
      <div class="candidate-evidence-inline">自动开仓理由：${openReason}</div>
      ${isOpen
        ? '<div class="candidate-evidence-inline">当前处于自动盯市中；只有当新快照到来时，系统才会重新判断止盈、止损、策略失效和是否继续持有。</div>'
        : `<div class="candidate-evidence-inline">自动平仓理由：${closeReason}</div>`}
    </article>
  `;
}

function renderAutoTraderOrderList() {
  const wrap = el('autoTraderOrderList');
  const data = normalizeServerPaperTrader(serverPaperTrader);
  const books = getNormalizedStrategyBooks(data);
  const sections = books.map((book) => {
    const open = [...(book.open_orders || [])].sort((a, b) => new Date(b.entry_time || 0) - new Date(a.entry_time || 0));
    const closed = [...(book.recent_closed_orders || [])].sort((a, b) => new Date(b.close_time || 0) - new Date(a.close_time || 0));
    const list = [...open, ...closed].slice(0, 8);
    if (!list.length) return '';
    return `
      <section class="auto-book-section">
        <div class="section-mini-head">
          <h3>${book.strategy_label}</h3>
          <p>开仓 ${book.summary?.open_count ?? 0} ｜ 已平 ${book.summary?.closed_count ?? 0} ｜ 订单 ${getSummaryOrderCount(book.summary)} ｜ 胜率 ${fmtRatio(book.summary?.win_rate)} ｜ 回撤 ${fmtPct(book.summary?.max_drawdown_pct)}</p>
        </div>
        <div class="candidate-list">
          ${list.map((order) => autoOrderCard(order)).join('')}
        </div>
      </section>
    `;
  }).filter(Boolean);
  wrap.innerHTML = sections.length
    ? sections.join('')
    : '<article class="candidate-card empty-card"><div class="candidate-title">当前没有服务端自动订单</div><div class="candidate-evidence-inline">采集器每轮快照完成后，服务器会按多层影子规则分别决定是否开平仓。当前为空通常表示还没有满足条件的币种，或服务器尚未跑完首轮。</div></article>';
}

function renderAutoTraderCurveList() {
  const wrap = el('autoTraderCurveList');
  if (!wrap) return;
  const data = normalizeServerPaperTrader(serverPaperTrader);
  const books = getNormalizedStrategyBooks(data);
  wrap.innerHTML = [
    buildAutoCurveLaunchCard({
      strategyId: 'aggregate',
      strategyLabel: '多策略合计',
      summary: data.summary || {},
      subtitle: '服务端自动模拟总账户'
    }),
    ...books.map((book) => buildAutoCurveLaunchCard({
      strategyId: book.strategy_id,
      strategyLabel: book.strategy_label,
      summary: book.summary || {},
      subtitle: book.config?.signal_name || '--'
    }))
  ].join('');
}

function fmtLiveEventType(value) {
  return {
    trade_opened: '开仓成交',
    trade_closed: '平仓成交',
    trade_closed_without_market_exit: '平仓对账',
    protection_recreated: '保护单重建',
    protection_attach_failed_after_fill: '保护单失败',
    trade_open_failed: '开仓失败',
    trade_open_failed_fatal: '严重失败',
    orphan_positions_detected: '孤儿仓位',
    trade_flattened_outside_local_state: '外部平仓',
    position_mode_changed: '仓位模式切换',
    entry_aborted_after_fill: '成交后撤销'
  }[value] || value || '--';
}

function renderLiveTraderSummary() {
  const wrap = el('liveTraderSummary');
  const status = el('liveTraderStatusText');
  if (!wrap) return;
  const data = normalizeLiveTraderTestnet(liveTraderTestnet);
  const cards = [
    ['本金', fmtMoney(data.starting_capital_usd)],
    ['当前权益', fmtMoney(data.account?.equity_usd)],
    ['累计盈亏', fmtSignedMoney(data.summary?.total_pnl_usd)],
    ['收益率', fmtSignedPct(data.summary?.roi_pct)],
    ['已实现盈亏', fmtSignedMoney(data.summary?.realized_pnl_usd)],
    ['未实现盈亏', fmtSignedMoney(data.summary?.unrealized_pnl_usd)],
    ['当前持仓', data.summary?.open_count ?? 0],
    ['已平仓', data.summary?.closed_count ?? 0],
    ['订单量', getSummaryOrderCount(data.summary)],
    ['胜率', fmtRatio(data.summary?.win_rate)],
    ['最大回撤', fmtDrawdownStat(data.summary)],
    ['可用余额', fmtMoney(data.account?.available_balance_usd)],
    ['当前敞口', `${fmtMoney(data.account?.open_gross_usd)} / ${fmtMoney(data.account?.gross_cap_usd)}`]
  ];
  wrap.innerHTML = cards.map(([label, value]) => `
    <article class="paper-stat-card auto-stat-card live-stat-card">
      <span>${label}</span>
      <strong>${value}</strong>
    </article>
  `).join('');

  if (status) {
    const warnings = (data.runtime?.warnings || []).slice(0, 1);
    status.textContent = data.last_run_at
      ? `测试网最近同步 ${fmtLocalDateTime(data.last_run_at)} ｜ 快照 ${data.snapshot_id || '--'} ｜ 策略 ${data.strategy_id || '--'}${warnings.length ? ` ｜ ${warnings[0]}` : ''}`
      : `等待首轮测试网同步 ｜ 本金按 ${fmtMoney(data.starting_capital_usd)} 统计`;
  }

  const meta = el('liveTraderMetaSummary');
  if (meta) {
    const preview = Array.isArray(data.runtime?.candidate_preview) ? data.runtime.candidate_preview.slice(0, 3) : [];
    meta.innerHTML = `
      <article class="candidate-card auto-config-card live-meta-card">
        <div class="candidate-main">
          <div>
            <div class="candidate-title">测试网执行元数据 <span>${data.account_label || '--'}</span></div>
            <div class="candidate-tags">
              <span class="pill subtle">策略 ${data.strategy_id || '--'}</span>
              <span class="pill subtle">${data.enabled ? '已启用' : '未启用'}</span>
              <span class="pill subtle">事件 ${data.summary?.recent_event_count ?? 0}</span>
            </div>
          </div>
          <div class="candidate-score">
            <strong>${data.runtime?.candidate_count ?? '--'}</strong>
            <small>本轮候选数</small>
          </div>
        </div>
        <div class="candidate-meta">
          <span>最新快照：${data.snapshot_id || '--'}</span>
          <span>起始资金：${fmtMoney(data.starting_capital_usd)}</span>
          <span>已平：${data.summary?.closed_count ?? 0}</span>
          <span>订单量：${getSummaryOrderCount(data.summary)}</span>
          <span>胜率：${fmtRatio(data.summary?.win_rate)}</span>
          <span>最大回撤：${fmtDrawdownStat(data.summary)}</span>
          <span>最近开仓：${(data.runtime?.opened || []).length}</span>
          <span>最近平仓：${(data.runtime?.closed || []).length}</span>
          <span>最近失败：${(data.runtime?.failed || []).length}</span>
        </div>
        <div class="auto-curve-actions">
          <button type="button" class="ghost" data-action="open-live-curve">查看测试网全历史资金曲线</button>
          <span class="auto-curve-action-note">全历史 ｜ 每 4 小时一个点</span>
        </div>
        <div class="candidate-evidence-inline">${preview.length ? `候选预览：${preview.map((item) => `${item.symbol || '--'} / Q=${fmtNum(item.quality_score)} / 止损=${fmtPct(item.structure_stop_pct)}`).join(' ｜ ')}` : '当前没有新的候选预览或本轮尚未同步。'}</div>
      </article>
    `;
  }
}

function liveTraderPositionCard(position) {
  const protection = position.protection || {};
  const stop = protection.stop || {};
  const takeProfit = protection.take_profit || {};
  return `
    <article class="candidate-card candidate-card-short live-position-card">
      <div class="candidate-main">
        <div>
          <div class="candidate-title">${position.symbol || '--'} <span>${fmtLocalDateTime(position.opened_at)}</span></div>
          <div class="candidate-tags">
            <span class="pill short-pill-standard">测试网持仓</span>
            <span class="pill subtle">快照 ${position.snapshot_id || '--'}</span>
            <span class="pill subtle">Q=${fmtNum(position.quality_score)}</span>
          </div>
        </div>
        <div class="candidate-score">
          <strong class="${(toNum(position.unrealized_pnl_usd) || 0) >= 0 ? 'up' : 'down'}">${fmtSignedMoney(position.unrealized_pnl_usd)}</strong>
          <small>${fmtSignedPct(position.unrealized_pnl_pct)}</small>
        </div>
      </div>
      <div class="candidate-meta">
        <span>入场价：${fmtMoney(position.entry_price)}</span>
        <span>标记价：${fmtMoney(position.mark_price)}</span>
        <span>持仓数量：${fmtNum(position.position_qty)}</span>
        <span>当前名义：${fmtMoney(position.position_notional_usd)}</span>
        <span>入场名义：${fmtMoney(position.entry_notional_usd)}</span>
        <span>结构止损：${fmtMoney(position.stop_price)}</span>
        <span>止盈目标：${fmtMoney(position.target_price)}</span>
        <span>止损距离：${fmtPct(position.stop_pct)}</span>
        <span>前高锚点：${fmtMoney(position.front_high_price)}</span>
        <span>ATR14(1h)：${fmtPct(position.atr_1h_pct)}</span>
      </div>
      <div class="candidate-evidence-inline">信号摘要：${position.signal_summary || '--'}</div>
      <div class="candidate-evidence-inline">保护单：STOP ${fmtMoney(stop.trigger_price)} ｜ TP ${fmtMoney(takeProfit.trigger_price)} ｜ 活跃算法单 ${(position.algo_orders || []).length}</div>
    </article>
  `;
}

function renderLiveTraderPositions() {
  const wrap = el('liveTraderPositions');
  if (!wrap) return;
  const data = normalizeLiveTraderTestnet(liveTraderTestnet);
  const positions = [...(data.positions || [])].sort((a, b) => new Date(b.opened_at || 0) - new Date(a.opened_at || 0));
  wrap.innerHTML = positions.length
    ? positions.map((position) => liveTraderPositionCard(position)).join('')
    : '<article class="candidate-card empty-card"><div class="candidate-title">当前没有测试网持仓</div><div class="candidate-evidence-inline">当 C 策略测试网实盘触发开仓后，这里会显示真实仓位、保护单和未实现盈亏。</div></article>';
}

function liveTraderEventCard(event) {
  const isNegative = String(event.event_type || '').includes('failed');
  const toneClass = isNegative ? 'down' : 'up';
  const symbol = event.symbol || '--';
  const openEntry = event.entry || {};
  const closeResp = event.close_response || {};
  const detailParts = [];
  if (toNum(openEntry.avg_price) !== null) detailParts.push(`入场 ${fmtMoney(openEntry.avg_price)}`);
  if (toNum(openEntry.executed_qty) !== null) detailParts.push(`数量 ${fmtNum(openEntry.executed_qty)}`);
  if (toNum(openEntry.notional_usd) !== null) detailParts.push(`名义 ${fmtMoney(openEntry.notional_usd)}`);
  if (toNum(closeResp.avgPrice) !== null) detailParts.push(`平仓 ${fmtMoney(closeResp.avgPrice)}`);
  if (event.reason) detailParts.push(`原因 ${event.reason}`);
  if (event.error) detailParts.push(`错误 ${event.error}`);
  if (!detailParts.length && event.signal_summary) detailParts.push(event.signal_summary);
  return `
    <article class="candidate-card auto-config-card live-event-card">
      <div class="candidate-main">
        <div>
          <div class="candidate-title">${fmtLiveEventType(event.event_type)} <span>${symbol}</span></div>
          <div class="candidate-tags">
            <span class="pill subtle">时间 ${fmtLocalDateTime(event.ts)}</span>
            <span class="pill subtle">快照 ${event.snapshot_id || '--'}</span>
          </div>
        </div>
        <div class="candidate-score">
          <strong class="${toneClass}">${symbol}</strong>
          <small>${event.event_type || '--'}</small>
        </div>
      </div>
      <div class="candidate-evidence-inline">${detailParts.join(' ｜ ') || '--'}</div>
    </article>
  `;
}

function renderLiveTraderEvents() {
  const wrap = el('liveTraderEvents');
  if (!wrap) return;
  const data = normalizeLiveTraderTestnet(liveTraderTestnet);
  const events = [...(data.recent_events || [])].sort((a, b) => new Date(b.ts || 0) - new Date(a.ts || 0));
  wrap.innerHTML = events.length
    ? events.map((event) => liveTraderEventCard(event)).join('')
    : '<article class="candidate-card empty-card"><div class="candidate-title">当前没有测试网订单事件</div><div class="candidate-evidence-inline">开仓、平仓、保护单重建和失败事件都会落到这里，作为实盘执行审计日志。</div></article>';
}

function renderLiveAccountsSummary() {
  const wrap = el('liveAccountsSummary');
  const status = el('liveAccountsStatusText');
  if (!wrap) return;
  if (liveTraderAccountsLoadError) {
    wrap.innerHTML = '<article class="candidate-card empty-card"><div class="candidate-title">实盘账户加载失败</div><div class="candidate-evidence-inline">后端接口返回异常，请检查 `/api/live-trader-accounts`。</div></article>';
    if (status) status.textContent = `实盘账户加载失败：${liveTraderAccountsLoadError}`;
    return;
  }
  const enabledCount = liveTraderAccounts.filter((item) => item.enabled).length;
  const totalEquity = liveTraderAccounts.reduce((sum, item) => sum + (toNum(item.account?.equity_usd) || 0), 0);
  const totalPnl = liveTraderAccounts.reduce((sum, item) => sum + (toNum(item.summary?.total_pnl_usd) || 0), 0);
  const totalOpen = liveTraderAccounts.reduce((sum, item) => sum + (item.summary?.open_count ?? 0), 0);
  const totalClosed = liveTraderAccounts.reduce((sum, item) => sum + (item.summary?.closed_count ?? 0), 0);
  const cards = [
    ['账户数', liveTraderAccounts.length],
    ['已启用', enabledCount],
    ['总权益', fmtMoney(totalEquity)],
    ['累计盈亏', fmtSignedMoney(totalPnl)],
    ['当前持仓', totalOpen],
    ['已平仓', totalClosed]
  ];
  wrap.innerHTML = cards.map(([label, value]) => `
    <article class="paper-stat-card auto-stat-card live-stat-card">
      <span>${label}</span>
      <strong>${value}</strong>
    </article>
  `).join('');
  if (status) {
    status.textContent = liveTraderAccounts.length
      ? `已加载 ${liveTraderAccounts.length} 个实盘账户 ｜ 已启用 ${enabledCount} 个 ｜ 当前持仓 ${totalOpen} 个`
      : '尚未发现实盘账户配置，请在 config/live_trader_accounts/ 下放置账户 JSON。';
  }
}

function buildLiveAccountCard(account) {
  const isSelected = account.account_id === selectedLiveTraderAccountId;
  const preview = Array.isArray(account.runtime?.candidate_preview) ? account.runtime.candidate_preview.slice(0, 2) : [];
  return `
    <article class="candidate-card live-account-card ${isSelected ? 'is-selected' : ''}" data-action="select-live-account" data-account-id="${account.account_id || ''}">
      <div class="candidate-main">
        <div>
          <div class="candidate-title">${account.account_label || account.account_id || '--'} <span>${account.account_id || '--'}</span></div>
          <div class="candidate-tags">
            <span class="pill subtle">策略 ${account.strategy_id || '--'}</span>
            <span class="pill subtle">${account.enabled ? '已启用' : '已停用'}</span>
            <span class="pill subtle">持仓 ${account.summary?.open_count ?? 0}</span>
          </div>
        </div>
        <div class="candidate-score">
          <strong class="${(toNum(account.summary?.total_pnl_usd) || 0) >= 0 ? 'up' : 'down'}">${fmtSignedMoney(account.summary?.total_pnl_usd)}</strong>
          <small>${fmtSignedPct(account.summary?.roi_pct)}</small>
        </div>
      </div>
      <div class="candidate-meta">
        <span>权益 ${fmtMoney(account.account?.equity_usd)}</span>
        <span>可用 ${fmtMoney(account.account?.available_balance_usd)}</span>
        <span>已平 ${account.summary?.closed_count ?? 0}</span>
        <span>胜率 ${fmtRatio(account.summary?.win_rate)}</span>
        <span>最大回撤 ${fmtDrawdownStat(account.summary)}</span>
        <span>最近同步 ${fmtLocalDateTime(account.last_run_at)}</span>
      </div>
      <div class="candidate-evidence-inline">${preview.length ? `候选预览：${preview.map((item) => `${item.symbol || '--'} / Q=${fmtNum(item.quality_score)} / 止损=${fmtPct(item.structure_stop_pct)}`).join(' ｜ ')}` : '当前没有候选预览，或该账户本轮未同步到候选。'}</div>
      <div class="live-account-actions">
        <button type="button" class="${account.enabled ? 'toggle-off' : 'toggle-on'}" data-action="toggle-live-account" data-account-id="${account.account_id || ''}" data-enabled="${account.enabled ? '0' : '1'}">${account.enabled ? '停用账户' : '启用账户'}</button>
        <button type="button" class="ghost" data-action="open-live-account-curve" data-account-id="${account.account_id || ''}">查看全历史资金曲线</button>
        <span class="action-note">配置切换后，下轮 runner 自动生效</span>
      </div>
    </article>
  `;
}

function renderLiveAccountsList() {
  const wrap = el('liveAccountsList');
  if (!wrap) return;
  if (liveTraderAccountsLoadError) {
    wrap.innerHTML = `<article class="candidate-card empty-card"><div class="candidate-title">实盘账户接口异常</div><div class="candidate-evidence-inline">${liveTraderAccountsLoadError}</div></article>`;
    return;
  }
  wrap.innerHTML = liveTraderAccounts.length
    ? liveTraderAccounts.map((account) => buildLiveAccountCard(account)).join('')
    : '<article class="candidate-card empty-card"><div class="candidate-title">当前没有实盘账户配置</div><div class="candidate-evidence-inline">把账户配置文件放到 `config/live_trader_accounts/` 下后，这里会自动列出每个账户的独立记录和开关。</div></article>';
}

function renderSelectedLiveAccountDetail() {
  const summaryWrap = el('liveAccountDetailSummary');
  const metaWrap = el('liveAccountDetailMetaSummary');
  const positionsWrap = el('liveAccountPositions');
  const eventsWrap = el('liveAccountEvents');
  const account = selectedLiveTraderAccount();
  if (!summaryWrap || !metaWrap || !positionsWrap || !eventsWrap) return;
  if (!account) {
    const emptyHtml = '<article class="candidate-card empty-card"><div class="candidate-title">尚未选择实盘账户</div><div class="candidate-evidence-inline">当前没有可展示的实盘账户详情。</div></article>';
    summaryWrap.innerHTML = emptyHtml;
    metaWrap.innerHTML = emptyHtml;
    positionsWrap.innerHTML = emptyHtml;
    eventsWrap.innerHTML = emptyHtml;
    return;
  }
  if (!selectedLiveTraderAccountDetail && selectedLiveTraderAccountDetailError) {
    const errorHtml = `<article class="candidate-card empty-card"><div class="candidate-title">账户详情加载失败</div><div class="candidate-evidence-inline">${selectedLiveTraderAccountDetailError}</div></article>`;
    summaryWrap.innerHTML = errorHtml;
    metaWrap.innerHTML = errorHtml;
    positionsWrap.innerHTML = errorHtml;
    eventsWrap.innerHTML = errorHtml;
    return;
  }

  const cards = [
    ['本金', fmtMoney(account.starting_capital_usd)],
    ['当前权益', fmtMoney(account.account?.equity_usd)],
    ['累计盈亏', fmtSignedMoney(account.summary?.total_pnl_usd)],
    ['收益率', fmtSignedPct(account.summary?.roi_pct)],
    ['已实现盈亏', fmtSignedMoney(account.summary?.realized_pnl_usd)],
    ['未实现盈亏', fmtSignedMoney(account.summary?.unrealized_pnl_usd)],
    ['当前持仓', account.summary?.open_count ?? 0],
    ['已平仓', account.summary?.closed_count ?? 0],
    ['订单量', getSummaryOrderCount(account.summary)],
    ['胜率', fmtRatio(account.summary?.win_rate)],
    ['最大回撤', fmtDrawdownStat(account.summary)],
    ['当前敞口', `${fmtMoney(account.account?.open_gross_usd)} / ${fmtMoney(account.account?.gross_cap_usd)}`]
  ];
  summaryWrap.innerHTML = cards.map(([label, value]) => `
    <article class="paper-stat-card auto-stat-card live-stat-card">
      <span>${label}</span>
      <strong>${value}</strong>
    </article>
  `).join('');

  const preview = Array.isArray(account.runtime?.candidate_preview) ? account.runtime.candidate_preview.slice(0, 3) : [];
  metaWrap.innerHTML = `
    <article class="candidate-card auto-config-card live-meta-card">
      <div class="candidate-main">
        <div>
          <div class="candidate-title">${account.account_label || '--'} <span>${account.account_id || '--'}</span></div>
          <div class="candidate-tags">
            <span class="pill subtle">策略 ${account.strategy_id || '--'}</span>
            <span class="pill subtle">${account.enabled ? '已启用' : '已停用'}</span>
            <span class="pill subtle">事件 ${account.summary?.recent_event_count ?? 0}</span>
          </div>
        </div>
        <div class="candidate-score">
          <strong>${account.runtime?.candidate_count ?? '--'}</strong>
          <small>本轮候选数</small>
        </div>
      </div>
      <div class="candidate-meta">
        <span>快照 ${account.snapshot_id || '--'}</span>
        <span>最近同步 ${fmtLocalDateTime(account.last_run_at)}</span>
        <span>已平 ${account.summary?.closed_count ?? 0}</span>
        <span>订单量 ${getSummaryOrderCount(account.summary)}</span>
        <span>胜率 ${fmtRatio(account.summary?.win_rate)}</span>
        <span>最大回撤 ${fmtDrawdownStat(account.summary)}</span>
      </div>
      <div class="auto-curve-actions">
        <button type="button" class="ghost" data-action="open-live-account-curve" data-account-id="${account.account_id || ''}">查看账户全历史资金曲线</button>
        <span class="auto-curve-action-note">全历史 ｜ 每 4 小时一个点</span>
      </div>
      <div class="candidate-evidence-inline">${preview.length ? `候选预览：${preview.map((item) => `${item.symbol || '--'} / Q=${fmtNum(item.quality_score)} / 止损=${fmtPct(item.structure_stop_pct)}`).join(' ｜ ')}` : '当前没有候选预览。'}</div>
    </article>
  `;

  const positions = [...(account.positions || [])].sort((a, b) => new Date(b.opened_at || 0) - new Date(a.opened_at || 0));
  positionsWrap.innerHTML = positions.length
    ? positions.map((position) => liveTraderPositionCard(position)).join('')
    : '<article class="candidate-card empty-card"><div class="candidate-title">当前没有实盘持仓</div><div class="candidate-evidence-inline">如果账户已经启用但这里为空，说明当前没有满足条件的已成交仓位，或者交易所侧仓位已全部平掉。</div></article>';

  const events = [...(account.recent_events || [])].sort((a, b) => new Date(b.ts || 0) - new Date(a.ts || 0));
  eventsWrap.innerHTML = events.length
    ? events.map((event) => liveTraderEventCard(event)).join('')
    : '<article class="candidate-card empty-card"><div class="candidate-title">当前没有实盘订单事件</div><div class="candidate-evidence-inline">开仓、平仓、保护单重建和失败事件都会落到这里，作为该账户的独立执行审计日志。</div></article>';
}

async function toggleLiveAccountEnabled(accountId, enabled) {
  try {
    await fetchJson('/api/live-trader-account-toggle', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        account_id: accountId,
        enabled: !!enabled
      })
    });
    await loadDashboard();
  } catch (err) {
    window.alert(`切换账户开关失败：${err.message}`);
  }
}

async function selectLiveTraderAccount(accountId) {
  selectedLiveTraderAccountId = accountId || null;
  selectedLiveTraderAccountDetail = null;
  selectedLiveTraderAccountDetailError = null;
  renderLiveAccountsList();
  renderSelectedLiveAccountDetail();
  await refreshSelectedLiveTraderAccountDetail();
  renderLiveAccountsList();
  renderSelectedLiveAccountDetail();
}

async function openLiveAccountCurveModal(accountId) {
  const account = liveTraderAccounts.find((item) => item.account_id === accountId);
  const modal = el('autoCurveModal');
  const title = el('autoCurveModalTitle');
  const subtitle = el('autoCurveModalSubtitle');
  const body = el('autoCurveModalBody');
  if (!account || !modal || !title || !subtitle || !body) return;

  openAutoCurveStrategyId = `live:account:${accountId}`;
  title.textContent = `${account.account_label || accountId} ｜ 全历史资金曲线`;
  subtitle.textContent = '全历史数据按 4 小时采样一个点';
  body.innerHTML = '<article class="candidate-card curve-viewer-card"><div class="curve-viewer-empty">加载账户历史资金曲线中…</div></article>';
  modal.classList.add('is-open');
  modal.setAttribute('aria-hidden', 'false');
  document.body.classList.add('modal-open');

  try {
    const rows = await fetchLiveTraderAccountCurveHistory(accountId, 4);
    if (openAutoCurveStrategyId !== `live:account:${accountId}`) return;
    body.innerHTML = buildAutoCurveViewer({
      strategyLabel: account.account_label || accountId,
      startingEquity: account.starting_capital_usd,
      rows,
    });
  } catch (err) {
    if (openAutoCurveStrategyId !== `live:account:${accountId}`) return;
    body.innerHTML = `<article class="candidate-card curve-viewer-card"><div class="curve-viewer-empty">加载账户历史资金曲线失败：${err.message}</div></article>`;
  }
}

function openShortPosition(symbol) {
  const row = getRowBySymbol(symbol);
  if (!row) return;
  const signal = buildShortSignal(row);
  const profile = currentProfile();
  const permission = canOpenShort(symbol, signal, profile);
  if (!permission.ok) {
    window.alert(permission.reason);
    return;
  }
  const price = getCurrentPrice(row);
  if (price === null) {
    window.alert('当前没有可用价格，无法建立模拟仓位');
    return;
  }

  const plan = permission.plan;
  const position = {
    id: `${symbol}-${Date.now()}`,
    symbol: row.symbol,
    name: row.name,
    status: 'open',
    createdAt: new Date().toISOString(),
    entryTime: new Date().toISOString(),
    entryPrice: price,
    lastMarkPrice: price,
    profileId: profile.id,
    sizeUsd: plan.sizeUsd,
    riskUsd: plan.riskUsd,
    marginUsd: plan.marginUsd,
    leverage: paperSettings.leverage,
    tpPct: signal.structureStopPct,
    slPct: signal.structureStopPct,
    stopPct: signal.structureStopPct,
    stopPrice: signal.structureStopPrice,
    targetPrice: signal.structureTargetPrice,
    frontHighPrice: signal.frontHighPrice,
    atr1hPct: signal.atr1hPct,
    maxHoldHours: profile.maxHoldHours,
    ageHours: 0,
    snapshotId: row.snapshot_id || latestManifest.latest_snapshot_id,
    signalTier: signal.tier,
    signalSummary: signal.signalSummary
  };
  paperPositions = [position, ...paperPositions];
  savePaperPositions();
  applyFilters();
}

function closeShortPosition(positionId) {
  const position = paperPositions.find((item) => item.id === positionId);
  if (!position || position.status !== 'open') return;
  const row = getRowBySymbol(position.symbol);
  const exitPrice = row ? getCurrentPrice(row) : (toNum(position.lastMarkPrice) || position.entryPrice);
  paperPositions = paperPositions.map((item) => item.id === positionId ? closePositionRecord(item, exitPrice, 'manual') : item);
  savePaperPositions();
  applyFilters();
}

function clearClosedPositions() {
  paperPositions = paperPositions.filter((position) => position.status !== 'closed');
  savePaperPositions();
  applyFilters();
}

function updatePaperSettingsFromInputs() {
  paperSettings = sanitizePaperSettings({
    ...paperSettings,
    accountUsd: readControlValue('paperAccountUsd', paperSettings.accountUsd),
    riskPct: readControlValue('paperRiskPct', paperSettings.riskPct),
    maxConcurrent: readControlValue('paperMaxConcurrent', paperSettings.maxConcurrent),
    maxGrossPct: readControlValue('paperMaxGrossPct', paperSettings.maxGrossPct),
    leverage: readControlValue('paperLeverage', paperSettings.leverage),
    profileId: readControlValue('shortProfileSelect', paperSettings.profileId)
  });
  savePaperSettings();
  hydratePaperControls();
  renderShortResearchCards();
  applyFilters();
}

function updateAutoTraderSettingsFromInputs() {
  autoTraderSettings = sanitizeAutoTraderSettings({
    ...autoTraderSettings,
    initialEquityUsd: readControlValue('autoInitialEquityUsd', autoTraderSettings.initialEquityUsd),
    riskPct: readControlValue('autoRiskPct', autoTraderSettings.riskPct),
    maxConcurrent: readControlValue('autoMaxConcurrent', autoTraderSettings.maxConcurrent),
    maxGrossPct: readControlValue('autoMaxGrossPct', autoTraderSettings.maxGrossPct),
    leverage: readControlValue('autoLeverage', autoTraderSettings.leverage),
    minTier: readControlValue('autoMinTierSelect', autoTraderSettings.minTier)
  });
  if (!autoTraderState.orders.length && !autoTraderState.lastProcessedSnapshotId) {
    autoTraderState.startingEquityUsd = autoTraderSettings.initialEquityUsd;
    saveAutoTraderState();
  }
  saveAutoTraderSettings();
  hydrateAutoTraderControls();
  renderAutoTraderSummary();
  renderAutoTraderOrderList();
}

function toggleAutoTrader() {
  autoTraderSettings = sanitizeAutoTraderSettings({
    ...autoTraderSettings,
    enabled: !autoTraderSettings.enabled
  });
  saveAutoTraderSettings();
  hydrateAutoTraderControls();
  if (autoTraderSettings.enabled && allRows.length) processAutoTraderSnapshot(latestManifest, allRows);
  renderAutoTraderSummary();
  renderAutoTraderOrderList();
}

function resetAutoTrader() {
  autoTraderState = {
    ...freshAutoTraderState(),
    startingEquityUsd: autoTraderSettings.initialEquityUsd
  };
  saveAutoTraderState();
  if (autoTraderSettings.enabled && allRows.length) processAutoTraderSnapshot(latestManifest, allRows);
  renderAutoTraderSummary();
  renderAutoTraderOrderList();
}

function toggleAutoRefresh() {
  autoRefresh = !autoRefresh;
  setText('autoRefreshBtn', `自动刷新：${autoRefresh ? '开' : '关'}`);
  scheduleRefresh();
}

function scheduleRefresh() {
  if (refreshTimer) clearInterval(refreshTimer);
  if (autoRefresh) refreshTimer = setInterval(loadDashboard, REFRESH_MS);
}

function bindEvents() {
  const refreshBtn = el('refreshBtn');
  if (refreshBtn) refreshBtn.addEventListener('click', loadDashboard);
  const autoRefreshBtn = el('autoRefreshBtn');
  if (autoRefreshBtn) autoRefreshBtn.addEventListener('click', toggleAutoRefresh);
  const toggleAlgoBtn = el('toggleAlgoBtn');
  if (toggleAlgoBtn) toggleAlgoBtn.addEventListener('click', toggleAlgoPanel);
  const clearClosedBtn = el('clearClosedBtn');
  if (clearClosedBtn) clearClosedBtn.addEventListener('click', clearClosedPositions);
  ['workspaceShortTab', 'workspaceOverviewTab', 'workspaceLiveTab', 'workspaceMainnetTab'].forEach((id) => {
    const node = el(id);
    if (node) node.addEventListener('click', () => setWorkspaceTab(node.dataset.tabTarget));
  });
  ['sectorFilter', 'riskFilter', 'activityFilter'].forEach((id) => {
    const node = el(id);
    if (node) node.addEventListener('change', applyFilters);
  });
  ['paperAccountUsd', 'paperRiskPct', 'paperMaxConcurrent', 'paperMaxGrossPct', 'paperLeverage', 'shortProfileSelect'].forEach((id) => {
    const node = el(id);
    if (node) node.addEventListener('change', updatePaperSettingsFromInputs);
  });
  const searchInput = el('searchInput');
  if (searchInput) searchInput.addEventListener('input', applyFilters);
  const snapshotFilter = el('snapshotFilter');
  if (snapshotFilter) {
    snapshotFilter.addEventListener('change', () => {
      setText('statusText', '当前版本仅接最新数据，历史快照切换将在下一版接入。');
    });
  }
  document.addEventListener('click', (event) => {
    const curveOpenBtn = event.target.closest('[data-action="open-auto-curve"]');
    if (curveOpenBtn) {
      openAutoCurveModal(curveOpenBtn.dataset.strategyId || 'aggregate');
      return;
    }
    const liveCurveOpenBtn = event.target.closest('[data-action="open-live-curve"]');
    if (liveCurveOpenBtn) {
      openLiveCurveModal();
      return;
    }
    const liveAccountCurveOpenBtn = event.target.closest('[data-action="open-live-account-curve"]');
    if (liveAccountCurveOpenBtn) {
      openLiveAccountCurveModal(liveAccountCurveOpenBtn.dataset.accountId || '');
      return;
    }
    const curveCloseBtn = event.target.closest('[data-action="close-auto-curve"]');
    if (curveCloseBtn) {
      closeAutoCurveModal();
      return;
    }
    const toggleLiveAccountBtn = event.target.closest('[data-action="toggle-live-account"]');
    if (toggleLiveAccountBtn) {
      toggleLiveAccountEnabled(toggleLiveAccountBtn.dataset.accountId || '', toggleLiveAccountBtn.dataset.enabled === '1');
      return;
    }
    const selectLiveAccountBtn = event.target.closest('[data-action="select-live-account"]');
    if (selectLiveAccountBtn) {
      selectLiveTraderAccount(selectLiveAccountBtn.dataset.accountId || '');
      return;
    }
    const openBtn = event.target.closest('[data-action="open-short"]');
    if (openBtn) {
      openShortPosition(openBtn.dataset.symbol);
      return;
    }
    const closeBtn = event.target.closest('[data-action="close-short"]');
    if (closeBtn) {
      closeShortPosition(closeBtn.dataset.positionId);
    }
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && openAutoCurveStrategyId) closeAutoCurveModal();
  });
}

renderShortProfileOptions();
hydratePaperControls();
setWorkspaceTab(DEFAULT_WORKSPACE_TAB);
bindEvents();
loadDashboard();
scheduleRefresh();
