# TOP15 Readonly Backend v2

只做一件事：
- 提供本地只读 API
- 服务 TOP15 展示数据
- 默认监听 `127.0.0.1:8080`

## 启动

```bash
cd /root/.openclaw/agents/top15-analyst/workspace
python3 services/top15-readonly-backend-v2/server.py
```

## API

- `/api/health`
- `/api/manifest`
- `/api/latest-display`
- `/api/latest-analysis`
- `/api/latest-summary`
- `/api/snapshots`

## 数据源

仅读取：
- `data/top15_tracker/latest/manifest.json`
- `data/top15_tracker/display/latest_display.json`
- `data/top15_tracker/latest/latest.json`
- `data/top15_tracker/snapshots/raw/`
