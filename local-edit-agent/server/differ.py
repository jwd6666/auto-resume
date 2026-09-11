"""
Unified Diff 生成模块。

str_replace 计算出替换范围并执行内存替换后，不直接覆盖磁盘文件，而是生成 unified diff
供前端做"红绿预览"（绿色=新增行，红色=删除行）。用户点击 Apply 后才落地写入。

统一使用 difflib.unified_diff 输出标准格式，便于前端 diff 高亮组件直接解析。
"""
from __future__ import annotations

import difflib
from pathlib import Path


def build_unified_diff(
    file_path: str | Path,
    old_content: str,
    new_content: str,
    context: int = 3,
) -> str:
    """生成 old_content -> new_content 的 unified diff 文本。

    Args:
        file_path: 用于 diff 头中展示的文件路径。
        old_content: 修改前的完整文件内容。
        new_content: 修改后的完整文件内容。
        context: 上下行数。

    Returns:
        str: unified diff 全文（标准 hunk 格式）。
    """
    path = str(file_path).replace("\\", "/")
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)

    diff_lines = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="\n",
            n=context,
        )
    )
    # difflib 默认给每个差异行追加 "\n"，若原本没有换行的需保持一致
    return "".join(diff_lines)


def build_inline_preview(
    old_content: str,
    new_content: str,
    match_start: int,
    match_end: int,
) -> dict:
    """生成针对单段替换的紧凑预览，供前端绘制红绿高亮。

    Returns:
        dict: {
            "before": 被替换的旧文本,
            "after":   替换后的新文本,
            "line_range_before": [start_line, end_line]（旧文件中的行范围, 1 基）,
        }
    """
    before = old_content[match_start:match_end]
    after_length = len(new_content) - (len(old_content) - (match_end - match_start))
    # 构造 new_content 中对应的 after 范围（按比例定位并不精确，更稳妥的方案见 replace_once）
    return {
        "before": before,
        "after": _extract_after(old_content, new_content, match_start, match_end),
        "line_range_before": _locate_lines(old_content, match_start, match_end),
    }


def _extract_after(old_content, new_content, start, end):
    """使用 difflib 从全文比对的 hunk 中提取 after 文本。"""
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    sm = difflib.SequenceMatcher(None, old_lines, new_lines)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "replace" and i1 <= 0 and i2 >= len(old_lines):
            after = "".join(new_lines[j1:j2])
            if after:
                return after
    # 兜底：整体取差异的新内容片段
    return new_content[start:start + (end - start)]


def _locate_lines(content: str, start: int, end: int) -> tuple[int, int]:
    """根据字符下标计算 1-based 起止行号。"""
    start_line = content.count("\n", 0, start) + 1
    end_line = content.count("\n", 0, end) + 1
    return start_line, end_line