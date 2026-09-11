# local-edit-agent —— 模仿 Trae 的「局部文件修改」AI Agent（MCP 服务器）

一个基于 **MCP / Function Calling** 的本地文件编辑 Agent。核心哲学与 Trae 一致：

> **严禁 LLM 输出完整文件。** 所有文件改动一律通过局部替换工具 `str_replace` 完成，
> 配合 `view`（按行按需读取省 token）、`git_snapshot`（修改前备份）、`validate_syntax`
> （语法校验 + 自动回滚），形成一套安全、可回滚、只改「一处」的编辑闭环。

---

## 1. 项目目录结构

```
local-edit-agent/
├── local_edit_server.py      # MCP 入口：注册 6 个工具（FastMCP）
├── smoke_test.py             # 端到端冒烟测试（view → str_replace → apply）
├── README.md                 # 本文档
└── server/                   # 业务逻辑抽离为可独立测试的纯函数模块
    ├── __init__.py           # 包说明
    ├── hashing.py            # md5 计算 + 乐观锁校验
    ├── matcher.py            # 核心：精确 → 空白符标准化 → difflib 滑动窗相似度
    ├── differ.py             # unified diff / 红绿预览生成
    ├── snapshot.py           # git 快照备份 + 回滚（manifest.json）
    ├── syntax.py             # 语法校验（ast.parse / json / yaml / node）
    ├── staging.py            # 暂存区：str_replace 不落盘，apply 后再写
    └── fs.py                 # 工作区路径安全校验（防目录穿越）
```

模块职责边界：
- **工具层**（`local_edit_server.py`）只负责接收参数、编排流程、返回 JSON。
- **辅助层**（`server/*`）是纯函数，可单独单测、可复用。

---

## 2. 工具清单

| 工具 | 读/写 | 作用 |
|------|------|------|
| `view` | 只读 | 按 `start_line`..`end_line` 读取文件片段，返回 `file_md5` 供后续乐观锁使用 |
| `str_replace` | 写（暂存） | **核心工具**：精确/降级匹配一段 `old_str`，生成 unified diff 预览，暂存不落盘 |
| `apply` | 写（落地） | 用户确认后把暂存区 diff 写入磁盘，写后即时语法校验，失败自动回滚 |
| `git_snapshot` | 写 | 修改前把文件原始内容备份到 `.local-edit-snapshots/`（含 git 跟踪检测） |
| `validate_syntax` | 读 | 校验磁盘文件语法（Python/JSON/YAML/JS） |
| `rollback` | 写 | 按快照 ID 一键回滚文件到备份版本 |

---

## 3. 工具调用 JSON 样例

以下为 MCP 协议下调用各工具的请求 JSON。

### 3.1 view —— 读取目标片段（第 35~40 行）

```json
{
  "method": "tools/call",
  "params": {
    "name": "view",
    "arguments": {
      "file_path": "src/icons.py",
      "start_line": 35,
      "end_line": 40
    }
  }
}
```

响应（节选）：

```json
{
  "file_path": "…/src/icons.py",
  "file_md5": "14ddb08762d2a1cbe9e2ff0f7d2f0a1c",
  "total_lines": 120,
  "start_line": 35,
  "end_line": 40,
  "lines": [
    { "num": 35, "text": "# 图标替换点" },
    { "num": 36, "text": "SVG_ICON = \"fa-circle\"" },
    { "num": 37, "text": "size = 24" }
  ],
  "truncated": false
}
```

`file_md5` 必须原样传给下一次 `str_replace` 的 `expected_hash`。

### 3.2 str_replace —— 局部替换（核心工具）

```json
{
  "name": "str_replace",
  "arguments": {
    "file_path": "src/icons.py",
    "old_str": "SVG_ICON = \"fa-circle\"\nsize = 24",
    "new_str": "SVG_ICON = \"bi-circle-fill\"\nsize = 24",
    "expected_hash": "14ddb08762d2a1cbeef2e7d2f0a06c"
  }
}
```

### 3.3 apply —— 确认落地

```json
{ "name": "apply", "arguments": { "file_path": "src/icons.py" } }
```

### 3.4 git_snapshot / validate_syntax / rollback

```json
{ "name": "git_snapshot",  "arguments": {} }
{ "name": "validate_syntax", "arguments": { "file_path": "src/icons.py" } }
{ "name": "rollback",      "arguments": { "snapshot_id": "20260911_120000_123456" } }
```

---

## 4. 使用示例：把「SVG 图标」替换成「Bootstrap Icons」

模拟一次单行修改的完整会话。

**场景**：把 `src/icons.py` 第 36 行 `SVG_ICON = "fa-circle"` 改为 Bootstrap Icons 的
`"bi-circle-fill"`。

### 步骤 1 —— 先备份快照（可选但推荐）

```
User: 先对 src/icons.py 做一次快照备份
Agent: git_snapshot { file_path: "src/icons.py" }
```

### 步骤 2 —— view 读取上下文

```
User: 看下 src/icons.py 第 33~40 行，我要改第 36 行
Agent: view { file_path: "src/icons.py", start_line: 33, end_line: 40 }
```

返回 `d[file_md5]` = `14ddb087…`。Agent 只拿到 8 行上下文，而不是整个大文件（省 token）。

### 步骤 3 —— str_replace 携带锚定上下文 + 乐观锁

```
Agent: str_replace {
  file_path:     "src/icons.py",
  old_str:       "SVG_ICON = \"fa-circle\"\nsize = 24",
  new_str:       "SVG_ICON = \"bi-circle-fill\"\nsize = 24",
  expected_hash: "14ddb087…"
}
```

- `old_str` 带上了下一行 `size = 24` 作为锚定前文，确保全局唯一，避免在别处也出现 `fa-circle`
  时被误改。
- 工具先校验 `expected_hash`：磁盘 md5 若已不等于 `14ddb087…`，立即报错要求重新 `view`。

返回（节选，staged 模式，**未落盘**）：

```json
{
  "status": "staged",
  "applied": false,
  "unified_diff": "--- a/src/icons.py\n+++ b/src/icons.py\n@@ -35,3 +35,3 @@\n-SVG_ICON = \"fa-circle\"\n+SVG_ICON = \"bi-circle-fill\"\n size = 24",
  "match": { "exact": true, "similarity": "exact" },
  "next_step": "调用 apply 确认落地，或调用 discard 丢弃本次改动。"
}
```

### 步骤 4 —— 用户查看红绿 diff 预览，确认 Apply

- **绿色** `+ SVG_ICON = "bi-circle-fill"`（新增）
- **红色** `- SVG_ICON = "fa-circle"`（删除）

```
User: 确认，落地
Agent: apply { file_path: "src/icons.py" }
```

`apply` 写盘后立即 `validate_syntax`：若这一行改坏了语法（例如引号不配对），自动回滚到
本次修改前的快照，绝不留残缺代码。校验通过才返回成功。

---

## 5. 降级匹配策略（str_replace 的灵魂）

`str_replace` 在「找到 `old_str` 该改哪里」时，按以下顺序逐级降级，**任何一级命中的位置
恰好一处**才会执行；多于一处的**直接拒绝**，绝不猜测改哪。

### 5.1 精确匹配

未经任何加工，把 `old_str` 在完整文件内容里做子串查找。

- 命中 **1 处** → 直接替换，`matched_exact = True`。
- 命中 **≥2 处** → **歧义，拒绝**，并返回命中数量提示 Agent 追加锚定上下文。
- 命中 **0 处** → 进入降级。

### 5.2 空白符标准化

很多 LLM 生成 `old_str` 时缩进/换行与磁盘不一致（如用 2 空格代替 4 空格）。降级一：
对 `old_str` 与文件内容做「把连续空白折叠为单个空格」的规范化，再尝试精确匹配。
规范化后不再做字符下标映射（因为长度变了），因此命中后继续走第 5.3 步完成精确定位。

### 5.3 difflib 滑动窗相似度

前面仍失败时，把文件按“行”切成与 `old_str` 行数匹配的滑动窗口，对每个窗口与
`old_str` 做 `SequenceMatcher.ratio()` 相似度打分：

- 只保留 Top-K 候选避免 O(n²) 内存膨胀。
- 最高相似度 < `MIN_SIMILARITY (0.70)` → 视为找不到，报错并附文件开头预览，
  让 Agent 重读 `view` 修正 `old_str`。
- 最高相似度与第二名差距过小（< `TOP_AMBIGUITY_EPS (0.005)`）→ 歧义，拒绝，
  避免「改了相似的那一处却不是 Agent 想改的位置」。

### 5.4 匹配失败时

工具在错误信息中**附上相似度最高的候选 / 文件片段预览**，Agent 可比对真实内容，
修正好 `old_str` 后重试，而不是盲目重传原 `old_str`。

---

## 6. 安全与防护机制

| 机制 | 说明 |
|------|------|
| **乐观锁（expected_hash / md5）** | 每次 `str_replace` 前校验磁盘 md5；不一致立即报错，要求重新 `view`。杜绝「用旧快照去改新文件」。 |
| **暂存区 + Apply 确认** | `str_replace` 只在内存生成 diff，**不直接覆盖磁盘**；用户确认为 `apply` 后才落笔。拒绝则丢弃本次改动。 |
| **小粒度修改** | 一次 `str_replace` 只改「一处」，多处改动必须多次循环调用，绝不做几十行的大改。 |
| **先快照后改** | `git_snapshot` 在任何改前创建不可见的备份，出了错 `rollback` 一键还原。 |
| **语法校验自动回滚** | 落盘后立即 `validate_syntax`；Python 用 `ast.parse`、JSON 用 `json.loads`、YAML 用 `yaml.safe_load`、JS 用 `node --check`。校验失败自动回滚本次变更。 |
| **路径安全** | `fs.resolve_path` 规范化 `../`、符号链接，并可配置 `LOCAL_EDIT_WORKSPACE` 限定工作区，防目录穿越。 |

---

## 7. 运行与自测

```bash
# 1) 依赖（mcp + pydantic）
pip install "mcp[cli]" pydantic

# 2) 冒烟测试（内置端到端流程）
python smoke_test.py

# 3) MCP 服务启动（stdio，供 Claude / 其它 MCP 客户端调用）
python local_edit_server.py

# 4) 或启动为 streamable HTTP 服务
python local_edit_server.py --http
```

环境变量：

| 变量 | 说明 | 默认 |
|------|------|------|
| `LOCAL_EDIT_WORKSPACE` | 允许读写的工作区根目录（留空则不限制） | 空 |
| `LOCAL_EDIT_APPLY_MODE` | `staged`（暂存待 Apply）或 `auto`（直接写盘+自动回滚） | `staged` |
| `LOCAL_EDIT_SNAPSHOT_DIR` | 快照与 manifest 存放目录 | `.local-edit-snapshots/` |

---

## 8. 原理简述

```
                 view(读取片段 + file_md5)        git_snapshot(备份)
                      │                                  │
  LLM ──Function Call│───────────►　MCP Server ──────────┤
       └───────────??│  str_replace{ old_str, expected_hash }
                      │        │ ① hash 校验(乐观锁)
                      │        │ ② 精确→降级匹配，恰好1处才放行
                      │        │ ③ 内存替换，生成 unified diff
                      │        ▼
                      │   diff 红绿预览（未落盘）
                      ▼
                用户确认 ── apply ──► 写盘 ── validate_syntax ──失败→ rollback
```

- LLM 永不输出整份文件；它只「指位置」（old_str）与「给新内容」（new_str）。
- 所有改动都经过自己是「暂存 → diff → apply → 校验 → 回滚」的安全水道，防止破坏正在使用的文件。