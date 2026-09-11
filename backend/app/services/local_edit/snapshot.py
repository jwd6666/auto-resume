"""
快照备份模块 — 按「回合(round)」建档的多级快照。

设计（用户确认的重写目标）：
- 每回合（一次用户输入 + 该轮 AI 的所有工具写入）只在回合开始时 push 一个「回合快照」，
  记录该回合 AI 开始修改之前的文件状态。用户可借 UI 上的回退按钮一键恢复到该回合之前。
- 仅保留「最近 MAX_ROUNDS=10 个」回合快照，超出的最旧回合快照会被清理。
  同时仍保留按时间(max_age_days=7)过期清理。
- 工具级写入（patch_file / write_file）使用独立的「瞬态安全快照」：
  写入前压入，写完若语法校验失败弹栈回滚当前失败写；成功后丢弃，不污染回合计数。
- 只记录 AI 工具操作产生的变更，手动改的文件不会被快照保存。

磁盘结构 {resume_dir}/.snapshots/ ：
- files/                 快照文件副本目录
- manifest.json          回合快照栈（栈式数组，最新在末尾，round_id 从 1 递增计数）
- safety.json            瞬态安全快照（只保留最近 1 层，用于语法回滚）
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

# 保留的最近回合快照上限（与 TRAE 官方的「最近 10 轮」一致）
MAX_ROUNDS = 10
# 按天过期清理
MAX_AGE_DAYS = 7


def _snapshot_dir(resume_id: int) -> Path:
    from ...services.resume_workspace import resume_dir
    d = resume_dir(resume_id) / ".snapshots"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _files_dir(resume_id: int) -> Path:
    d = _snapshot_dir(resume_id) / "files"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# 通用底层工具
# ---------------------------------------------------------------------------
def _copy_to_snapshot(file_path: Path, resume_id: int) -> tuple[str, str]:
    """复制文件到 files/ 目录，返回 (快照文件绝对路径, snapshot_id)。"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    rel = str(file_path).replace(":", "_").replace("\\", "_").replace("/", "_")
    snapshot_file = _files_dir(resume_id) / f"{timestamp}__{rel}"
    shutil.copy2(file_path, snapshot_file)
    return str(snapshot_file), timestamp


def _is_git_tracked(file_path: Path) -> bool:
    try:
        proc = subprocess.run(["git", "ls-files", "--error-unmatch", str(file_path)],
                              cwd=str(file_path.parent), capture_output=True, text=True)
        return proc.returncode == 0
    except (FileNotFoundError, Exception):
        return False


def _restore(entry: dict, resume_id: int) -> dict:
    snap = Path(entry["snapshot_file"])
    target = Path(entry["target_file"])
    if not snap.exists():
        return {"ok": False, "message": f"快照不存在: {snap}"}
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(snap, target)
    return {"ok": True, "message": f"已从快照恢复: {target}", "snapshot_file": str(snap)}


# ---------------------------------------------------------------------------
# 回合快照（用户可见回退栈）
# ---------------------------------------------------------------------------
def _round_manifest_path(resume_id: int) -> Path:
    return _snapshot_dir(resume_id) / "manifest.json"


def _load_round_manifest(resume_id: int) -> list[dict]:
    mf = _round_manifest_path(resume_id)
    if mf.exists():
        try:
            data = json.loads(mf.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return []


def _save_round_manifest(manifest: list[dict], resume_id: int) -> None:
    _round_manifest_path(resume_id).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def round_count(resume_id: int = 0) -> int:
    """当前回合快照数量（1 起）。"""
    return len(_load_round_manifest(resume_id))


# 兼容旧名（前端/接口仍用 stack_depth）
def stack_depth(resume_id: int = 0) -> int:
    return round_count(resume_id)


def make_snapshot(file_path: str | Path, resume_id: int = 0) -> dict:
    """【回合快照】对话回合开始时压入 1 层。创建前先按规则清理超限/过期快照。"""
    file_path = Path(file_path).resolve()
    if not file_path.exists():
        return {"ok": False, "snapshot_id": None, "file_path": str(file_path), "message": "文件不存在，无法创建快照"}

    manifest = _load_round_manifest(resume_id)

    # 去重：若栈顶快照内容与当前文件一致（回合内已被 push 过，如重入/同回合二次调用），不再 push
    if manifest:
        top = manifest[-1]
        top_file = Path(top["snapshot_file"])
        if top_file.exists() and top_file.read_bytes() == file_path.read_bytes():
            return {
                "ok": True,
                "snapshot_id": top["snapshot_id"],
                "snapshot_file": top["snapshot_file"],
                "file_path": str(file_path),
                "git_tracked": _is_git_tracked(file_path),
                "message": f"已存在本回合快照 {top['snapshot_id']}，跳过重复压栈",
                "stack_depth": len(manifest),
            }

    snapshot_file, snapshot_id = _copy_to_snapshot(file_path, resume_id)
    entry = {
        "snapshot_file": snapshot_file,
        "target_file": str(file_path),
        "snapshot_id": snapshot_id,
        "timestamp": snapshot_id,
        "kind": "round",
    }
    manifest.append(entry)
    _save_round_manifest(manifest, resume_id)

    cleanup = clean_old_snapshots(resume_id, max_age_days=MAX_AGE_DAYS)
    return {
        "ok": True,
        "snapshot_id": snapshot_id,
        "snapshot_file": snapshot_file,
        "file_path": str(file_path),
        "git_tracked": _is_git_tracked(file_path),
        "message": f"已创建回合快照 {snapshot_id}",
        "stack_depth": len(manifest),
        "cleaned": cleanup,
    }


def pop_snapshot(resume_id: int = 0) -> dict | None:
    """弹出栈顶回合快照。"""
    manifest = _load_round_manifest(resume_id)
    if not manifest:
        return None
    entry = manifest.pop()
    _save_round_manifest(manifest, resume_id)
    return entry


def peek_top(resume_id: int = 0) -> dict | None:
    manifest = _load_round_manifest(resume_id)
    return manifest[-1] if manifest else None


def peek_bottom(resume_id: int = 0) -> dict | None:
    manifest = _load_round_manifest(resume_id)
    return manifest[0] if manifest else None


def all_snapshots(resume_id: int = 0) -> list[dict]:
    return list(_load_round_manifest(resume_id))


def restore_from_entry(entry: dict, resume_id: int = 0) -> dict:
    return _restore(entry, resume_id)


def restore_snapshot(snapshot_file: str | Path, target_file: str | Path, resume_id: int = 0) -> dict:
    return _restore({"snapshot_file": str(snapshot_file), "target_file": str(target_file)}, resume_id)


def latest_snapshot_for(file_path: str | Path, resume_id: int = 0) -> dict | None:
    return peek_top(resume_id)


def rollback_to_round(resume_id: int, target_depth: int) -> dict:
    """回滚到第 target_depth 回合「开始前」的文件状态，并丢弃该回合及其后所有回合快照。

    语义（round / snapshot_depth 从 1 计）：
      - manifest[i] 保存的是第 (i+1) 回合开始前的文件状态；
      - 回退到「第 k 回合之前」 = 用 manifest[k-1] 恢复文件，栈仅保留 entries[0..k-2]。
      - target_depth <= 0：恢复到对话起点（manifest[0]）并清空整栈。
    这样「回退最近一轮」(k == 当前回合数) 也能正常生效，而非被空拦截。
    """
    manifest = _load_round_manifest(resume_id)
    c = len(manifest)
    if c == 0:
        return {"ok": True, "message": "快照栈为空，无法回滚", "popped": 0, "current_depth": 0}

    if target_depth <= 0:
        keep_count = 0
        restore_entry = manifest[0]           # 回到对话起点
    else:
        k = min(c, int(target_depth))         # 目标回合号（1 起）
        restore_entry = manifest[k - 1]       # 该回合开始前
        keep_count = k - 1

    _restore(restore_entry, resume_id)

    # 丢弃被删除的回合快照文件
    for e in manifest[keep_count:]:
        Path(e["snapshot_file"]).unlink(missing_ok=True)

    kept = manifest[:keep_count]
    _save_round_manifest(kept, resume_id)
    popped = c - keep_count
    return {
        "ok": True,
        "message": f"已回滚 {popped} 步",
        "popped": popped,
        "current_depth": len(kept),
    }


def clear_stack(resume_id: int = 0) -> int:
    manifest = _load_round_manifest(resume_id)
    count = len(manifest)
    _save_round_manifest([], resume_id)
    return count


def clean_old_snapshots(resume_id: int, max_age_days: int = MAX_AGE_DAYS) -> int:
    """按时间过期清理 + 按回合数量上限(MAX_ROUNDS)截断最旧快照。返回清理数量。"""
    manifest = _load_round_manifest(resume_id)
    now = time.time()
    cutoff = now - max_age_days * 86400
    removed = 0

    kept = []
    for entry in manifest:
        snap = Path(entry["snapshot_file"])
        if not snap.exists():
            removed += 1
            continue
        # 尝试用时间戳判断是否已过期
        stale = False
        try:
            stale = snap.stat().st_mtime < cutoff
        except OSError:
            stale = False
        if stale:
            snap.unlink(missing_ok=True)
            removed += 1
        else:
            kept.append(entry)

    # 按回合上限截断最旧的
    if len(kept) > MAX_ROUNDS:
        excess = kept[:-MAX_ROUNDS]
        kept = kept[-MAX_ROUNDS:]
        for entry in excess:
            Path(entry["snapshot_file"]).unlink(missing_ok=True)
            removed += 1

    if removed:
        _save_round_manifest(kept, resume_id)
    return removed


# ---------------------------------------------------------------------------
# 瞬态安全快照（工具写入，用于 HTML 语法校验失败即时回滚）
# ---------------------------------------------------------------------------
def _safety_manifest_path(resume_id: int) -> Path:
    return _snapshot_dir(resume_id) / "safety.json"


def _load_safety_manifest(resume_id: int) -> list[dict]:
    mf = _safety_manifest_path(resume_id)
    if mf.exists():
        try:
            data = json.loads(mf.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return []


def _save_safety_manifest(manifest: list[dict], resume_id: int) -> None:
    _safety_manifest_path(resume_id).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def push_safety_snapshot(file_path: str | Path, resume_id: int = 0) -> dict | None:
    """写文件前压入瞬态安全快照。仅保留最近 1 层，写入成功后调用 release_safety() 丢弃。"""
    file_path = Path(file_path).resolve()
    if not file_path.exists():
        return None
    snapshot_file, snapshot = _copy_to_snapshot(file_path, resume_id)
    entry = {
        "snapshot_file": snapshot_file,
        "target_file": str(file_path),
        "snapshot_id": snapshot,
        "timestamp": snapshot,
        "kind": "safety",
    }
    _save_safety_manifest([entry], resume_id)
    # 清理该 resume 可能残留的旧 safety 快照文件（覆盖模式）
    return entry


def pop_safety_snapshot(resume_id: int = 0) -> dict | None:
    """弹出瞬态安全快照并返回。用于语法校验失败时回滚。"""
    manifest = _load_safety_manifest(resume_id)
    if not manifest:
        return None
    entry = manifest.pop()
    _save_safety_manifest(manifest, resume_id)
    return entry


def discard_safety_snapshot(resume_id: int = 0) -> None:
    """写成功后丢弃瞬态安全快照（不执行回滚）。"""
    manifest = _load_safety_manifest(resume_id)
    if manifest:
        Path(manifest[-1]["snapshot_file"]).unlink(missing_ok=True)
    _save_safety_manifest([], resume_id)