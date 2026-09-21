# AutoResume 云端管控后端

Phase 1：用户认证 + 心跳封禁 + 管理后台 + 版本更新推送。桌面客户端（Electron + 本地 sidecar）必须登录云端账号才能使用，管理员可在后台创建/封禁用户、发布新版本（下载走外部链接）。

## 架构

```
Electron 客户端
  └─ 本地 sidecar (backend/) ── 每次启动/登录验证 + 60s 心跳 ──> cloud-backend (本服务)
                                                              └─ /admin 管理后台（浏览器访问）
```

## 部署

```bash
cd cloud-backend
pip install -r requirements.txt
cp .env.example .env        # 修改 JWT_SECRET（必须！）
python scripts/create_admin.py admin@yourdomain.com your_password
python run.py               # 默认 0.0.0.0:8000
```

生产建议：Nginx 反代 + HTTPS + PostgreSQL（改 `.env` 的 `DATABASE_URL`）。

## 管理后台

浏览器访问 `http://<server>:8000/admin`，管理员登录后两个标签页：

**用户管理**
- 创建用户（分配邮箱+密码给客户）
- 封禁（填写原因，客户端 60 秒内被强制下线）/ 解封
- 重置密码、删除用户
- 查看用户活跃状态（最近登录/心跳）

**版本管理**
- 发布新版本：版本号 + 更新说明 + 下载外链（官网/网盘直链）+ 可勾选「强制更新」
- 草稿 → 发布 → 撤回 的生命周期；只有「已发布」的版本会推送给客户端
- 客户端语义化版本对比（仅更高版本才提示）

## 客户端接入

- 开发期：sidecar 默认连 `http://127.0.0.1:8000`（`backend/app/core/config.py` 的 `CLOUD_SERVER_URL`）
- 打包期：`electron/main.cjs` 读取构建机的环境变量 `AUTORESUME_CLOUD_URL` 注入给 sidecar：

```bash
set AUTORESUME_CLOUD_URL=https://cloud.yourdomain.com
npm run build
```

## API 一览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/auth/login` | 登录，返回 JWT |
| GET | `/auth/me` | 当前用户信息 |
| POST | `/auth/heartbeat` | 心跳（封禁/过期返回 401/403） |
| GET | `/admin/users` | 用户列表（搜索/过滤/分页） |
| POST | `/admin/users` | 创建用户 |
| PUT | `/admin/users/{id}` | 改昵称/重置密码 |
| POST | `/admin/users/{id}/ban` | 封禁（body: `{"reason": "..."}`） |
| POST | `/admin/users/{id}/unban` | 解封 |
| DELETE | `/admin/users/{id}` | 删除用户 |
| GET | `/admin/stats` | 用户统计 |
| GET | `/admin/releases` | 版本列表 |
| POST | `/admin/releases` | 创建版本（草稿） |
| PUT | `/admin/releases/{id}` | 编辑版本说明/链接/强制标记 |
| POST | `/admin/releases/{id}/publish` | 发布 / 撤回 |
| DELETE | `/admin/releases/{id}` | 删除版本 |
| GET | `/client/latest-release` | 客户端拉最新已发布版本（需登录） |

## 封禁生效机制

1. sidecar 每 60s 心跳，云端封禁后心跳返回 403 → sidecar 进入 `banned` 状态
2. sidecar 中间件拦截所有业务请求（HTTP 403 / WebSocket 1008 拒绝）
3. 前端每 5s 轮询 `/api/auth/status`，检测到 `banned` 立即切到封禁提示页
4. 断网宽限期 24h：云端不可达时本地可继续使用，超时后要求重新联网验证（`backend/app/core/cloud_auth.py` 的 `HEARTBEAT_GRACE_HOURS`）

## 版本更新推送机制

1. sidecar 登录后每小时向云端拉一次 `/client/latest-release`（`backend/app/core/updates.py`）
2. 与本地版本号（Electron 注入 `AUTORESUME_APP_VERSION`，来自 package.json）语义化对比，仅更高版本提示
3. 前端每 60s 轮询本地 `/api/updates/check`，`should_prompt=true` 时顶部显示更新横幅
4. 横幅「前往下载」通过 Electron `shell.openExternal` 用系统浏览器打开外链；「跳过此版本」持久化不再提醒；「设置 → 系统设置」可整体关闭更新提示
5. **强制更新**（后台勾选）：横幅红色不可关闭、不受用户设置影响，用户只能去下载

发布流程：`发版前改 package.json 的 version → npm run dist → 管理后台创建对应版本号并填外链 → 发布`

## Phase 2/3 规划

- Phase 2：AI 请求走云端代理，按量计费额度（`licenses` / `usage_logs` 表）
- Phase 3：订阅制、到期自动停用
