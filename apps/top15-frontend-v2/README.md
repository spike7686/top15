# TOP15 Frontend v2

基于 `127.0.0.1:8080` 的只读后端构建的前端展示页。

## 目录

```text
apps/top15-frontend-v2/
├── index.html
├── app.js
└── styles.css
```

## 本地预览

```bash
cd /root/.openclaw/agents/top15-analyst/workspace/apps/top15-frontend-v2
python3 -m http.server 8081 --bind 127.0.0.1
```

访问：
- `http://127.0.0.1:8081/`

## 后端依赖

默认读取：
- `http://127.0.0.1:8080/api/manifest`
- `http://127.0.0.1:8080/api/latest-display`
- `http://127.0.0.1:8080/api/snapshots`

如需改后端地址，可在 `app.js` 中修改 `API_BASE`。
