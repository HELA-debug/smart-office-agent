# 11 · 部署与打包

> 事实来源：`Makefile`、`docker-compose.yml`、`Dockerfile.api`、`Dockerfile.web`、`deploy/`、`packaging/`、`scripts/launch.py`、`scripts/app_entry.py`

## 11.1 四种形态对比

| 形态 | 启动方式 | 端口 | 适用 |
|---|---|---|---|
| 开发态 | `make api` + `make web`（两个终端） | 8000 / 5173 | 改代码 |
| 单端口 | `SERVE_FRONTEND=1` 起 uvicorn | 8000 | 只有后端进程 |
| Docker Compose | `make docker` | 127.0.0.1:8080 / :8000 | 隔离验证 |
| 桌面 | 双击 `启动 Office Agent.cmd` 或 `dist/Office Agent.exe` | 自动找空闲端口 | 发给别人 |

## 11.2 开发态

```bash
make api     # uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
make web     # cd frontend && npm run dev（127.0.0.1:5173）
```

前端 `/api` 由 Vite 代理转发到 8000，并配了 SSE 需要的 `timeout: 0` / `Accept-Encoding: identity`。

## 11.3 单端口模式

```bash
SERVE_FRONTEND=1 python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

- 后端直接托管 `frontend/dist`（`mount_spa`）。
- 挂载顺序必须是 `/api` 路由**之后**（`main.py:244`），否则兜底路由吞掉接口。
- 无 dist 时 `GET /` 返回 `{"name","version"}`。

## 11.4 Docker Compose

| 服务 | 配置 |
|---|---|
| `api` | `Dockerfile.api`；环境变量从 `.env` 注入（Key **不落镜像**）；卷 `app-data:/app/data`；端口只绑回环 `127.0.0.1:8000:8000`；`restart: unless-stopped`；HEALTHCHECK 打 `/api/v1/health`（interval 15s / start-period 30s / retries 8） |
| `web` | `Dockerfile.web`（两阶段：node:20-alpine 构建 → nginx:1.27-alpine）；`depends_on: api(service_healthy)`；`NGINX_CLIENT_MAX_BODY_SIZE` 取 `MAX_UPLOAD_MB`；端口 `127.0.0.1:8080:80` |

镜像构建：

- api：单阶段 `python:3.13-slim`，`pip install -e /app/backend`（依赖唯一真源是 `backend/pyproject.toml`），预建 `/app/data/{uploads,artifacts,outbox,samples,trash}`。
- web：`ARG VITE_API_BASE=/api`；三个 nginx 片段拷到 `/etc/nginx/snippets/`（**不能放 `conf.d/`**，location 级指令会被顶层 include 导致启动失败）。

### Nginx 关键配置

| 项 | 值 |
|---|---|
| SSE location | 三条正则（含 `artifacts/{id}/regenerate`），**必须写在 `location /api/` 之前** |
| SSE 参数 | `proxy_buffering off` / `proxy_cache off` / `gzip off` / `proxy_read_timeout 360s` / `X-Accel-Buffering no` |
| 普通 API | `proxy_pass http://api:8000` + `proxy_read_timeout 120s` |
| SPA | `try_files $uri $uri/ /index.html` |
| 静态资源 | `/assets/` 加 `Cache-Control: public, max-age=604800, immutable` |
| 安全头 | 每个 location 都要 include（add_header 不跨块继承）：`X-Content-Type-Options` / `X-Frame-Options: SAMEORIGIN` / `Referrer-Policy` / `Permissions-Policy` / CSP（`default-src 'self'` …） |
| 上传 | `client_max_body_size ${NGINX_CLIENT_MAX_BODY_SIZE}` |

模板渲染靠官方 nginx 镜像的 envsubst（`NGINX_ENVSUBST_FILTER=NGINX_`）。

## 11.5 桌面分发

### 路径 A：PyInstaller exe

```bash
make exe
# = npm run build → pip install pyinstaller
#   → python -m PyInstaller packaging/office_agent.spec --noconfirm --distpath dist --workpath build/pyi
```

产物 `dist/Office Agent.exe`（约 38 MB）。

`packaging/office_agent.spec` 要点：

| 项 | 配置 |
|---|---|
| 入口 | `scripts/app_entry.py` |
| 名称/图标 | `Office Agent` / `packaging/icon.ico` |
| console | `True`（保留黑窗口，地址写在里面，关窗口 = 退出） |
| datas | `frontend/dist`、`build_info.json`、`backend/app/prompts`、`skills`、`skills_catalog`、`infra/db/migrations`（**Alembic 版本文件必须按 data 带**）、`backend/config`、`.env.example` |
| hiddenimports | launch、backend.app.main、uvicorn 三套、sqlalchemy sqlite、alembic、docx、pypdf、openpyxl、reportlab、multipart、yaml、httpx |
| excludes | pytest / coverage / IPython / tkinter / sphinx / mypy / ruff |
| upx | `False`（省不了多少体积且常被杀软误报） |

纪律：**用户数据不进 exe**。运行时落在数据目录（源码态 = 仓库根；打包态 = `%LOCALAPPDATA%\Office Agent`）。`app_entry.py` 无 `.env` 时从内置 `.env.example` 复制。

### 路径 B：PWA

| 项 | 内容 |
|---|---|
| manifest | `frontend/public/manifest.webmanifest`，`display: standalone`，`display_override: [window-controls-overlay, standalone]`，`theme_color #101317`，192/256/512/maskable 图标，2 个 shortcuts |
| Service Worker | `frontend/public/sw.js`，构建时把 `__SW_VERSION__` 替换为 buildId |
| 安装入口 | `shared/lib/desktop.ts` 的 `promptInstall()`；右栏 `DesktopAppCard` |
| 安装包分发 | `desktop/package*` 四个接口可让后端把 exe 复制到本机下载目录 |

### 启动器脚本

`启动 Office Agent.cmd` / `.command` → `scripts/launch.py`：

```text
① 校验 Python 版本  ② 准备 .venv  ③ 装后端依赖（已装跳过）
④ 确认前端已构建（否则构建一次）  ⑤ 起服务 + 自动开浏览器
参数：--port（被占用自动往后找） / --no-browser / --rebuild / --check
```

`.cmd` 的注意点：**正文纯 ASCII**（cmd 逐字节读取，混排多字节会让下一行崩），中文全部放在 `scripts/messages/*.txt` 用 `type` 打印。Python 探测顺序：项目 `.venv` → `py -3` → `python`（跳过 `WindowsApps`）→ 扫描常见安装目录。

## 11.6 Makefile target 速查

| 分组 | target |
|---|---|
| 环境 | `help` / `setup` / `venv` / `install` |
| 开发 | `start`（一键，给不改代码的人）/ `api` / `web` / `dev` / `mock-api` / `mock-stop` |
| 测试 | `test` / `coverage` / `smoke`（依赖 mock-api）/ `e2e` |
| 质量 | `lint` / `typecheck` / `contract` / `contract-check` / `lock` / `lock-check` / `security` / `verify` |
| 构建 | `build`（无 Docker 时显式跳过）/ `exe` |
| 运维 | `docker` / `docker-check` / `sample` / `export` / `clean` |

几个约定：

- `PY ?= .venv/Scripts/python.exe`（Windows 优先用项目虚拟环境）
- `PIP_INDEX` 默认阿里云镜像
- Makefile/CI 都设 `NO_PROXY=no_proxy=localhost,127.0.0.1`（Windows 的 `[::1]` 会让 httpx 崩）

## 11.7 升级与备份

| 操作 | 做法 |
|---|---|
| 备份 | 停服务后整包复制 `data/`（含 `app.db-wal`/`-shm`）；或用 `make export` 导四表 JSON |
| 回灌 | `python scripts/export.py --import [--replace] --db <url>` |
| 升级代码 | 拉取后重启即可；Alembic 在启动时自动 `upgrade head` |
| 升级 exe | 直接覆盖 exe；数据目录独立，不受影响 |
| 改模型配置 | 改 `.env` 或用设置中心（后者会盖住 `.env`） |

## 11.8 部署检查清单

- [ ] `APP_ENV=prod`（会关闭交互文档）
- [ ] `API_TOKEN` 已设（否则任何人可调用）
- [ ] 端口只绑回环，不暴露公网
- [ ] `LOG_FORMAT=json`
- [ ] 数据卷已挂载（`app-data:/app/data`）
- [ ] `MAX_UPLOAD_MB` 与 Nginx `client_max_body_size` 一致
- [ ] SSE location 排在 `location /api/` 之前
- [ ] 供应商 Key 以 env 注入，不落镜像
- [ ] 备份策略就位（`data/`）
