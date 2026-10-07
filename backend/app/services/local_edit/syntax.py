"""
语法校验模块 — 扩展 HTML 校验。

替换完成后自动执行语法校验：
- Python:  ast.parse
- JSON:    json.loads
- YAML:    yaml.safe_load（若可用）
- JS/TS:   通过 node --check（若系统装有 node）
- HTML:    使用 html.parser 检查标签闭合
- 其它:     返回 SKIPPED（不阻塞）

若校验失败，调用方将触发回滚：把磁盘文件恢复为本次修改前的快照。
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
from pathlib import Path

_VOID_HTML_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}

# 可省略闭合标签的元素：HTML 规范允许不写结束标签（浏览器会自动隐式闭合），
# 校验时遇到它们不当作“未闭合”错误，避免大量误报。
# 注意：span / i / b / div 等属于必须闭合元素，不在此列。
_OPTIONAL_END_TAGS = {
    "p", "li", "dd", "dt", "option", "optgroup", "thead", "tbody", "tfoot",
    "tr", "td", "th", "rt", "rp", "colgroup", "caption",
    "html", "head", "body",
}


def validate_syntax(path: str | Path, content: str) -> dict:
    p = Path(path)
    lang = _detect_lang(p)
    if lang == "python":
        return _validate_python(content)
    if lang == "json":
        return _validate_json(content)
    if lang in ("yaml", "yml"):
        return _validate_yaml(content)
    if lang in ("js", "jsx", "ts", "tsx"):
        return _validate_js_ts(content, lang)
    if lang == "html":
        return _validate_html(content)
    return {"ok": True, "lang": lang, "status": "skipped", "message": f"未内置 {lang} 校验器，跳过语法检查。", "line": None, "error": None}


def _detect_lang(p: Path) -> str:
    ext = p.suffix.lstrip(".").lower()
    aliases = {
        "py": "python",
        "pyw": "python",
        "yml": "yaml",
        "mjs": "js",
        "cjs": "js",
        "htm": "html",
    }
    return aliases.get(ext, ext)


def _validate_python(content: str) -> dict:
    try:
        ast.parse(content, filename="<agent_edit>")
        return {"ok": True, "lang": "python", "status": "ok", "message": "Python 语法校验通过 (ast.parse)", "line": None, "error": None}
    except SyntaxError as e:
        return {
            "ok": False,
            "lang": "python",
            "status": "error",
            "message": f"Python 语法错误: {e.msg} (line {e.lineno}, col {e.offset})",
            "line": e.lineno,
            "error": str(e),
        }


def _validate_json(content: str) -> dict:
    try:
        json.loads(content)
        return {"ok": True, "lang": "json", "status": "ok", "message": "JSON 校验通过", "line": None, "error": None}
    except Exception as e:
        return {"ok": False, "lang": "json", "status": "error", "message": f"JSON 解析错误: {e}", "line": None, "error": str(e)}


def _validate_yaml(content: str) -> dict:
    try:
        import yaml
        yaml.safe_load(content)
        return {"ok": True, "lang": "yaml", "status": "ok", "message": "YAML 校验通过 (PyYAML)", "line": None, "error": None}
    except ImportError:
        return {"ok": True, "lang": "yaml", "status": "skipped", "message": "未安装 PyYAML，跳过 YAML 校验", "line": None, "error": None}
    except Exception as e:
        return {"ok": False, "lang": "yaml", "status": "error", "message": f"YAML 解析错误: {e}", "line": None, "error": str(e)}


def _validate_js_ts(content: str, lang: str) -> dict:
    try:
        if lang != "js":
            return {"ok": True, "lang": lang, "status": "skipped", "message": "TS/JSX 建议使用项目自身 linter 校验，此处跳过", "line": None, "error": None}
        with __import__("tempfile").NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
            f.write(content)
            tmp_name = f.name
        result = subprocess.run(["node", "--check", tmp_name], capture_output=True, text=True)
        Path(tmp_name).unlink(missing_ok=True)
        if result.returncode == 0:
            return {"ok": True, "lang": "js", "status": "ok", "message": "JS 语法校验通过 (node --check)", "line": None, "error": None}
        return {"ok": False, "lang": "js", "status": "error", "message": f"JS 语法错误: {result.stderr.strip()}", "line": None, "error": result.stderr.strip()}
    except FileNotFoundError:
        return {"ok": True, "lang": lang, "status": "skipped", "message": "未安装 Node.js，跳过 JS 语法校验", "line": None, "error": None}


def _validate_html(content: str) -> dict:
    """基于标准库 html.parser 的标签平衡校验。

    相较早期的严格栈逻辑，这里做了三点修正：
    - 空元素（br/img/hr/input/meta/link ...）与自闭合标签不压栈；
    - 属性值内的 '>'、<script>/<style> 原始文本由 html.parser 天然正确解析，不会误判；
    - 闭合标签采用“容错匹配”：向上查找最近同名开标签，两者之间尚未闭合的元素只允许是
    可隐式闭合的标签，否则报为交叉嵌套；并给出准确行号（不再恒为 None）。
    """
    from html.parser import HTMLParser

    class TagChecker(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.stack: list[tuple[str, int]] = []   # [(tag, line)]
            self.errors: list[tuple[str, int]] = []  # [(message, line)]

        def handle_starttag(self, tag, attrs):
            t = tag.lower()
            if t in _VOID_HTML_TAGS:
                return
            self.stack.append((t, self.getpos()[0]))

        def handle_startendtag(self, tag, attrs):
            # <x ... /> 自闭合：既不压栈也不弹出（覆盖默认的 start+end 行为，避免误配）
            return

        def handle_endtag(self, tag):
            t = tag.lower()
            if t in _VOID_HTML_TAGS:
                return
            close_line = self.getpos()[0]
            idx = None
            for i in range(len(self.stack) - 1, -1, -1):
                if self.stack[i][0] == t:
                    idx = i
                    break
            if idx is None:
                self.errors.append((f"多余的闭合标签 </{t}>（无对应开标签，约第 {close_line} 行）", close_line))
                return
            # idx 之上、尚未闭合的元素必须都是可隐式闭合的，否则为交叉嵌套/漏闭合
            for j in range(len(self.stack) - 1, idx, -1):
                etag, eline = self.stack[j]
                if etag not in _OPTIONAL_END_TAGS:
                    self.errors.append(
                        (f"标签未正确闭合：<{etag}>（约第 {eline} 行）在 </{t}> 之前缺少 </{etag}>", eline)
                    )
            del self.stack[idx:]  # 弹出匹配元素及其上方隐式闭合的元素

        def handle_data(self, data):
            pass

    try:
        checker = TagChecker()
        checker.feed(content)
        checker.close()
        # 文件结束时栈中仍存在的必须闭合元素 → 未闭合
        for etag, eline in checker.stack:
            if etag not in _OPTIONAL_END_TAGS:
                checker.errors.append((f"未闭合标签 <{etag}>（约第 {eline} 行）", eline))
        if checker.errors:
            first_msg, first_line = checker.errors[0]
            return {
                "ok": False,
                "lang": "html",
                "status": "error",
                "message": f"HTML 标签不平衡: {first_msg}",
                "line": first_line,
                "error": "; ".join(m for m, _ in checker.errors[:3]),
            }
        return {"ok": True, "lang": "html", "status": "ok", "message": "HTML 标签闭合校验通过", "line": None, "error": None}
    except Exception as e:
        return {"ok": False, "lang": "html", "status": "error", "message": f"HTML 解析异常: {e}", "line": None, "error": str(e)}


def validate_file_on_disk(path: str | Path) -> dict:
    content = Path(path).read_text(encoding="utf-8", errors="replace")
    return validate_syntax(path, content)
