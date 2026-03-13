# TOP15 Readonly Backend v2

只做一件事：
- 提供本地只读 API
- 同时直接托管前端展示页
- 默认监听 `127.0.0.1:8080`

## 启动

```bash
cd /root/.openclaw/agents/top15-analyst/workspace
python3 services/top15-readonly-backend-v2/server.py
```

## 直接访问

启动后可直接访问：
- 页面：`http://服务器IP:8080/`
- 健康检查：`http://服务器IP:8080/api/health`
- 摘要：`http://服务器IP:8080/api/latest-summary`

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

## 前端资源

由同一个 8080 进程直接提供：
- `/`
- `/app.js`
- `/styles.css`
