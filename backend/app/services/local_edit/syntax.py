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
    """使用 html.parser 检查 HTML 标签闭合与严重语法问题。"""
    from html.parser import HTMLParser

    class TagChecker(HTMLParser):
        def __init__(self):
            super().__init__()
            self.errors: list[str] = []
            self.stack: list[tuple[str, int]] = []
            self._line_map: list[int] = []

        def handle_starttag(self, tag, attrs):
            if tag.lower() not in _VOID_HTML_TAGS:
                line_approx = self.getpos()[0] if self.getpos() else 0
                self.stack.append((tag.lower(), line_approx))

        def handle_endtag(self, tag):
            tag = tag.lower()
            if tag in _VOID_HTML_TAGS:
                return
            if self.stack and self.stack[-1][0] == tag:
                self.stack.pop()
            elif self.stack:
                open_tag, line = self.stack[-1]
                self.errors.append(f"未匹配的闭合标签 </{tag}>，期望 </{open_tag}>（约第 {line} 行）")
            else:
                self.errors.append(f"未匹配的闭合标签 </{tag}>（无对应开标签）")

        def handle_data(self, data):
            pass

    try:
        checker = TagChecker()
        checker.feed(content)
        if checker.errors:
            first_error = checker.errors[0]
            return {
                "ok": False,
                "lang": "html",
                "status": "error",
                "message": f"HTML 标签不平衡: {first_error}",
                "line": None,
                "error": "; ".join(checker.errors[:3]),
            }
        if checker.stack:
            unclosed = [f"<{tag}>（约第 {line} 行）" for tag, line in checker.stack[:5]]
            return {
                "ok": False,
                "lang": "html",
                "status": "error",
                "message": f"HTML 存在未闭合标签: {', '.join(unclosed)}",
                "line": checker.stack[0][1] if checker.stack else None,
                "error": f"未闭合: {', '.join(unclosed)}",
            }
        return {"ok": True, "lang": "html", "status": "ok", "message": "HTML 标签闭合校验通过", "line": None, "error": None}
    except Exception as e:
        return {"ok": False, "lang": "html", "status": "error", "message": f"HTML 解析异常: {e}", "line": None, "error": str(e)}


def validate_file_on_disk(path: str | Path) -> dict:
    content = Path(path).read_text(encoding="utf-8", errors="replace")
    return validate_syntax(path, content)
