"""
Unified Diff 生成模块。

str_replace 计算出替换范围后，生成 unified diff 供前端做"红绿预览"。
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
    return "".join(diff_lines)


def build_inline_preview(
    old_content: str,
    new_content: str,
    match_start: int,
    match_end: int,
) -> dict:
    before = old_content[match_start:match_end]
    return {
        "before": before,
        "after": _extract_after(old_content, new_content, match_start, match_end),
        "line_range_before": _locate_lines(old_content, match_start, match_end),
    }


def _extract_after(old_content, new_content, start, end):
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    sm = difflib.SequenceMatcher(None, old_lines, new_lines)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "replace" and i1 <= 0 and i2 >= len(old_lines):
            after = "".join(new_lines[j1:j2])
            if after:
                return after
    return new_content[start:start + (end - start)]


def _locate_lines(content: str, start: int, end: int) -> tuple[int, int]:
    start_line = content.count("\n", 0, start) + 1
    end_line = content.count("\n", 0, end) + 1
    return start_line, end_line
