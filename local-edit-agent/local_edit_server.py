"""
local-edit-agent —— 本地文件局部编辑 MCP 服务器。

模拟 Trae 的局部文件修改机制，核心设计：
- 严禁 Agent 输出完整文件；所有改动仅通过局部替换工具 str_replace 完成。
- 每次 str_replace 只修改一处，改用自带锚定上下文的 old_str，并携带 expected_hash
  (md5 乐观锁) 防止"旧快照改新文件"。
- 匹配失败时启用降级策略（空白符标准化 + difflib 滑动窗口相似度），命中恰好一处才执行；
  命中多处直接拒绝，返回相似候选项让 Agent 修正后重试。
- 修改不直接覆盖磁盘：先生成 unified diff 预览，等待用户 Apply 后再落地；
  语法校验失败自动回滚。
- 每次修改前自动创建 git 快照，出错可一键回滚。

启动入口：
    python local_edit_server.py          # 使用 stdio 传输
    python local_edit_server.py --http   # 使用 streamable_http 传输，端口 8000
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from server import differ, hashing, matcher, snapshot, staging, syntax
from server.fs import WorkspaceError
from server.hashing import HashMismatchError
from server.matcher import MatchError

# 初始化 MCP 服务器名称遵循 {service}_mcp 规范
mcp: FastMCP = FastMCP("local_edit_mcp")

# 修改落地方式：staged（默认，生成 diff 待 Apply 后写盘）| auto（直接写盘+语法校验回滚）
APPLY_MODE_ENV = "LOCAL_EDIT_APPLY_MODE"


# --------------------------------------------------------------------------- #
# 工具 1：view —— 只读取需要的上下文
# --------------------------------------------------------------------------- #
@mcp.tool(
    name="view",
    annotations={
        "title": "读取文件指定行范围",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def view_tool(
    file_path: str = Field(..., description="目标文件路径（绝对或相对当前工作目录）。"),
    start_line: int = Field(1, description="起始行号（1 起），默认 1。", ge=1),
    end_line: Optional[int] = Field(None, description="结束行号（含），默认返回尽量多的行。", ge=1),
):
    """读取文件指定行范围，只返回需要的上下文（节省 token），并附文件 md5 作为乐观锁。

    Returns（JSON 文本）:
        {
          "file_path": ..., "file_md5": "<尽快锁 hash，供 str_replace 的 expected_hash 用>",
          "total_lines": N, "start_line": .., "end_line": ..,
          "lines": [ {"num": 1, "text": "..."}, ... ], "truncated": false
        }

    Errors:
        文件不存在/目录/读写失败时返回 "Error: ..."。
    """
    try:
        p = _resolve_path(file_path)
        if not p.exists():
            return f"Error: 文件不存在: {p}。请先创建该文件。"
        if p.is_dir():
            return f"Error: {p} 是目录，请指向文件。"

        content = p.read_text(encoding="utf-8", errors="replace")
        lines = content.split("\n")
        total = len(lines)

        # 防御：可选参数在部分调用路径下可能携带 FieldInfo 默认值而非 None/int，
        # 统一规约为合法的整数（1 起，默认读到文件末尾）。
        if not isinstance(start_line, int):
            start_line = 1
        start_line = max(1, start_line)
        if not isinstance(end_line, int):
            end_line = total
        end_line = max(start_line, min(end_line, total))

        selected = lines[start_line - 1 : end_line]
        numbered = [{"num": start_line + i, "text": line} for i, line in enumerate(selected)]

        return json.dumps(
            {
                "file_path": str(p),
                "file_md5": hashing.compute_hash(p),
                "total_lines": total,
                "start_line": start_line,
                "end_line": end_line,
                "lines": numbered,
                "truncated": end_line < total,
            },
            ensure_ascii=False,
            indent=2,
        )
    except Exception as e:
        return f"Error: view 失败: {e}"


# --------------------------------------------------------------------------- #
# 工具 2：str_replace —— 核心局部替换工具
# --------------------------------------------------------------------------- #
@mcp.tool(
    name="str_replace",
    annotations={
        "title": "局部文本替换（乐观锁 + 降级匹配）",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def str_replace_tool(
    file_path: str = Field(..., description="目标文件路径（绝对或相对工作区）。"),
    old_str: str = Field(
        ...,
        description=(
            "要被替换的旧文本。**必须带上少量前后锚定上下文**，保证该片段在文件全局唯一。\n"
            "示例：只改一行引用，应把上一行/下一行也带上一小段，避免在别处撞车。"
        ),
    ),
    new_str: str = Field(..., description="替换后的新文本。"),
    expected_hash: Optional[str] = Field(
        default=None,
        description=(
            "文件 md5（乐观锁）。通常由最近的 view 返回；若缺失则跳过 hash 校验。"
            "校验失败会报错，要求先重新 view。"
        ),
    ),
):
    """在文件内精确/相似匹配一段旧文本并局部替换（核心工具，一次只改一处）。

    执行流程：
    1. 校验 expected_hash（乐观锁，防止旧快照改新文件）。
    2. 在"当前生效内容"上匹配（精确 → 空白符标准化 → difflib 滑动窗口相似度）。
    3. 命中且唯一时做局部替换，生成 unified diff 预览。
    4. staged 模式：不覆盖磁盘，返回 diff 等待 apply 落地；auto 模式：直接写盘并语法校验，失败回滚。

    Errors:
        - HashMismatchError: 磁盘已变化，需重新 view。
        - MatchError: 未发现唯一命中（歧义/多候选），返回候选供修正 old_str 后重试。
    """
    try:
        p = _resolve_path(file_path)

        # 1) 乐观锁校验（仅对已存在的文件）
        if p.exists():
            if expected_hash is None:
                return (
                    "Error: 请先调用 view 拿到 file_md5 作为 expected_hash（乐观锁）。"
                    "不允许在未取得最新快照的情况下修改文件。"
                )
            hashing.verify_hash(p, expected_hash)

        # 2) 取"当前生效内容"（默认优先暂存区，其次磁盘）
        staging_store = staging.get_staging()
        base = staging_store.current_content(p)
        old_content = base if base is not None else ""

        # 3) 匹配（精确 -> 降级）
        match = matcher.match_once(old_content, old_str)

        # 4) 局部替换
        new_content = old_content[: match.start] + new_str + old_content[match.end :]

        # 5) 生成 diff（红绿预览）
        unified = differ.build_unified_diff(str(p), old_content, new_content)
        inline = differ.build_inline_preview(old_content, new_content, match.start, match.end)

        mode = _apply_mode()
        if mode == "auto":
            snapshot_info = snapshot.make_snapshot(str(p))
            if not _write_content(p, new_content):
                return "Error: 写入失败，已中止，未改动磁盘。"
            vres = syntax.validate_file_on_disk(p)
            if not vres["ok"]:
                _rollback_to_snapshot(p, snapshot_info)
                return f"Error: 语法校验失败，已自动回滚本次修改。\n{vres['message']}\n请重新 view 并修改。"
            return json.dumps(
                {
                    "status": "applied_auto",
                    "applied": True,
                    "file_path": str(p),
                    "unified_diff": unified,
                    "matched_exact": match.matched_exact,
                    "similarity": round(match.similarity, 3) if not match.matched_exact else "exact",
                    "syntax": vres,
                },
                ensure_ascii=False,
                indent=2,
            )

        # staged 模式：暂存不落盘
        staging_store.stage(p, new_content)
        return json.dumps(
            {
                "status": "staged",
                "applied": False,
                "reason": "diff 预览已生成，等待用户 Apply 后落地。",
                "file_path": str(p),
                "unified_diff": unified,
                "inline_preview": {
                    "before": _preview_lines(inline["before"], 8),
                    "after": _preview_lines(inline["after"], 8),
                    "line_range_before": inline["line_range_before"],
                },
                "match": {
                    "exact": match.matched_exact,
                    "similarity": round(match.similarity, 3) if not match.matched_exact else "exact",
                },
                "next_step": "调用 apply 确认落地，或调用 discard 丢弃本次改动。",
            },
            ensure_ascii=False,
            indent=2,
        )
    except HashMismatchError as e:
        return f"Error: {e}"
    except MatchError as e:
        if e.hits:
            return f"Error: 匹配歧义（共 {len(e.hits)} 处），已拒绝。请追加锚定上下文使 old_str 唯一后再重试。"
        return (
            "Error: 匹配失败："
            + str(e)
            + "\n匹配规则：优先精确；失败启用空白符标准化 + difflib 相似度降级。\n"
            "请重新 view 最近内容，构造带足够锚定上下文的 old_str 后重试。"
        )
    except Exception as e:
        return f"Error: str_replace 失败: {e}"


# --------------------------------------------------------------------------- #
# 工具 3：apply —— 用户确认后落地
# --------------------------------------------------------------------------- #
@mcp.tool(
    name="apply",
    annotations={
        "title": "确认并落地暂存的改动",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def apply_tool(
    file_path: Optional[str] = Field(
        default=None, description="指定落地某文件；缺省落地全部暂存文件。"
    ),
):
    """把暂存区的 diff 预览正式写入磁盘。

    - 指定 file_path：仅落地该文件；缺省：落地全部暂存文件。
    - 落地后自动做语法校验，校验失败自动回滚该文件并返回错误。
    """
    store = staging.get_staging()
    pending = store.pending_items()
    if not pending:
        return "无待 apply 的暂存改动。"

    # 防御：缺省参数可能携带 FieldInfo，仅当真实字符串时才视为指定文件
    file_path = file_path if isinstance(file_path, str) else None
    target_resolved = _resolve_path(file_path) if file_path else None
    results: list[dict] = []
    applied_count = 0

    for path, new_content in pending.items():
        p = Path(path)
        if target_resolved is not None and p.resolve() != target_resolved:
            continue
        try:
            _resolve_path(p)
        except WorkspaceError:
            results.append({"file": str(p), "ok": False, "message": "超出工作区，跳过"})
            continue

        if not _write_text(p, new_content):
            results.append({"file": str(p), "ok": False, "message": "写入失败"})
            continue

        vres = syntax.validate_file_on_disk(p)
        if not vres["ok"]:
            _restore_previous(p)
            results.append(
                {
                    "file": str(p),
                    "ok": False,
                    "message": f"语法校验失败，已回滚: {vres['message']}",
                }
            )
            continue

        results.append({"file": str(p), "ok": True, "syntax": vres["status"]})
        applied_count += 1
        store.discard(p)

    return json.dumps(
        {"applied_results": results, "count": applied_count},
        ensure_ascii=False,
        indent=2,
    )


# --------------------------------------------------------------------------- #
# 工具 4：git_snapshot —— 修改前快照备份
# --------------------------------------------------------------------------- #
@mcp.tool(
    name="git_snapshot",
    annotations={
        "title": "创建 git 快照备份",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def git_snapshot_tool(
    file_path: Optional[str] = Field(
        default=None, description="对指定文件做快照；缺省对暂存区涉及的全部文件做快照。"
    ),
):
    """为文件/暂存区创建快照备份，出错后可一键回滚。

    - 记录原始内容到快照目录（默认 .local-edit-snapshots/）。
    - 支持 git 仓库跟踪检测；真正回滚按 manifest 精确还原。
    """
    try:
        # 防御：缺省参数可能携带 FieldInfo，仅当真实字符串时才视为指定文件
        file_path = file_path if isinstance(file_path, str) else None
        if file_path:
            p = _resolve_path(file_path)
            info = snapshot.make_snapshot(p)
        else:
            pending = staging.get_staging().pending_items()
            items = [snapshot.make_snapshot(Path(path)) for path in pending]
            info = {
                "ok": all(i.get("ok") for i in items),
                "snapshot_id": [i.get("snapshot_id") for i in items],
                "snapshot_file": [i.get("snapshot_file") for i in items],
                "count": len(items),
            }
        return json.dumps(info, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"Error: git_snapshot 失败: {e}"


# --------------------------------------------------------------------------- #
# 工具 5：validate_syntax —— 语法校验
# --------------------------------------------------------------------------- #
@mcp.tool(
    name="validate_syntax",
    annotations={
        "title": "校验文件语法（失败可触发回滚）",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def validate_syntax_tool(
    file_path: str = Field(..., description="要校验的文件路径（读取磁盘最新内容）。"),
):
    """对磁盘文件做语法校验（Python: ast.parse / JSON / YAML / JS 等）。"""
    try:
        p = _resolve_path(file_path)
        if not p.exists():
            return f"Error: 文件不存在 {p}"
        vres = syntax.validate_file_on_disk(p)
        return json.dumps(vres, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"Error: validate_syntax 失败: {e}"


# --------------------------------------------------------------------------- #
# 工具 6（辅助）：rollback —— 回滚到最近快照
# --------------------------------------------------------------------------- #
@mcp.tool(
    name="rollback",
    annotations={
        "title": "回滚到指定快照",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def rollback_tool(
    snapshot_id: Optional[str] = Field(
        default=None, description="回滚到指定快照 ID；缺省回滚到最近一次快照。"
    ),
):
    """根据快照 ID 将文件恢复到修改前（一键回滚）。"""
    try:
        # 防御：部分调用路径下缺省参数可能携带 FieldInfo 而非 None，仅当真实字符串时才视为指定 ID
        sid = snapshot_id if isinstance(snapshot_id, str) else None
        snap = _find_snapshot(sid)
        if snap is None:
            return "Error: 未找到可回滚的快照。"
        res = snapshot.restore_snapshot(snap["snapshot_file"], snap["target_file"])
        return json.dumps(res, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"Error: rollback 失败: {e}"


# --------------------------------------------------------------------------- #
# 内部工具函数
# --------------------------------------------------------------------------- #
def _resolve_path(raw: str | Path) -> Path:
    """规范化 + 工作区安全校验。"""
    from server import fs

    return fs.resolve_path(raw)


def _write_text(p: Path, content: str) -> bool:
    """安全写文件（先写临时再原子替换）。"""
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".local-edit-tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(p)
        return True
    except Exception:
        return False


def _write_content(p: Path, content: str) -> bool:
    return _write_text(p, content)


def _restore_previous(p: Path, _context: str) -> None:
    """将文件恢复到本次改动前的磁盘内容（回滚本次 apply 的写入）。"""
    record = snapshot.latest_snapshot_for(p)
    if record:
        snapshot.restore_snapshot(record["snapshot_file"], record["target_file"])


def _rollback_to_snapshot(p: Path, snapshot_info: dict | None) -> None:
    """回滚到指定快照；无有效快照时用最近快照兜底。"""
    snapshot_file = snapshot_info.get("snapshot_file") if snapshot_info else None
    if snapshot_file and Path(snapshot_file).exists():
        snapshot.restore_snapshot(snapshot_file, p)
        return
    record = snapshot.latest_snapshot_for(p)
    if record:
        snapshot.restore_snapshot(record["snapshot_file"], record["target_file"])


def _apply_mode() -> str:
    import os

    return os.environ.get(APPLY_MODE_ENV, "staged")


def _preview_lines(text: str, limit: int = 6) -> list:
    lines = text.splitlines()
    if len(lines) > limit:
        return lines[:limit] + [f"...(共 {len(lines)} 行)"]
    return lines


def _find_snapshot(snapshot_id: Optional[str]):
    """按快照 ID / 最近快照，从 manifest 精确解析出 (snapshot_file, target_file)。

    不再依赖从快照文件名反推目标路径（Windows 盘符/分隔符会造成偏差），
    直接使用 snapshot.all_snapshots() 基于 manifest 的可靠映射。
    """
    snaps = snapshot.all_snapshots()
    if not snaps:
        return None
    if snapshot_id:
        for r in snaps:
            if snapshot_id in r["snapshot_id"]:
                return r
        return None
    return snaps[0]


if __name__ == "__main__":
    import sys

    if "--http" in sys.argv:
        mcp.run(transport="streamable_http", port=8000)
    else:
        mcp.run()