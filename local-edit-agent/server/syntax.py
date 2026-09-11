"""
语法校验模块（validate_syntax 工具底层）。

替换完成后自动执行语法校验：
- Python:  使用 ast.parse
- JSON:    使用 json.loads
- YAML:    使用 yaml.safe_load（若可用）
- JS/TS:   通过 node --check（若系统装有 node）
- 其它:     返回 SKIPPED（不阻塞）

若校验失败，调用方将触发回滚：把磁盘文件恢复为本次修改前的快照，保证绝不留下残缺代码。
"""
from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path


def validate_syntax(path: str | Path, content: str) -> dict:
    """单元格校验一段文本的语法。

    Returns:
        dict: {
            "ok": bool,
            "lang": str,             # 侦测到的语言
            "status": "ok" | "error" | "skipped",
            "message": str,          # 成功/跳过 说明或错误详情
            "line": int | None,      # 出错行号（若有）
            "error_type": str | None,
        }
    """
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
    return {"ok": True, "lang": lang, "status": "skipped", "message": f"未内置 {lang} 校验器，跳过语法检查。", "line": None, "error": None}


def _detect_lang(p: Path) -> str:
    ext = p.suffix.lstrip(".").lower()
    aliases = {
        "py": "python",
        "pyw": "python",
        "yml": "yaml",
        "mjs": "js",
        "cjs": "js",
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
        import yaml  # type: ignore

        yaml.safe_load(content)
        return {"ok": True, "lang": "yaml", "status": "ok", "message": "YAML 校验通过 (PyYAML)", "line": None, "error": None}
    except ImportError:
        return {"ok": True, "lang": "yaml", "status": "skipped", "message": "未安装 PyYAML，跳过 YAML 校验", "line": None, "error": None}
    except Exception as e:
        return {"ok": False, "lang": "yaml", "status": "error", "message": f"YAML 解析错误: {e}", "line": None, "error": str(e)}


def _validate_js_ts(content: str, lang: str) -> dict:
    """使用 node --check 校验 JS；TS 通过 esbuild/tsc 不可用时退回跳过。"""
    try:
        tmp = Path.cwd() / f"._validate_{Path(content).name}.tmp" if False else None
        # TS 校验需要类型信息，较复杂，这里仅对 .js 做 node --check
        if lang != "js":
            return {"ok": True, "lang": lang, "status": "skipped", "message": "TS/JSX 建议使用项目自身 linter 校验，此处跳过", "line": None, "error": None}
        with __import__("tempfile").NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
            f.write(content)
            tmp_name = f.name
        result = subprocess.run(["node", "--check", tmp_name], capture_output=True, text=True)
        # 清理临时文件
        Path(tmp_name).unlink(missing_ok=True)
        if result.returncode == 0:
            return {"ok": True, "lang": "js", "status": "ok", "message": "JS 语法校验通过 (node --check)", "line": None, "error": None}
        return {"ok": False, "lang": "js", "status": "error", "message": f"JS 语法错误: {result.stderr.strip()}", "line": None, "error": result.stderr.strip()}
    except FileNotFoundError:
        return {"ok": True, "lang": lang, "status": "skipped", "message": "未安装 Node.js，跳过 JS 语法校验", "line": None, "error": None}


def validate_file_on_disk(path: str | Path) -> dict:
    """读取磁盘上的文件并校验（供 str_replace 落地前使用）。"""
    content = Path(path).read_text(encoding="utf-8", errors="replace")
    return validate_syntax(path, content)