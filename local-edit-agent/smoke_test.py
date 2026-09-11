"""End-to-end smoke test for local-edit-agent core workflow.

Tests:
1. hashing: compute/verify md5 optimistic lock, mismatch raises.
2. matcher: exact unique match, ambiguity (multi-hit) rejection, fuzzy fallback.
3. differ: unified diff contains +/- lines.
4. syntax: ast.parse pass & fail.
5. Full flow via MCP tool functions: view -> str_replace (staged) -> apply.
"""
import asyncio
import json
import os
import tempfile
from pathlib import Path

WORKSPACE = tempfile.mkdtemp(prefix="local-edit-test-")
os.environ["LOCAL_EDIT_WORKSPACE"] = WORKSPACE
os.environ["LOCAL_EDIT_APPLY_MODE"] = "staged"

from server import hashing, matcher, differ, syntax, snapshot  # noqa
from server.hashing import HashMismatchError  # noqa
from server.matcher import MatchError  # noqa
import server

# import local_edit_server as a module (entry point script)
import importlib.util
import sys

_spec = importlib.util.spec_from_file_location("local_edit_server", "local_edit_server.py")
_les = importlib.util.module_from_spec(_spec)
sys.modules["local_edit_server"] = _les
_spec.loader.exec_module(_les)

view_tool = _les.view_tool
str_replace_tool = _les.str_replace_tool
apply_tool = _les.apply_tool

SAMPLE = """line1 = \"a\"
# 目标行将被替换
SVG_ICON = \"fa-circle\"   # TODO: 换成 bootstrap icon
line4 = \"b\"
"""

TARGET = Path(WORKSPACE) / "demo.py"


def test_hashing():
    TARGET.write_text(SAMPLE, encoding="utf-8")
    h = hashing.compute_hash(TARGET)
    assert len(h) == 32
    # 匹配成功
    hashing.verify_hash(TARGET, h)
    # 磁盘被改，校验失败
    TARGET.write_text(SAMPLE + "# changed\n", encoding="utf-8")
    try:
        hashing.verify_hash(TARGET, h)
        raise AssertionError("应抛出 HashMismatchError")
    except HashMismatchError:
        pass
    # 还原
    TARGET.write_text(SAMPLE, encoding="utf-8")
    print("[OK] hashing / 乐观锁")


def test_matcher_exact_and_ambiguity():
    content = "a\nb\na\n"
    # 唯一精确
    r = matcher.match_once(content, "b")
    assert r.matched_exact and content[r.start:r.end] == "b"
    # 歧义（两处 a）
    try:
        matcher.match_once("a\nb\na\n", "a")
        raise AssertionError("应拒绝歧义")
    except MatchError as e:
        assert len(e.hits) == 2
    # 不在文件中
    try:
        matcher.match_once("hello world", "zzz")
        raise AssertionError("应找不到")
    except MatchError:
        pass
    print("[OK] matcher 精确/歧义/未命中")


def test_fuzzy():
    # 空白符/缩进差异，应通过模糊匹配命中恰好一处
    content = "def f():\n    x = 1\n    y = 2\n    z = 3\n"
    # old_str 缩进与真实内容不一致（用了 2 空格而非 4），走 difflib 降级
    needle = "  y = 2\n  z = 3"
    res = matcher.match_once(content, needle)
    assert not res.matched_exact
    assert content[res.start:res.end]
    print("[OK] matcher 模糊降级命中一次, similarity=%.3f" % res.similarity)


def test_diff():
    old = "a\nb\nc\n"
    new = "a\nB\nc\n"
    d = differ.build_unified_diff("demo.py", old, new)
    # difflib 每行带前缀 + 内容，匹配行开头有 '-'/'+' 前缀
    assert any(l.startswith("-b") for l in d.splitlines()), d
    assert any(l.startswith("+B") for l in d.splitlines()), d
    print("[OK] differ unified-diff")


def test_syntax():
    ok = syntax.validate_syntax("f.py", "x = 1\n")
    assert ok["ok"]
    bad = syntax.validate_syntax("f.py", "def f(:\n")
    assert not bad["ok"]
    print("[OK] syntax py ast.parse")


async def test_snapshot_rollback_and_default_args():
    """覆盖缺省参数(FastMCP FieldInfo)防御、git_snapshot、rollback 缺省回滚。"""
    f = Path(WORKSPACE) / "rollback.py"
    f.write_text("X=1\nY=2\nZ=3\n", encoding="utf-8")

    # git_snapshot 缺省（无暂存区）也应正常返回 JSON
    snap0 = await _les.git_snapshot_tool()
    assert "count" in json.loads(snap0), snap0

    snap = json.loads(await _les.git_snapshot_tool(file_path=str(f)))
    assert snap["ok"]

    # 乐观锁：外部改文件后，用旧 hash 修改应被拦截
    v = json.loads(await _les.view_tool(file_path=str(f)))
    md5 = v["file_md5"]
    f.write_text("X=99\nY=2\nZ=3\n", encoding="utf-8")
    blocked = await _les.str_replace_tool(
        file_path=str(f), old_str="Y=2", new_str="Y=22", expected_hash=md5
    )
    assert "HashMismatch" in blocked

    # rollback 缺省：恢复到最近快照
    rb = json.loads(await _les.rollback_tool())
    assert rb["ok"]
    assert "X=1" in f.read_text(encoding="utf-8")
    print("[OK] git_snapshot + 缺省参数防御 + rollback 回滚")


async def test_full_tool_flow():
    TARGET.write_text(SAMPLE, encoding="utf-8")

    # 1) view
    v = json.loads(
        await view_tool(file_path=str(TARGET), start_line=1, end_line=5)
    )
    file_md5 = v["file_md5"]
    print("[view] md5=%s lines=%d" % (file_md5[:8], v["end_line"]))

    # 2) str_replace staged（old_str 带锚定上下文）
    old_str = 'SVG_ICON = "fa-circle"'
    new_str = 'SVG_ICON = "bi-circle-fill"'
    res = json.loads(
        await str_replace_tool(
            file_path=str(TARGET),
            old_str=old_str,
            new_str=new_str,
            expected_hash=file_md5,
        )
    )
    assert res["status"] == "staged", res
    assert "unified_diff" in res
    assert "bi-circle-fill" in res["unified_diff"]
    print("[OK] str_replace staged + diff: status=%s" % res["status"])

    # 磁盘上仍应是旧内容（未落地）
    assert old_str in TARGET.read_text(encoding="utf-8")

    # 3) apply 落地
    app = json.loads(await apply_tool(file_path=str(TARGET)))
    assert app["count"] == 1, app
    assert new_str in TARGET.read_text(encoding="utf-8")
    assert old_str not in TARGET.read_text(encoding="utf-8")
    print("[OK] apply 落地成功")


async def run():
    test_hashing()
    test_matcher_exact_and_ambiguity()
    test_fuzzy()
    test_diff()
    test_syntax()
    await test_snapshot_rollback_and_default_args()
    await test_full_tool_flow()


if __name__ == "__main__":
    asyncio.run(run())
    print("\nALL SMOKE TESTS PASSED")