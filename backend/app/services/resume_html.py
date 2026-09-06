"""结构化简历 JSON 的规范化与纯文本转换。

模板渲染功能已废弃：简历 HTML 由 AI 直接生成（resume_agent.py），
此模块仅保留结构化数据的清洗/校验与文本化工具。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

TEMPLATES = ("classic", "modern", "minimal")
ACCENTS = ("#2563eb", "#0d9488", "#334155", "#9f1239", "#7c3aed")


# ══════════════════════════════════════════════════════════════
# 规范化
# ══════════════════════════════════════════════════════════════

def _s(d: Any, key: str) -> str:
    if not isinstance(d, dict):
        return ""
    v = d.get(key)
    if isinstance(v, str):
        return v.strip()
    if v is None:
        return ""
    return str(v).strip()


def _items(v: Any) -> List[str]:
    if isinstance(v, list):
        out = []
        for x in v:
            t = str(x).strip()
            if t:
                out.append(t)
        return out
    if isinstance(v, str) and v.strip():
        return [p.strip() for p in re.split(r"[,，、;；\n]", v) if p.strip()]
    return []


def _entry(raw: Any, keys: List[str], list_keys: List[str]) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    out: Dict[str, Any] = {k: _s(raw, k) for k in keys}
    for k in list_keys:
        out[k] = _items(raw.get(k))
    return out


def normalize_structured(data: Any, keep_meta: bool = True) -> Dict[str, Any]:
    """把任意（通常来自 AI 的）输入清洗为完整、安全的结构化简历。"""
    if not isinstance(data, dict):
        data = {}
    meta_in = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    template = meta_in.get("template") if meta_in.get("template") in TEMPLATES else "classic"
    accent = meta_in.get("accent") if meta_in.get("accent") in ACCENTS else "#2563eb"
    custom_css = meta_in.get("customCss") if isinstance(meta_in.get("customCss"), str) else ""

    basics = data.get("basics") if isinstance(data.get("basics"), dict) else {}
    experience = [_entry(e, ["company", "role", "start", "end"], ["highlights"])
                  for e in (data.get("experience") or []) if isinstance(e, (dict,))]
    projects = [_entry(p, ["name", "role", "start", "end", "description"], ["highlights"])
                for p in (data.get("projects") or []) if isinstance(p, (dict,))]
    education = [_entry(e, ["school", "major", "degree", "start", "end"], ["highlights"])
                 for e in (data.get("education") or []) if isinstance(e, (dict,))]
    skills = []
    for s in data.get("skills") or []:
        if isinstance(s, dict):
            skills.append({"category": _s(s, "category"), "items": _items(s.get("items"))})
        elif isinstance(s, str) and s.strip():
            skills.append({"category": "技能", "items": _items(s)})
    extras = []
    for x in data.get("extras") or []:
        if isinstance(x, dict):
            extras.append({"title": _s(x, "title") or "其他", "items": _items(x.get("items"))})

    # 兼容 AI 可能输出的 "resume" 嵌套
    if isinstance(data.get("resume"), dict) and not (experience or projects or education):
        return normalize_structured(data["resume"], keep_meta=keep_meta)

    summary = data.get("summary")
    if not isinstance(summary, str):
        summary = ""

    return {
        "meta": {"template": template, "accent": accent, "customCss": custom_css} if keep_meta else {},
        "basics": {
            "name": _s(basics, "name"),
            "headline": _s(basics, "headline"),
            "email": _s(basics, "email"),
            "phone": _s(basics, "phone"),
            "location": _s(basics, "location"),
            "links": _items(basics.get("links")),
        },
        "summary": summary.strip(),
        "experience": experience,
        "projects": projects,
        "education": education,
        "skills": skills,
        "extras": extras,
    }


# ══════════════════════════════════════════════════════════════
# 结构化 JSON → 纯文本（供 AI 对话 / 匹配评估使用，向下兼容 content）
# ══════════════════════════════════════════════════════════════

def structured_to_text(data: Dict[str, Any]) -> str:
    d = normalize_structured(data)
    b = d["basics"]
    lines: List[str] = []

    lines.append("📋 基本信息")
    head = " | ".join(x for x in [b["name"], b["headline"]] if x)
    if head:
        lines.append(f"  {head}")
    contact = " | ".join(x for x in [b["location"], b["phone"], b["email"]] if x)
    if contact:
        lines.append(f"  {contact}")
    for l in b["links"]:
        lines.append(f"  {l}")

    if d["summary"]:
        lines += ["", "💬 个人简介"]
        lines += [f"  {p.strip()}" for p in d["summary"].splitlines() if p.strip()]

    if d["experience"]:
        lines += ["", "💼 工作经历"]
        for e in d["experience"]:
            seg = f"  {e['company']} | {e['role']}  {e['start']} - {e['end']}".rstrip(" -")
            lines.append(seg)
            for h in e["highlights"]:
                lines.append(f"  • {h}")

    if d["projects"]:
        lines += ["", "🚀 项目经历"]
        for p in d["projects"]:
            seg = f"  {p['name']} | {p['role']}  {p['start']} - {p['end']}".rstrip(" -")
            lines.append(seg)
            if p["description"]:
                lines.append(f"  {p['description']}")
            for h in p["highlights"]:
                lines.append(f"  • {h}")

    if d["education"]:
        lines += ["", "🎓 教育经历"]
        for e in d["education"]:
            seg = f"  {e['school']} | {e['major']} | {e['degree']}  {e['start']} - {e['end']}".rstrip(" -")
            lines.append(seg)
            for h in e["highlights"]:
                lines.append(f"  • {h}")

    if d["skills"]:
        lines += ["", "⚡ 核心技能"]
        for s in d["skills"]:
            if s["category"] or s["items"]:
                lines.append(f"  • {s['category']}：{'、'.join(s['items'])}".rstrip("："))

    for x in d["extras"]:
        if x["title"] or x["items"]:
            lines += ["", f"🏅 {x['title']}"]
            lines += [f"  • {i}" for i in x["items"]]

    return "\n".join(lines).strip()
