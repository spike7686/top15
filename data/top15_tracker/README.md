# TOP15 Tracker Data Store

本目录用于存储“24h 交易额 > 1.5 亿美元”的现货涨幅榜 TOP15 增量采集结果。

## 目录结构

- `snapshots/raw/`：每次采集的原始快照 JSON
- `snapshots/clean/`：每次采集的清洗结果（CSV + JSON）
- `latest/latest.csv`：最新一轮可直接展示/分析的表格
- `latest/latest.json`：最新一轮 JSON
- `latest/manifest.json`：最新轮次索引
- `history.csv`：长期累计明细表
- `history.jsonl`：长期累计 JSONL 明细
- `meta/coinpaprika_coin_cache.json`：币种元数据缓存（板块、叙事、链接等）

## 核心字段说明

- `sector_primary`：主板块归类
- `sector_tags`：CoinPaprika 标签原始集合
- `narrative_summary`：项目叙事摘要
- `market_cap_usd`：当前市值
- `price_usd`：现价
- `change_24h_pct`：24h 涨跌幅
- `volume_24h_usd`：24h 成交额
- `turnover_ratio_24h`：24h 成交额 / 市值，用于衡量换手强度
- `liquidity_bucket`：流动性分层
- `binance_trade_count_24h`：Binance 24h 成交笔数
- `binance_quote_volume_usd`：Binance 24h 报价成交额
- `activity_bucket`：交易活跃度分层

## 数据口径

- 主源：CoinPaprika
- 复核：Binance 24hr ticker
- 过滤规则：仅保留 24h 成交额 > 150,000,000 USD 的标的，再取涨幅前 15

## 注意

- `history.csv/jsonl` 为增量追加，不回写历史。
- 币种元数据使用缓存，避免每 5 分钟重复请求项目详情接口。
- 板块与叙事字段是为后续展示/研究准备的辅助字段，不替代人工研判。
