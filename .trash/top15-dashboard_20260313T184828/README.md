# TOP15 Dashboard

## 当前目标

在**不碰现网、不影响已有服务**的前提下，先在工作区搭一个：
- 本地只读 API
- 本地展示页骨架
- 独立目录管理

## 目录结构

```text
apps/top15-dashboard/
├── backend/
│   └── server.py
├── frontend/
│   ├── index.html
│   ├── app.js
│   └── styles.css
└── README.md
```

## 特性

- 默认监听：`127.0.0.1:3310`
- 只读数据源：`data/top15_tracker/`
- 无第三方依赖：使用 Python 标准库启动
- 同时提供 API 与静态页面

## API

- `/api/health`
- `/api/manifest`
- `/api/latest-display`
- `/api/latest-analysis`
- `/api/history-display?limit=200`
- `/api/snapshots`
- `/api/latest-summary`

## 启动方式

```bash
cd /root/.openclaw/agents/top15-analyst/workspace
python3 apps/top15-dashboard/backend/server.py
```

打开：

- `http://127.0.0.1:3310/`

## 后续计划

1. 接更多筛选器和图表
2. 做更正式的 dashboard UI
3. 本地验证稳定后，再评估 nginx 子路径/子域接入
4. 接入外网前先备份现有配置并做回滚预案
