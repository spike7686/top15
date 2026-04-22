# MEMORY.md

## User Preferences

- 用户名：王宝泽；称呼：宝总。
- 时区：Asia/Shanghai。
- 偏好专业风格。
- 优先使用中文。
- 使用专业名词时，需附带简明解释。
- 回答与做事汇报时，先给结论，再展开说明。

## Working Identity / Role Positioning

除非宝总明确重新划分身份或新增/修改要素，否则默认长期遵守以下工作身份定位：

- 角色名称：TOP15分析师。
- 研究方向：聚焦虚拟货币现货涨幅榜 TOP 15。
- 流动性过滤：仅研究 24 小时交易额 > 1500 万美元、且 Binance 现货可交易的标的，剔除流动性不足项目与稳定币。
- 核心任务：
  - 筛选黑马：在符合条件标的中，挖掘最有概率冲击并稳定在前 5 名的潜力币种。
  - 形态解剖：结合历史走势与 K 线形态，总结价格规律。
  - 轮动推演：识别板块轮动的确定性特征。
  - 模型构建：建立具备未来预测能力的量化分析模型。
- 数据真实性原则：严禁数据幻觉。所有分析必须基于真实市场数据，包括价格、成交量、市值、链上转账等。
- 数据获取机制：
  - 首选：主动调用授权的加密数据 API（如 CoinGecko、CoinMarketCap、TradingView 等）抓取实时数据。
  - 次选：若无法连接数据库或权限不足，则停止分析，并明确提示：
    “BOSS，需要您提供数据接口权限，或手动上传最新的CSV/Excel数据表格。”
- 输出原则：
  - 科学严谨，拒绝空谈与臆造。
  - 重视赛道、总交易量、叙事逻辑。
  - 持续学习和迭代分析方法。
  - 产出必须专业、详细、以数据事实为依据。

### Current TOP15 System Defaults

- 时间口径：前端与数据展示默认使用北京时间（GMT+8 / captured_at_cst）。
- 榜单过滤：仅保留 24h 成交额 > 1500 万美元、剔除稳定币、且 Binance 现货可交易的标的。
- 历史数据策略：旧规则（>1.5 亿美元）数据已归档到 `data/top15_tracker/archive/rule_gt_150m_before_20260314/`；默认分析只使用新规则主历史文件。
- K线数据：已接入 Binance `1h / 4h / 1d` 最近 7 天 K线，按 `open_time_ms` 增量去重存储，避免重复请求。
- 结构特征层：当前默认输出 `trend_1d / trend_4h / trend_1h / breakout_1h / breakout_4h / price_change_7d_pct / max_drawdown_7d_pct / structure_score / structure_grade / structure_state`。
- 黑马筛选层：当前默认输出 `darkhorse_score / top5_potential / sustainability / risk_reward_profile / darkhorse_tag`，作为前五潜力与持续性判断基础。
- 持续走强层：当前默认输出 `persistence_score / persistence_label / continuation_risk / continuation_evidence`，用于识别强势延续质量。
- 时间确认层：当前默认输出 `top15_persistence_hours / top15_presence_ratio_24h / top15_presence_snapshots_24h / top15_snapshot_count_24h / top15_observation_window_hours / top15_snapshot_interval_hours_est`，用于判断是否在榜持续而非瞬时冲高。
- 交叉确认层：当前默认输出 `overlap_gate_pass / overlap_score / overlap_label / overlap_rank_signal / overlap_candidate / overlap_evidence`，用于综合黑马、持续走强、在榜时长与在榜占比，筛出更高质量的趋势候选。
- 前端展示：当前首页已完成三榜结构：`黑马候选榜 / 持续走强候选榜 / 交叉确认候选榜`，并保留证据链、主榜单、算法说明与方法论展示。

### TOP15 Product Map / Code Locations

- 主采集与分析脚本：`scripts/top15_collector.py`
  - 负责：主榜抓取、Binance 复核、K线同步、结构特征、黑马层、持续走强层、时间确认层、交叉确认层、latest/history/display 落表。
- 前端页面：`apps/top15-frontend-v2/`
  - `index.html`：页面骨架
  - `app.js`：前端渲染逻辑、三榜排序、证据链、算法详情
  - `styles.css`：整体科技风视觉、三榜分区配色、卡片主题、顶部细线高光
- 只读后端服务：`services/top15-readonly-backend-v2/server.py`
  - 负责提供 `/api/manifest`、`/api/latest-display`、`/api/latest-analysis`、`/api/snapshots` 等接口，并托管前端静态文件。
- 产品说明文件：`TOP15_TRACKER.md`
  - 记录目标、采集口径、存储位置、字段范围、当前实现说明。

### TOP15 Product Data Paths

- 最新分析主表：`data/top15_tracker/latest/latest.csv`
- 最新分析 JSON：`data/top15_tracker/latest/latest.json`
- 最新展示表：`data/top15_tracker/display/latest_display.csv`
- 最新展示 JSON：`data/top15_tracker/display/latest_display.json`
- 历史主表：`data/top15_tracker/history.csv`
- 历史展示表：`data/top15_tracker/history_display.csv`
- 历史 JSONL：`data/top15_tracker/history.jsonl`
- K线目录：`data/top15_tracker/klines/<SYMBOL>/<interval>/candles.csv`
- K线元数据：`data/top15_tracker/meta/klines/<SYMBOL>__<interval>.json`
- 快照目录：`data/top15_tracker/snapshots/raw/`、`clean/`、`display/`

### TOP15 Startup / Run Method

当前默认启动方式应记住：

1. **执行采集更新数据**
   - 在 workspace 根目录运行：
   - `python3 scripts/top15_collector.py`

2. **启动只读后端 + 前端页面**
   - 在 workspace 根目录运行：
   - `python3 services/top15-readonly-backend-v2/server.py`
   - 默认监听：`127.0.0.1:8080`

3. **前端访问方式**
   - 浏览器打开：`http://127.0.0.1:8080/`

4. **当前后端接口**
   - `/api/health`
   - `/api/manifest`
   - `/api/latest-display`
   - `/api/latest-analysis`
   - `/api/latest-summary`
   - `/api/snapshots`

5. **定时采集任务说明**
   - 文档中记录的定时任务名为：`TOP15 collector 5m`
   - 采集说明写在：`TOP15_TRACKER.md`

### TOP15 Reliability Fixes (2026-03-18)

- 2026-03-18 修复了 TOP15 交叉确认候选长期显示为 0 的问题。
- 根因有两层：
  1. `data/top15_tracker/history.csv` 表结构与当前字段列表不一致，导致历史读取错位。
  2. `scripts/top15_collector.py` 中 `estimate_snapshot_interval_hours()` 曾按行级时间戳估算采样周期，把同一轮快照的多币种记录误判为多次独立采样，导致 `top15_persistence_hours` 被严重低估。
- 已执行的修复：
  - 备份旧历史文件到 `data/top15_tracker/archive/history_repair_20260318_1707/`
  - 用 `history.jsonl` 重建 `history.csv`
  - 用 `snapshots/display/*.csv` 重建 `history_display.csv`
  - 为 `load_recent_top15_history()` 增加 CSV 表头校验与 JSONL 回退
  - 将采样间隔估算改为按 `snapshot_id` 去重，并将周期下限锁到 5 分钟
- 修复后，正式交叉候选恢复正常；最新结果已出现 ENJ、ANKR、HOT、AUCTION、ZIL 等正式交叉候选。
- 后续若再次看到“高 overlap_score 但正式交叉候选长期为 0”，优先检查历史表结构和采样间隔估算。

### TOP15 Research Roadmap (2026-03-18)

- 当前 TOP15 规则研究判断：**现有样本够做探索，不够做规则定型**。
- 现阶段主历史跨度仍偏短（约 4 天级别），容易受单一市场状态影响；建议继续稳定积累 **2~4 周** 后，再做更严肃的规则验证。
- 未来 2~4 周研究主线：
  1. 继续稳定积累 TOP15 历史快照与 K 线数据；
  2. 冻结成功 / 失败 / 边界样本定义，避免分析口径漂移；
  3. 保留当前核心字段（趋势、动能、换手、黑马、持续走强、时间确认、交叉确认）；
  4. 重点补“路径型变量”，尤其是：榜位前移速度、首次入榜后 1 小时演化、darkhorse/persistence/overlap 分数斜率、突破持续性；
  5. 每周复盘新增成功样本与失败样本，不急于下最终规则。
- 当前阶段最重要的研究结论：
  - 更有前置价值的是 **资金攻击强度（turnover）+ 中短周期动能（1h/4h）+ 趋势一致性**；
  - `darkhorse_score / persistence_score / overlap_score` 更适合作为辅助确认，不应单独充当主规则。
- 当前建议：先进入“研究准备期 / 变量筛选期 / 标签体系打磨期”，待样本厚度上来后再做 V2/V3 规则定型。

### TOP15 Notification / History Reliability (2026-03-18)

- 2026-03-18 还修复过一次关键链路问题：自动通知曾出现“手动发正确、自动整点发错误”。
- 根因：collector 计算 `top15_persistence_hours` 时，历史读取源不稳定，`history.csv` 污染会导致连续在榜时长被错误清零。
- 当前修复原则：连续在榜 / 时间确认层研究与通知，统一以 `data/top15_tracker/history.jsonl` 为主历史源；`history.csv` / `history_display.csv` 仅保留为展示与导出用途。
