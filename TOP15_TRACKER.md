# TOP15 采集任务说明

## 任务目标

每 5 分钟自动采集一次：
- 现货涨幅榜 TOP15
- 仅保留 24h 成交额 > 1500 万美元的标的
- 增量存储，可用于后续展示、回测、黑马筛选、轮动分析

## 当前实现

- 主源：CoinPaprika
- 复核：Binance 24hr ticker
- 采集脚本：`scripts/top15_collector.py`
- 定时任务：OpenClaw cron，任务名 `TOP15 collector 5m`

## 存储位置

### 分析主表
- 最新表：`data/top15_tracker/latest/latest.csv`
- 最新 JSON：`data/top15_tracker/latest/latest.json`
- 全量历史 CSV：`data/top15_tracker/history.csv`
- 全量历史 JSONL：`data/top15_tracker/history.jsonl`

### 展示宽表
- 最新展示表：`data/top15_tracker/display/latest_display.csv`
- 最新展示 JSON：`data/top15_tracker/display/latest_display.json`
- 展示历史表：`data/top15_tracker/history_display.csv`

### K线历史数据
- Binance K线目录：`data/top15_tracker/klines/<SYMBOL>/<interval>/candles.csv`
- K线元数据：`data/top15_tracker/meta/klines/<SYMBOL>__<interval>.json`
- 当前周期：`1h` / `4h` / `1d`
- 当前窗口：最近 7 天
- 存储策略：按 `open_time_ms` 增量去重，只补新K线，避免重复写入与过度请求

### 快照与缓存
- 每轮原始快照：`data/top15_tracker/snapshots/raw/`
- 每轮清洗快照：`data/top15_tracker/snapshots/clean/`
- 每轮展示快照：`data/top15_tracker/snapshots/display/`
- 元数据缓存：`data/top15_tracker/meta/coinpaprika_coin_cache.json`
- 交叉确认播报状态：`data/top15_tracker/meta/overlap_report_state.json`

## 已保留的核心字段

### 市场核心
- 抓取时间
- TOP15 名次
- 币种名称 / 代码
- 当前价格
- 24h 涨跌幅
- 24h 成交额
- 当前市值
- 市值排名

### 流动性 / 活跃度
- turnover_ratio_24h（24h 成交额 / 市值）
- liquidity_bucket（流动性分层）
- Binance 交易对
- Binance 24h 报价成交额
- Binance 24h 成交笔数
- activity_bucket（交易活跃度分层）

### 展示 / 研究辅助
- asset_type（coin/token）
- sector_primary（主板块）
- sector_tags（标签）
- narrative_summary（叙事摘要）
- website / source_code / explorer

## 本轮新增且判断为“有必要”的字段

### 为展示与筛选增加
- `display_name`：更适合前端直接展示
- `market_cap_band`：市值分层（Mega / Large / Mid / Small）
- `momentum_bucket`：涨势强度分层
- `turnover_bucket`：换手强度分层
- `verify_grade`：复核强度标签
- `risk_flags`：风险标签集合
- `narrative_tags_normalized`：标准化叙事标签

## 为什么这些字段有必要

这些字段满足至少一个条件：
1. 可以直接用于前端展示/筛选
2. 能提高后续黑马筛选效率
3. 能把原始数值转成可分层、可排序、可解释的标签

## 这次刻意没加的字段

以下字段当前先不加，原因是维护成本高或数据可信度不够：
- 链上活跃地址数
- 净流入 / 净流出
- 大额转账笔数
- 持币地址集中度
- 社媒热度/推特声量
- 开发活跃度时序

这些字段后续可以补，但需要新的可靠数据源，不能先拍脑袋做。

## 备注

- 板块与叙事字段来自项目元数据与规则归类，适合作为研究辅助字段。
- 如果后面你要补链上字段（转账数、活跃地址、净流入等），可以在这套表结构上继续扩展。

## 交叉确认榜单飞书播报（服务器 cron 版）

### 脚本位置
- `scripts/top15_overlap_reporter.py`

### 设计目标
- 每小时固定播报一次交叉确认榜单
- 无论当前是否存在正式交叉候选，都会发到飞书群
- 若本小时出现新增正式交叉候选、排名显著变化、在榜时长突破关键阈值（1h / 2h / 4h / 6h）或正式候选清空，会在播报中附带变化原因
- 主排序：`top15_persistence_hours` 降序
- 次排序：`overlap_score` 降序
- 目标群组：飞书 `oc_5393fbde5ac800d4a72fc39d2924653e`
- 不使用 agent 底层定时；使用服务器级 cron

### 本地验证
```bash
python3 scripts/top15_overlap_reporter.py --dry-run
```

### 强制发送一次（人工测试）
```bash
python3 scripts/top15_overlap_reporter.py --force-send --dry-run
```

### 实际发送
```bash
python3 scripts/top15_overlap_reporter.py
```

### 推荐服务器 cron
建议每小时第 3 分钟执行，避免和采集任务整点冲突：

```bash
3 * * * * cd /root/.openclaw/agents/top15-analyst/workspace && /usr/bin/python3 scripts/top15_overlap_reporter.py >> logs/top15_overlap_reporter.log 2>&1
```

## 2026-03-18 修复记录：交叉确认候选误判为 0

### 问题现象
- 飞书播报与最新分析中，正式交叉候选长期为 0。
- 但榜单中多个币种已经具备较高 `overlap_score`，却统一卡在 `在榜时长不足1h`。

### 根因
1. **历史主表 `history.csv` 结构错位**
   - 旧历史文件表头与当前字段顺序不一致，导致 `symbol / name / top15_position / top15_persistence_hours` 等字段错列。
   - 结果：最近 24h 历史读取失真，持续在榜时长统计异常。

2. **采样间隔估算逻辑有误**
   - `estimate_snapshot_interval_hours()` 之前直接按行级 `captured_at_utc` 去重。
   - 同一轮快照会写入 15 个币种，多行时间戳非常接近，被误判成多次独立采样。
   - 结果：采样周期被压缩到秒级，`top15_persistence_hours` 被严重低估。

### 修复动作
1. 备份坏历史文件到：
   - `data/top15_tracker/archive/history_repair_20260318_1707/history.csv`
   - `data/top15_tracker/archive/history_repair_20260318_1707/history_display.csv`

2. 用 `history.jsonl` 重建 `history.csv`，并用 `snapshots/display/*.csv` 重建 `history_display.csv`。

3. 修改 `scripts/top15_collector.py`：
   - `load_recent_top15_history()` 增加表头完整性检查；若 `history.csv` 缺关键字段，则自动回退读取 `history.jsonl`。
   - `estimate_snapshot_interval_hours()` 改为按 `snapshot_id` 去重后估算采样间隔，而非直接按行级时间戳。
   - 将采样周期下限提升到 **5 分钟**，避免人工重跑/连续执行时把连续在榜时长压缩失真。

4. 重新执行采集：
   - `python3 scripts/top15_collector.py`

### 修复结果
修复后正式交叉候选恢复正常，最新快照中已出现：
- `ENJ`（连续在榜约 17.5h）
- `ANKR`（连续在榜约 9.5h）
- `HOT`（连续在榜约 1.5h）
- `AUCTION`（连续在榜约 2.7h）
- `ZIL`（连续在榜约 2.4h）

### 自动通知链路修复补充（2026-03-18 晚间）

#### 问题现象
- 手动执行 `scripts/top15_overlap_reporter.py` 时，飞书消息中能看到正式交叉候选。
- 但系统每小时自动通知时，曾出现：
  - `top15_persistence_hours = 0.00h`
  - `正式交叉候选已清空`
- 该结果与同时间段真实历史不一致；例如 ENJ / ANKR / HOT 等在自动通知对应时段实际上仍连续在榜。

#### 根因
- 自动通知脚本本身无异常，真正问题出在 **collector 生成 `latest/latest.json` 的历史读取链路**。
- `scripts/top15_collector.py` 在计算 `top15_persistence_hours` 时，历史源曾存在读取 `history.csv` 的可能。
- 由于 `history.csv` 在历史修复前后曾出现字段错位 / 结构污染风险，导致连续在榜时长计算偶发失真，被错误重置为 0。
- `scripts/top15_overlap_reporter.py` 读取的是 `latest/latest.json`，因此会把这个错误结果原样发送到飞书。

#### 修复动作
1. 将 `scripts/top15_collector.py` 中 `load_recent_top15_history()` 改为：
   - **强制只读取 `data/top15_tracker/history.jsonl`**
   - 不再以 `history.csv` 作为连续在榜统计的数据源
2. 重新执行：
   - `python3 scripts/top15_collector.py`
3. 重新手动验证：
   - `python3 scripts/top15_overlap_reporter.py --webhook-url '<FEISHU_WEBHOOK>'`

#### 修复后验证结果
修复后，最新快照已恢复正常，例如：
- `ENJ`：`top15_persistence_hours ≈ 18.4h`，`overlap_candidate = true`
- `ANKR`：`top15_persistence_hours ≈ 10.4h`，`overlap_candidate = true`
- `HOT`：`top15_persistence_hours ≈ 2.4h`，`overlap_candidate = true`
- `AUCTION`：`top15_persistence_hours ≈ 3.6h`，`overlap_candidate = true`
- `VANRY`：`top15_persistence_hours ≈ 1.4h`，`overlap_candidate = true`
- `CHR`：仍因在榜时长不足 1h，暂不属于正式候选（该结果属正常）

#### 经验结论
后续若再次出现“手动发正确、自动整点发错误”的现象，优先检查：
1. `latest/latest.json` 中 `top15_persistence_hours` 是否已被 collector 算错。
2. collector 的历史读取源是否稳定指向 `history.jsonl`。
3. 是否又有新的逻辑把 `history.csv` 引回连续在榜统计主路径。

#### 当前建议
- `history.jsonl` 作为连续在榜 / 时间确认层的主历史源。
- `history.csv` 与 `history_display.csv` 保留为导出与展示用途，不作为时长统计真源。

## TOP15 未来 2~4 周规则研究执行清单

### 总目标
未来 2~4 周的目标不是立即下最终规则，而是完成三件事：
1. 把样本池做厚
2. 把研究口径做稳
3. 把规则候选做成可验证框架

### 第一周：打稳研究底盘

#### 任务 1：确保数据持续稳定积累
- 继续保持 TOP15 每 5 分钟采集
- latest / history / history.jsonl 正常更新
- 自动通知继续稳定发送

**验收标准：**
- 每天没有明显采集中断
- `history.jsonl` 持续增长
- 自动通知与 `latest/latest.json` 保持一致

#### 任务 2：冻结研究标签口径
建议当前临时定义：
- 成功样本：`best_pos <= 5` 且 `max_chg24 >= 20%` 且 `duration_h >= 1h`
- 失败样本：`best_pos > 5` 且 `max_chg24 < 15%` 且 `duration_h < 1h`
- 边界样本：其余全部

**验收标准：**
- 后续所有分析默认沿用同一套定义
- 如果改口径，必须显式升级版本

#### 任务 3：确认主历史源统一
- 连续在榜、时间确认层、通知链路统一使用 `data/top15_tracker/history.jsonl`
- `history.csv` 只保留为展示与导出用途

**验收标准：**
- 关键时长计算不再依赖 `history.csv`

### 第二周：沉淀路径型变量

#### 任务 4：新增榜位前移速度字段
建议新增：
- `rank_change_15m`
- `rank_change_30m`
- `rank_change_60m`

含义：观察币种是否持续向前推进，而非仅短暂挤进榜单。

#### 任务 5：新增分数斜率字段
建议新增：
- `darkhorse_score_delta_30m`
- `persistence_score_delta_30m`
- `overlap_score_delta_30m`

含义：观察分数是在增强还是衰减，而不只看静态高分。

#### 任务 6：新增突破持续性字段
建议新增：
- `breakout_1h_persistence`
- `breakout_4h_persistence`

含义：区分一闪而过的 breakout 与持续型 breakout。

#### 任务 7：新增路径时间字段
建议新增：
- `hours_to_top10`
- `hours_to_top5`
- `hours_to_top3`

含义：衡量从首次入榜到进入更高排名区间所需时间。

### 第三周：开始做周度复盘

#### 任务 8：成功样本周报
每周固定复盘：
- 本周新增成功样本有哪些
- 它们共同特征是什么
- 与上一周是否一致

#### 任务 9：失败样本周报
每周固定复盘：
- 本周哪些币高分但没走出来
- 掉队点在哪（换手、榜位前移、持续性、breakout 持续性等）

#### 任务 10：候选规则周度验证
每周固定看：
- 候选规则命中了多少成功样本
- 误报了多少失败样本
- 哪些条件在退化

### 第四周：形成 V2 / V3 研究成果

#### 任务 11：形成 V2 规则候选矩阵
建议拆成三类：
- 结构先行型（偏 ENJ）
- 放量突破型（偏 ANKR）
- 持续占榜型（偏 VANRY / ZEC 等长期强势维持型）

#### 任务 12：形成研究版评分卡
建议目标：
- `prelaunch_score`
- `continuation_score`
- `false_break_risk`

#### 任务 13：输出正式方法论文档
内容建议包括：
- 样本定义
- 标签定义
- 核心字段
- 路径变量
- 周报方法
- 规则验证方法
- 已知局限

### 未来 2~4 周研究纪律

#### 纪律 1：不急着定规则
当前阶段重点是筛变量、看路径、做对照，而不是立即宣布最终规则。

#### 纪律 2：优先看动态，不只看静态
优先研究：
- 榜位前移
- 分数斜率
- 连续在榜
- breakout 持续性

#### 纪律 3：每个成功样本都要配失败样本对照
避免幸存者偏差，只看成功而忽略“看起来像成功但最终失败”的样本。

#### 纪律 4：以真实历史为准
所有分析必须基于已落地历史数据、可复盘样本、可重复验证逻辑，避免主观臆测。

### 当前阶段结论（供执行时参考）
- 当前样本：**够探索，不够规则定型**
- 建议继续稳定积累 **2~4 周** 后，再做更严肃的规则验证
- 当前更有前置价值的主线：
  - **资金攻击强度（turnover）**
  - **中短周期动能（1h / 4h）**
  - **趋势一致性**
- `darkhorse_score / persistence_score / overlap_score` 更适合作为辅助确认，不应单独充当主规则
