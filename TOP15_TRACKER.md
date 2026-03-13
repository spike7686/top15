# TOP15 采集任务说明

## 任务目标

每 5 分钟自动采集一次：
- 现货涨幅榜 TOP15
- 仅保留 24h 成交额 > 1.5 亿美元的标的
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

### 快照与缓存
- 每轮原始快照：`data/top15_tracker/snapshots/raw/`
- 每轮清洗快照：`data/top15_tracker/snapshots/clean/`
- 每轮展示快照：`data/top15_tracker/snapshots/display/`
- 元数据缓存：`data/top15_tracker/meta/coinpaprika_coin_cache.json`

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
