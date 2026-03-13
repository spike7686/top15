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

- 最新表：`data/top15_tracker/latest/latest.csv`
- 最新 JSON：`data/top15_tracker/latest/latest.json`
- 全量历史 CSV：`data/top15_tracker/history.csv`
- 全量历史 JSONL：`data/top15_tracker/history.jsonl`
- 每轮原始快照：`data/top15_tracker/snapshots/raw/`
- 每轮清洗快照：`data/top15_tracker/snapshots/clean/`
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

## 备注

- 板块与叙事字段来自项目元数据与规则归类，适合作为研究辅助字段。
- 如果后面你要补链上字段（转账数、活跃地址、净流入等），可以在这套表结构上继续扩展。
