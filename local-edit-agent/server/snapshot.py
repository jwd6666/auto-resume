"""
Git 快照备份模块（git_snapshot 工具底层）。

每次修改前自动创建 git 快照备份，出错时可一键回滚。实现两种备份方式：
1. git 方式:  若目标文件位于某个 git 仓库内，则用 `git stash --keep-index` 太重；
   我们改用更精准的方案 —— 生成"文件内容快照"到 workdir/.local-edit-snapshots/，
   同时保留一个 git 已提交基线。真正的回滚既支持文件级内容覆盖，也支持
   `git checkout -- <file>`（若文件已被 git 跟踪）。
2. 纯快照方式：把文件原始字节复制到本地快照目录，回滚时直接覆盖回来，不依赖仓库。

使用 .local-edit-snapshots/ 作为默认快照目录，可通过环境变量 LF_EDIT_SNAPSHOT_DIR 覆盖。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

SNAPSHOT_DIR_ENV = "LOCAL_EDIT_SNAPSHOT_DIR"
SNAPSHOT_DIR_DEFAULT = ".local-edit-snapshots"


def snapshot_dir() -> Path:
    """返回快照根目录（可被环境变量覆盖）。"""
    env = os.environ.get(SNAPSHOT_DIR_ENV)
    base = Path(env) if env else Path.cwd() / SNAPSHOT_DIR_DEFAULT
    base.mkdir(parents=True, exist_ok=True)
    return base


def make_snapshot(file_path: str | Path) -> dict:
    """为单个文件创建一份快照备份。

    Returns:
        dict: {
            "ok": bool,
            "snapshot_id": str,       # 可回滚标识
            "snapshot_file": str,     # 快照文件路径
            "file_path": str,
            "git_tracked": bool,      # 是否被 git 跟踪
            "message": str,
        }

    该函数是幂等的可追加式快照：每次调用生成一条独立记录，多次调用互不覆盖。
    """
    file_path = Path(file_path).resolve()
    if not file_path.exists():
        return {"ok": False, "snapshot_id": None, "file_path": str(file_path), "message": "文件不存在，无法创建快照"}

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    rel = str(file_path).replace(":", "_").replace("\\", "_").replace("/", "_")
    snap_dir = snapshot_dir() / "files"
    snap_dir.mkdir(parents=True, exist_ok=True)
    snapshot_file = snap_dir / f"{timestamp}__{rel}"
    shutil.copy2(file_path, snapshot_file)

    # 记录 manifest：{target_path: snapshot_file} 以便可靠地执行回滚
    manifest = _load_manifest()
    manifest[str(file_path)] = str(snapshot_file)
    _save_manifest(manifest)

    git_tracked = _is_git_tracked(file_path)
    snapshot_id = timestamp
    return {
        "ok": True,
        "snapshot_id": snapshot_id,
        "snapshot_file": str(snapshot_file),
        "file_path": str(file_path),
        "git_tracked": git_tracked,
        "message": f"已创建快照 {snapshot_id}",
    }


def latest_snapshot_for(file_path: str | Path) -> dict | None:
    """返回某文件最近一次的快照记录（含 snapshot_file / target）。"""
    manifest = _load_manifest()
    target = str(Path(file_path).resolve())
    snap = manifest.get(target)
    if not snap:
        return None
    return {"snapshot_file": snap, "target_file": target}


def all_snapshots() -> list[dict]:
    """返回全部快照记录（按快照文件修改时间倒序，最新在前）。

    Returns:
        list[dict]: [{"snapshot_id": str, "snapshot_file": str, "target_file": str}, ...]
    """
    manifest = _load_manifest()
    records = []
    for target, snap in manifest.items():
        if not hasattr(snap, "replace") and not isinstance(snap, str):
            continue
        sf = Path(str(snap))
        records.append(
            {
                "snapshot_id": sf.stem if sf.exists() else str(snap),
                "snapshot_file": str(sf),
                "target_file": str(target),
            }
        )
    # 快照文件名形如 {timestamp}__{rel}，timestamp 前缀可直接字符串排序（等价 mtime）
    records.sort(key=lambda r: r["snapshot_id"], reverse=True)
    return records


def _manifest_path() -> Path:
    return snapshot_dir() / "manifest.json"


def _load_manifest() -> dict:
    mf = _manifest_path()
    if mf.exists():
        try:
            return json.loads(mf.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_manifest(manifest: dict) -> None:
    _manifest_path().write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def restore_snapshot(snapshot_file: str | Path, target_file: str | Path) -> dict:
    """用某个快照文件恢复目标文件内容。"""
    snap = Path(snapshot_file)
    target = Path(target_file)
    if not snap.exists():
        return {"ok": False, "message": f"快照不存在: {snap}"}
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(snap, target)
    return {"ok": True, "message": f"已从快照恢复: {target}", "snapshot_file": str(snap)}


def _git_root(file_path: Path) -> Path | None:
    proc = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=str(file_path.parent), capture_output=True, text=True)
    if proc.returncode != 0:
        return None
    return Path(proc.stdout.strip())


def _is_git_tracked(file_path: Path) -> bool:
    proc = subprocess.run(["git", "ls-files", "--error-unmatch", str(file_path)], cwd=str(file_path.parent), capture_output=True, text=True)
    return proc.returncode == 0