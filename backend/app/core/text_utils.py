"""通用文本工具：清洗模型输出、去除代码围栏、提取内容片段。"""
from __future__ import annotations

import re


def strip_code_fence(s: str, json_mode: bool = False) -> str:
    """去除模型输出中的 Markdown 代码围栏，并尽量提取干净的 HTML/JSON 片段。"""
    s = (s or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:html|json|xml)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*```\s*$", "", s)
    s = s.strip()
    if json_mode:
        json_start = s.find("{")
        if json_start > 0:
            s = s[json_start:]
        json_end = s.rfind("}")
        if json_end >= 0 and json_end < len(s) - 1:
            s = s[:json_end + 1]
        return s.strip()
    doctype_pos = s.lower().find("<!doctype")
    html_pos = s.lower().find("<html")
    if doctype_pos >= 0 or html_pos >= 0:
        start = doctype_pos if doctype_pos >= 0 else html_pos
        if html_pos >= 0 and html_pos < start:
            start = html_pos
        s = s[start:]
    close_pos = s.lower().rfind("</html>")
    if close_pos >= 0:
        s = s[:close_pos + len("</html>")]
    return s.strip()