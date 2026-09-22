# AutoResume 云端管控后端

AutoResume 桌面套件的云端服务：账号认证与封禁、云端托管模型（客户无需自备 API Key）、每日 Token 额度管控、客户端版本更新推送。

技术栈：FastAPI + SQLAlchemy（默认 SQLite，可切 PostgreSQL），管理后台为零构建的静态单页 `static/admin.html`。

## 架构

```
Electron 客户端
  └─ 本地 sidecar (backend/)
       ├─ /auth/login + /auth/heartbeat（启动验证 + 60s 心跳，封禁即时生效）
       ├─ /client/models          拉取已发布模型模板（一键导入）
       ├─ /client/models/chat[/stream]  云端代理对话请求（配额计费）
       ├─ /client/latest-release  检查版本更新
       └─ 浏览器访问 /admin       管理后台
```

## 部署

```bash
cd cloud-backend
pip install -r requirements.txt
cp .env.example .env        # 修改 JWT_SECRET（必须，否则拒绝启动）
python scripts/create_admin.py <管理员账号> <密码>
python run.py               # 默认 0.0.0.0:8000
```

`.env` 关键项：`JWT_SECRET`（随机长串）、`DATABASE_URL`、`DAILY_TOKEN_QUOTA`（每用户每日 token 额度兜底默认值）。

生产建议：Nginx 反代 + HTTPS + PostgreSQL；`cloud.db`、`.env` 含密钥与用户数据，勿入版本库。

## 管理后台

浏览器访问 `http://<server>:8000/admin`，管理员登录后五个页面：

| 页面 | 能力 |
|------|------|
| 仪表盘 | 用户/用量总览、最近活跃用户 |
| 用户管理 | 创建用户（默认密码 123456）、封禁/解封、重置密码、删除 |
| 版本管理 | 草稿 → 发布 → 撤回；版本号 + 更新说明 + 下载外链 + 强制更新 |
| 模型管理 | 模型模板 CRUD：Base URL / API Key / 上下文 / 工具轮次，发布后客户端可拉取 |
| 用量统计 | 今日/累计 token 与请求数、按日按用户明细、**额度调整（见下）** |

## Token 额度体系

每日额度按 UTC 日期重置，生效优先级：**个人额度 > 整体默认额度 > 环境变量 `DAILY_TOKEN_QUOTA`**。

- 记账方式「预留 + 结转」：请求准入前按 `输入估算 + max_tokens` 原子预留（并发不超卖），结束后按服务商 `usage.total_tokens` 结转为实际用量；上游报错全额退还
- 用量统计页可「提升整体额度」（写入 `system_settings` 表，重启不丢）或按行「提升/调整额度」（写 `users.daily_token_quota`，输 0 恢复跟随整体默认）
- 调整**当日即时生效**，无需等到次日重置；超额请求返回 429 并提示实际生效额度

## 封禁生效机制

1. sidecar 每 60s 心跳，云端封禁后心跳返回 403 → sidecar 进入 `banned` 状态
2. sidecar 中间件拦截所有业务请求（HTTP 403 / WebSocket 1008 拒绝）
3. 前端每 5s 轮询 `/api/auth/status`，检测到 `banned` 立即切到封禁提示页
4. 断网宽限期 24h：云端不可达时本地可继续使用，超时后要求重新联网验证（`backend/app/core/cloud_auth.py` 的 `HEARTBEAT_GRACE_HOURS`）

## 版本更新推送机制

1. sidecar 登录后每小时拉一次 `/client/latest-release`（`backend/app/core/updates.py`）
2. 与本地版本号（Electron 注入 `AUTORESUME_APP_VERSION`，来自 package.json）语义化对比，仅更高版本提示
3. 前端每 60s 轮询本地 `/api/updates/check`，`should_prompt=true` 时顶部显示更新横幅
4. 横幅「前往下载」用系统浏览器打开外链；「跳过此版本」持久化不再提醒；「设置 → 系统设置」可整体关闭更新提示
5. **强制更新**（后台勾选）：横幅红色不可关闭、不受用户设置影响

发布流程：`改根 package.json 的 version → npm run dist:win / dist:mac → 管理后台创建对应版本号并填外链 → 发布`

## 客户端接入云端

- 开发期：sidecar 默认连 `http://127.0.0.1:8000`（`backend/app/core/config.py` 的 `CLOUD_SERVER_URL`）
- 打包期：构建机设置环境变量后打包，`scripts/write-cloud-url.cjs` 会将其写入 `electron/cloud-config.json` 注入客户端：

```powershell
$env:AUTORESUME_CLOUD_URL="https://cloud.yourdomain.com"
npm run dist:win
```

## API 一览

**认证（用户侧）**

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/auth/login` | 登录，返回 JWT |
| GET | `/auth/me` | 当前用户信息 |
| POST | `/auth/heartbeat` | 心跳（封禁/过期返回 401/403） |
| POST | `/auth/change-password` | 修改密码 |

**客户端（需登录）**

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/client/models` | 已发布模型模板列表（不含 API Key） |
| POST | `/client/models/chat` | 云端代理非流式对话（配额计费） |
| POST | `/client/models/chat/stream` | 云端代理 SSE 流式对话（配额计费） |
| GET | `/client/latest-release` | 最新已发布版本，无则返回 null |

**管理后台（需管理员，`/admin/*` 统一鉴权）**

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/admin/users` | 用户列表（搜索/过滤/分页） |
| POST | `/admin/users` | 创建用户（固定 role=user） |
| PUT | `/admin/users/{id}` | 改昵称 / 重置密码 |
| POST | `/admin/users/{id}/ban` / `unban` | 封禁（带原因）/ 解封 |
| DELETE | `/admin/users/{id}` | 删除用户 |
| PUT | `/admin/users/{id}/quota` | 个人日额度（null=恢复跟随整体） |
| GET / PUT | `/admin/quota` | 整体默认日额度（PUT null=恢复环境变量默认） |
| GET | `/admin/stats` | 用户与用量总览 |
| GET | `/admin/usage` | 按日按用户用量明细（含生效额度） |
| GET / POST | `/admin/models` | 模型模板列表 / 新建 |
| PUT / DELETE | `/admin/models/{id}` | 编辑 / 删除 |
| POST | `/admin/models/{id}/publish` | 发布 / 撤回 |
| GET / POST | `/admin/releases` | 版本列表 / 新建（草稿） |
| PUT / DELETE | `/admin/releases/{id}` | 编辑 / 删除 |
| POST | `/admin/releases/{id}/publish` | 发布 / 撤回 |

数据库结构变更由 `init_db` 启动时自动轻量迁移（SQLite 加列），无需手工操作。
