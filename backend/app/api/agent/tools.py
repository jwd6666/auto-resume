from __future__ import annotations

import json
import re
from typing import Optional

from ...services.resume_workspace import (
    read_resume_file, write_resume_file, resume_file_path,
)
from ...services.local_edit import matcher, hashing, snapshot, syntax, differ, staging
from ...services.local_edit.hashing import HashMismatchError
from ...services.local_edit.matcher import MatchError
from ...services.local_edit.staging import get_staging, clear_staging
from ...schemas import resume_models as models


_FULL_FLAG: dict = {}

_FILE_MD5_CACHE: dict = {}


def reset_full_read_state(resume_id) -> None:
    if resume_id is not None:
        _FULL_FLAG.pop(int(resume_id), None)
        _FILE_MD5_CACHE.pop(int(resume_id), None)
        clear_staging(int(resume_id))


def _mark_full_read(resume_id) -> None:
    if resume_id is not None:
        _FULL_FLAG[int(resume_id)] = True


def _has_full_read(resume_id) -> bool:
    if resume_id is None:
        return True
    try:
        return bool(_FULL_FLAG.get(int(resume_id)))
    except (TypeError, ValueError):
        return True


def _cache_file_md5(resume_id: int, md5: str) -> None:
    _FILE_MD5_CACHE[int(resume_id)] = md5


def _get_cached_md5(resume_id: int) -> Optional[str]:
    return _FILE_MD5_CACHE.get(int(resume_id))


RESUME_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取简历 HTML 文件。默认读取完整内容；可传 section_id 只读取指定 section（更省 token）。section_id 对应 HTML 中 data-resume-section 属性值（如 'basics','edu','skill','project','summary' 等）。读取时系统自动校验文件指纹（乐观锁），确保后续修改基于最新内容。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件路径（由系统提供）",
                    },
                    "section_id": {
                        "type": "string",
                        "description": "可选。只读取此 data-resume-section 对应的 section HTML 片段，不传则读取全文。",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "patch_file",
            "description": "精确字符串替换修改简历 HTML（str_replace 机制，含三级降级匹配+乐观锁+自动快照回滚）。先用 read_file 查看原文，把要修改的原文片段逐字符复制为 old_str，修改后的片段作为 new_str 传入。匹配策略：精确匹配→空白符标准化→difflib 滑动窗相似度降级，命中恰好一处才执行。修改前自动将当前版本压入快照栈，若修改导致 HTML 语法错误会自动弹栈回滚。每次只改一小块，多处修改分多次调用。new_str 传空字符串表示删除 old_str。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件路径（由系统提供）",
                    },
                    "old_str": {
                        "type": "string",
                        "description": "要被替换的原文片段，必须从 read_file 结果中逐字符精确复制",
                    },
                    "new_str": {
                        "type": "string",
                        "description": "替换后的片段；传空字符串表示删除 old_str",
                    },
                },
                "required": ["path", "old_str", "new_str"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "将完整内容写入简历 HTML 文件（全量覆写，含乐观锁+自动快照回滚）。仅在需要大范围重写简历（如更换模板、重排版）时使用，且必须先 read_file 读取全文。写入前自动将当前版本压入快照栈，若写入内容有 HTML 语法错误会自动弹栈回滚。写入后前端会自动刷新预览。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件路径（由系统提供）",
                    },
                    "content": {
                        "type": "string",
                        "description": "要写入的完整 HTML 内容",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
]


def _list_sections(html: str) -> str:
    matches = re.findall(r'data-resume-section\s*=\s*["\']?([^"\'>\s]+)["\']?', html, re.IGNORECASE)
    if not matches:
        return "(未找到任何 data-resume-section 属性，请使用 read_file 读取全文)"
    return "\n".join(f"  - {m}" for m in matches)


def _read_section(html: str, section_id: str) -> str:
    pattern = re.compile(
        rf'<[^>]+data-resume-section\s*=\s*["\']?{re.escape(section_id)}["\']?[^>]*>.*?</(?:section|div|header|article)>',
        re.DOTALL | re.IGNORECASE,
    )
    match = pattern.search(html)
    if match:
        return match.group(0)
    pattern_loose = re.compile(
        rf'<[^>]+data-resume-section\s*=\s*["\']?{re.escape(section_id)}["\']?[^>]*>',
        re.IGNORECASE,
    )
    match2 = pattern_loose.search(html)
    if match2:
        start = match2.start()
        tag_name = match2.group(0).lstrip('<').split()[0].rstrip('>')
        close_tag = f"</{tag_name}>"
        close_pos = html.find(close_tag, start + len(match2.group(0)))
        if close_pos != -1:
            return html[start:close_pos + len(close_tag)]
    return ""


def _patch_section(html: str, section_id: str, new_html: str) -> str:
    pattern = re.compile(
        rf'(<[^>]+data-resume-section\s*=\s*["\']?{re.escape(section_id)}["\']?[^>]*>).*?(</(?:section|div|header|article)>)',
        re.DOTALL | re.IGNORECASE,
    )
    match = pattern.search(html)
    if match:
        opening_tag = match.group(1)
        closing_tag = match.group(2)
        new_section = new_html
        if not new_section.strip().startswith("<"):
            new_section = opening_tag + new_html + closing_tag
        return html[:match.start()] + new_section + html[match.end():]
    pattern_loose = re.compile(
        rf'(<[^>]+data-resume-section\s*=\s*["\']?{re.escape(section_id)}["\']?[^>]*>)',
        re.IGNORECASE,
    )
    match2 = pattern_loose.search(html)
    if match2:
        start = match2.start()
        tag_name = match2.group(0).lstrip('<').split()[0].rstrip('>')
        close_tag = f"</{tag_name}>"
        close_pos = html.find(close_tag, start + len(match2.group(0)))
        if close_pos != -1:
            return html[:start] + new_html + html[close_pos + len(close_tag):]
    return ""


_VOID_TAGS = {"br", "hr", "img", "input", "meta", "link", "area", "base", "col",
              "embed", "source", "track", "wbr"}
_TAG_TOKEN_RE = re.compile(r'<\s*(/?)\s*([a-zA-Z][a-zA-Z0-9-]*)\b[^>]*?(/?)\s*>')


def _tag_balance_delta(html: str) -> dict:
    delta: dict = {}
    for m in _TAG_TOKEN_RE.finditer(html):
        closing, name, self_closing = m.group(1), m.group(2).lower(), m.group(3)
        if self_closing or name in _VOID_TAGS:
            continue
        delta[name] = delta.get(name, 0) + (-1 if closing else 1)
    return delta


def _check_tag_balance(old_str: str, new_str: str) -> str:
    old_delta = _tag_balance_delta(old_str)
    new_delta = _tag_balance_delta(new_str)
    problems = []
    for tag in sorted(set(old_delta) | set(new_delta)):
        diff = new_delta.get(tag, 0) - old_delta.get(tag, 0)
        if diff != 0:
            problems.append(f"<{tag}> {'多开' if diff > 0 else '多闭'} {abs(diff)} 个")
    return "；".join(problems)


def _sync_resume_db(resume_id: int, content: str) -> None:
    if not resume_id:
        return
    try:
        from ...services.resume_db import SessionLocal
        db = SessionLocal()
        try:
            db_resume = db.query(models.Resume).filter(models.Resume.id == resume_id).first()
            if db_resume:
                db_resume.rendered_html = content
                db.commit()
        finally:
            db.close()
    except Exception:
        pass


def _do_write_with_safety(resume_id: int, new_content: str, snap_info: dict | None) -> tuple[bool, str]:
    """写入文件 + DB同步 + HTML语法校验 + 失败自动弹栈回滚。

    使用「瞬态安全快照」：写入前 push_safety_snapshot，写失败语法校验不过则
    pop_safety_snapshot 回滚当前失败写入；成功则 discard_safety_snapshot 丢弃。
    不污染用户可见的回合快照栈。
    """
    file_path = resume_file_path(resume_id)
    write_resume_file(resume_id, new_content)
    _sync_resume_db(resume_id, new_content)

    vres = syntax.validate_syntax(file_path, new_content)
    if not vres["ok"]:
        entry = snapshot.pop_safety_snapshot(resume_id)
        if entry:
            snapshot.restore_from_entry(entry, resume_id)
            rollback_content = read_resume_file(resume_id)
            write_resume_file(resume_id, rollback_content)
            _sync_resume_db(resume_id, rollback_content)
        return False, f"HTML 语法校验失败，已自动回滚到修改前版本。\n{vres['message']}\n请重新 read_file 并修改。"
    snapshot.discard_safety_snapshot(resume_id)
    return True, ""


def execute_tool(name: str, arguments: dict, resume_id: int) -> str:
    if arguments is None:
        return f"工具调用参数解析失败，请重新调用 {name} 工具，确保参数是合法 JSON。"

    file_path = resume_file_path(resume_id)

    if name == "read_file":
        content = read_resume_file(resume_id)
        if not content:
            return "(文件为空或不存在)"
        if file_path.exists():
            file_md5 = hashing.compute_hash(file_path)
            _cache_file_md5(resume_id, file_md5)

        section_id = arguments.get("section_id", "").strip()
        if section_id:
            section_html = _read_section(content, section_id)
            if section_html:
                return section_html
            return f"未找到 data-resume-section=\"{section_id}\" 的 section。可用的 section 列表：\n" + _list_sections(content)
        _mark_full_read(resume_id)
        return content

    elif name == "patch_file":
        old_str = arguments.get("old_str")
        new_str = arguments.get("new_str")

        if not old_str and arguments.get("section_id"):
            section_id = arguments.get("section_id", "").strip()
            new_html = arguments.get("new_html", "")
            if not new_html or not new_html.strip():
                return "写入失败：new_html 参数为空。请传入该 section 修改后的完整 HTML 片段。"
            content = read_resume_file(resume_id)
            if not content:
                return "文件为空，无法 patch。请先使用 write_file 写入完整 HTML。"
            new_content = _patch_section(content, section_id, new_html)
            if not new_content:
                return f"未找到 data-resume-section=\"{section_id}\" 的 section，patch 失败。可用的 section 列表：\n" + _list_sections(content)
            # 瞬态安全快照：仅用于语法校验失败回滚当前写入，不污染回合栈
            snapshot.push_safety_snapshot(file_path, resume_id=resume_id)
            ok, err = _do_write_with_safety(resume_id, new_content, None)
            if not ok:
                return err
            return f"section[{section_id}] 已替换（旧版整段模式），共 {len(new_html)} 字符写入。前端预览将自动刷新。建议改用 patch_file(old_str, new_str) 精确替换。"

        if not isinstance(old_str, str) or not old_str.strip():
            return ("写入失败：old_str 参数为空。正确用法：先用 read_file 读取目标片段，"
                    "把要修改的原文逐字符精确复制为 old_str，修改后的片段作为 new_str 传入。")
        if "new_str" not in arguments:
            return "写入失败：缺少 new_str 参数。新增内容写入 new_str；删除内容传空字符串。"
        if not isinstance(new_str, str):
            new_str = str(new_str)
        content = read_resume_file(resume_id)
        if not content:
            return "文件为空，无法 patch。请先使用 write_file 写入完整 HTML。"
        if old_str == new_str:
            return "old_str 与 new_str 相同，无需替换。"

        if file_path.exists():
            expected_hash = _get_cached_md5(resume_id)
            if expected_hash:
                try:
                    hashing.verify_hash(file_path, expected_hash)
                except HashMismatchError:
                    content = read_resume_file(resume_id)
                    new_hash = hashing.compute_hash(file_path)
                    _cache_file_md5(resume_id, new_hash)
                    _mark_full_read(resume_id)

        try:
            match = matcher.match_once(content, old_str)
        except MatchError as e:
            if e.hits and len(e.hits) > 1:
                return (f"old_str 在文件中出现 {len(e.hits)} 次，无法确定替换目标。"
                        "请在 old_str 中多包含几行上下文，使其在全文中唯一。")
            return ("old_str 未在文件中找到（0 处匹配）。请重新 read_file 读取目标片段，"
                    "并逐字符精确复制——空格、Tab、换行、缩进、全角/半角标点必须与原文尽量一致。"
                    "系统支持模糊匹配，但 old_str 仍需足够接近原文。")

        new_content = content[:match.start] + new_str + content[match.end:]

        balance = _check_tag_balance(
            content[match.start:match.end], new_str
        )
        if balance:
            return (f"替换被拒绝：new_str 标签不平衡（{balance}）。"
                    "请确保 new_str 中新增的标签全部正确闭合、删除的标签成对移除，修正后重试。")

        if file_path.exists():
            snapshot.push_safety_snapshot(file_path, resume_id=resume_id)
        ok, err = _do_write_with_safety(resume_id, new_content, None)
        if not ok:
            return err

        match_desc = "精确" if match.matched_exact else f"模糊(similarity={match.similarity:.2f})"
        old_prev = content[match.start:match.end].replace("\n", " ")[:60]
        new_prev = new_str.replace("\n", " ")[:60]
        return (f"已替换 1 处（{match_desc}匹配）：「{old_prev}」→「{new_prev}」。"
                f"文件共 {len(new_content)} 字符，前端预览将自动刷新。")

    elif name == "write_file":
        content = arguments.get("content", "")
        if not content or not content.strip():
            return "写入失败：content 参数为空。请重新调用 write_file，确保传入完整的 HTML 内容。"
        existing = read_resume_file(resume_id)
        if existing and existing.strip() and not _has_full_read(resume_id):
            return ("写入被拒绝：原简历已存在内容，但你尚未在本轮对话中通过 read_file（不传 section_id）读取完整文件。"
                    "为避免覆盖丢失原内容，请先调用 read_file 读取全文，再写入；或改用 patch_file 按 section 局部修改。")

        if file_path.exists():
            expected_hash = _get_cached_md5(resume_id)
            if expected_hash:
                try:
                    hashing.verify_hash(file_path, expected_hash)
                except HashMismatchError:
                    new_hash = hashing.compute_hash(file_path)
                    _cache_file_md5(resume_id, new_hash)
                    _mark_full_read(resume_id)

        if file_path.exists():
            snapshot.push_safety_snapshot(file_path, resume_id=resume_id)
        ok, err = _do_write_with_safety(resume_id, content, None)
        if not ok:
            return err
        return f"文件已写入，共 {len(content)} 字符。前端预览将自动刷新。"

    else:
        return f"未知工具: {name}"
