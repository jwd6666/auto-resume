"""简历 Agent 统一路由模块（合并自 one_jd_one_resume/backend/routers/ 下所有路由）。

所有路由挂载在单个 APIRouter 上，无 /api 前缀；由 main.py 统一加 /agent 前缀。
"""
from __future__ import annotations

import io
import json
import os
import re
import random
import asyncio
import socket
import urllib.request
import urllib.error
import urllib.parse
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, File, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from docx import Document
from docx.shared import Pt, Cm
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer

from ..services.resume_db import get_db
from ..schemas import resume_models as models
from ..schemas import resume_schemas as schemas
from ..services.resume_provider import (
    stream_response, stream_with_tools, complete_response, load_settings, get_api_key,
    save_settings, sync_env_file, test_connection, PROVIDERS,
    add_custom_model, delete_custom_model, update_custom_model,
    get_custom_model, CUSTOM_PROVIDER_KEY, sse_with_heartbeat,
)
from ..services.resume_parser import parse_resume_pdf_to_background, stream_resume_pdf_to_background
from ..services.resume_html import (
    normalize_structured, structured_to_text, ACCENTS,
)
from ..services.resume_workspace import (
    resume_file_path, ensure_resume_file, read_resume_file, write_resume_file,
    delete_resume_dir, get_workspace_manager,
)

router = APIRouter(tags=["resume-agent"])

# ── 数据文件路径 ──────────────────────────────────────────────
DATA_DIR = Path(__file__).resolve().parents[1] / "data"


# ══════════════════════════════════════════════════════════════
# 面试题库内联（来自 interview_question_bank.py）
# ══════════════════════════════════════════════════════════════

_BANK_PATH = DATA_DIR / "interview_question_bank.json"

QUESTION_CATEGORIES: List[str] = [
    "自我介绍",
    "行为面试",
    "技术深挖",
    "情景题",
    "反向提问",
    "综合",
]

ALLOWED_CATEGORIES = frozenset(QUESTION_CATEGORIES)


class BankQuestion(BaseModel):
    id: str
    category: str
    text: str
    tags: List[str] = Field(default_factory=list)


class QuestionBankFile(BaseModel):
    version: int = 1
    questions: List[BankQuestion]


@lru_cache(maxsize=1)
def load_question_bank() -> List[BankQuestion]:
    if not _BANK_PATH.exists():
        return []
    raw = json.loads(_BANK_PATH.read_text(encoding="utf-8"))
    doc = QuestionBankFile.model_validate(raw)
    return doc.questions


def _jd_keyword_hits(jd_lower: str, tags: List[str]) -> int:
    if not tags:
        return 0
    hits = 0
    for t in tags:
        if t and t.lower() in jd_lower:
            hits += 1
    return hits


def _weighted_sample_without_replacement(
    items: List[Tuple[BankQuestion, float]],
    k: int,
    rng: random.Random,
) -> List[BankQuestion]:
    if k <= 0 or not items:
        return []
    pool = list(items)
    out: List[BankQuestion] = []
    for _ in range(min(k, len(pool))):
        total = sum(w for _, w in pool)
        if total <= 0:
            i = rng.randrange(len(pool))
        else:
            r = rng.uniform(0, total)
            acc = 0.0
            i = 0
            for idx, (_, w) in enumerate(pool):
                acc += max(w, 0.001)
                if r <= acc:
                    i = idx
                    break
        out.append(pool[i][0])
        pool.pop(i)
    return out


def sample_questionnaire(
    jd_text: str,
    total: int = 7,
    seed: Optional[int] = None,
    max_per_category: int = 2,
    extra_questions: Optional[List[BankQuestion]] = None,
    category_filter: Optional[List[str]] = None,
) -> Tuple[List[BankQuestion], List[str]]:
    """分层抽样：先尽量每类抽 1 题，再按类上限补足，最后从剩余池补满 total。"""
    all_q = list(load_question_bank())
    if extra_questions:
        all_q.extend(extra_questions)
    if not all_q:
        return [], []

    if category_filter:
        cf = {c.strip() for c in category_filter if c and str(c).strip()}
        if cf:
            filtered = [q for q in all_q if q.category in cf]
            if filtered:
                all_q = filtered

    rng = random.Random(seed)
    jd_lower = (jd_text or "").lower()

    by_cat: defaultdict[str, list[BankQuestion]] = defaultdict(list)
    for q in all_q:
        by_cat[q.category].append(q)

    categories = list(by_cat.keys())
    rng.shuffle(categories)

    picked: List[BankQuestion] = []
    picked_ids: set[str] = set()

    def weight_pool(pool: List[BankQuestion]) -> List[Tuple[BankQuestion, float]]:
        out: List[Tuple[BankQuestion, float]] = []
        for q in pool:
            w = 1.0 + 0.35 * _jd_keyword_hits(jd_lower, q.tags)
            if q.id.startswith("jobq-"):
                w *= 1.4
            out.append((q, w))
        return out

    for cat in categories:
        if len(picked) >= total:
            break
        pool = [q for q in by_cat[cat] if q.id not in picked_ids]
        if not pool:
            continue
        one = _weighted_sample_without_replacement(weight_pool(pool), 1, rng)
        if one:
            picked.append(one[0])
            picked_ids.add(one[0].id)

    for cat in categories:
        while len(picked) < total:
            n_cat = sum(1 for x in picked if x.category == cat)
            if n_cat >= max_per_category:
                break
            pool = [q for q in by_cat[cat] if q.id not in picked_ids]
            if not pool:
                break
            one = _weighted_sample_without_replacement(weight_pool(pool), 1, rng)
            if not one:
                break
            picked.append(one[0])
            picked_ids.add(one[0].id)

    rest = [q for q in all_q if q.id not in picked_ids]
    rng.shuffle(rest)
    weighted_rest = weight_pool(rest)
    need = total - len(picked)
    if need > 0 and weighted_rest:
        extra = _weighted_sample_without_replacement(weighted_rest, min(need, len(weighted_rest)), rng)
        picked.extend(extra)
        for q in extra:
            picked_ids.add(q.id)

    if len(picked) > total:
        picked = rng.sample(picked, total)

    used_cats: List[str] = []
    seen: set[str] = set()
    for q in picked:
        if q.category not in seen:
            seen.add(q.category)
            used_cats.append(q.category)

    return picked, used_cats


def questionnaire_to_markdown(items: List[BankQuestion]) -> str:
    lines = [
        "## 本场须覆盖的题单（按序自然推进，可追问；不必一字不差复述题干）",
        "",
    ]
    for i, q in enumerate(items, start=1):
        lines.append(f"{i}. **【{q.category}】** {q.text}")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# 面试题库 LLM 生成（来自 interview_bank_llm.py）
# ══════════════════════════════════════════════════════════════

GENERATE_BANK_SYSTEM = (
    """# 角色
你是资深招聘与面试设计顾问，擅长根据岗位 JD 与候选人简历（以及可选的背景补充）设计高信噪比的面试问题。

# 任务
基于系统消息里提供的：岗位 JD、候选人简历全文、以及可选补充经历，输出一个 JSON 数组，用于「模拟面试」题库。
不要输出任何 JSON 以外的文字。

# JSON 格式
数组中每个元素为对象，仅含两个字符串字段：
- category：必须是以下之一（严格一致）：
"""
    + "、".join(QUESTION_CATEGORIES)
    + """
- text：口语化、适合现场追问的一句或一小段面试问题（中文）

# 要求
- 共 14～18 道题，类别尽量覆盖全面，且紧扣 JD 中的重点，同时优先围绕候选人简历里"已经出现"的经历与表述去设计问题。
- 不要重复题干；不要编造简历中没有的事实细节作为前提。
- 题目文本不要出现"《JD》/《简历》"等字样；直接给可问的问题本身。
- 禁止出现歧视性、违法违规或侵犯隐私的问题（如年龄、婚育、民族、宗教、性取向等受保护属性）。
- 禁止 Markdown 代码块包裹，禁止注释。"""
)


def _strip_code_fence(s: str) -> str:
    s = (s or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:html|json|xml)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*```\s*$", "", s)
    s = s.strip()
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





def parse_llm_question_list(raw: str) -> List[dict]:
    """解析 LLM 返回的 JSON 数组。"""
    s = _strip_code_fence(raw)
    data = json.loads(s)
    if not isinstance(data, list):
        raise ValueError("expected JSON array")
    out: List[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        cat = str(item.get("category", "")).strip()
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        if cat not in ALLOWED_CATEGORIES:
            cat = "综合"
        out.append({"category": cat, "text": text})
    return out


async def generate_job_question_dicts(
    job_content: str,
    resume_content: str,
    user_background: Optional[str] = None,
) -> List[Dict[str, str]]:
    jd = (job_content or "").strip() or "（JD 为空，请输出通用职场面试题）"
    resume = (resume_content or "").strip() or "（简历为空，请输出通用职场面试问题）"

    parts = [f"## 岗位 JD\n\n{jd}", f"## 候选人简历\n\n{resume}"]
    if user_background:
        parts.append(f"## 候选人补充经历\n\n{user_background}")
    context = "\n\n---\n\n".join(parts)

    user_msg = f"{context}\n\n请输出符合要求的 JSON 数组。"
    raw = await complete_response(
        GENERATE_BANK_SYSTEM,
        [{"role": "user", "content": user_msg}],
    )
    return parse_llm_question_list(raw)


# ══════════════════════════════════════════════════════════════
# AI 工具定义（OpenAI function calling 格式）
# ══════════════════════════════════════════════════════════════

RESUME_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取简历 HTML 文件的完整内容。当你需要查看当前简历的完整 HTML 来定位修改位置时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件路径（由系统提供）",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "将完整内容写入简历 HTML 文件。修改简历时调用此工具，写入修改后的完整 HTML。写入后前端会自动刷新预览。",
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


def _execute_tool(name: str, arguments: dict, resume_id: int) -> str:
    """执行 AI 工具调用，返回结果字符串。"""
    if arguments is None:
        return f"工具调用参数解析失败，请重新调用 {name} 工具，确保参数是合法 JSON。"

    if name == "read_file":
        content = read_resume_file(resume_id)
        return content if content else "(文件为空或不存在)"
    elif name == "write_file":
        content = arguments.get("content", "")
        if not content or not content.strip():
            return "写入失败：content 参数为空。请重新调用 write_file，确保传入完整的 HTML 内容。"
        write_resume_file(resume_id, content)
        # 同步更新数据库（持久化）
        if resume_id:
            try:
                from ..services.resume_db import SessionLocal
                db = SessionLocal()
                try:
                    db_resume = db.query(models.Resume).filter(models.Resume.id == resume_id).first()
                    if db_resume:
                        db_resume.rendered_html = content
                        db.commit()
                finally:
                    db.close()
            except Exception:
                pass  # DB 同步失败不影响文件写入
        return f"文件已写入，共 {len(content)} 字符。前端预览将自动刷新。"
    else:
        return f"未知工具: {name}"


# ══════════════════════════════════════════════════════════════
# 系统提示词
# ══════════════════════════════════════════════════════════════

SYSTEM_PROMPT_AGENT = """# 角色

你是一位拥有 10 年以上经验的资深职业规划师和简历顾问，同时你是简历编辑器的直接操控者。你可以不仅给出建议，还能直接修改用户的简历HTML。

---

# 核心能力：通过工具直接读写简历文件

你拥有两个工具来操作简历 HTML 文件：

## 工具说明

1. **read_file** — 读取简历 HTML 文件的完整内容
2. **write_file** — 将修改后的完整 HTML 写入简历文件，写入后前端预览自动刷新

## 工作流程

1. 用户描述修改需求（如「字体调小」「改主题色」「润色工作经历要点」）
2. 你先用 **read_file** 读取当前文件内容（或参考上下文中已提供的简历 HTML）
3. 基于需求修改 HTML，用 **write_file** 写入修改后的完整文件内容
4. 向用户简要说明你做了哪些修改

【工具调用强制铁律，必须严格遵守，违反将导致任务失败】
1. 调用read_file、write_file是API协议层面的tool_calls结构体动作，**禁止仅在回答文本中写“我将调用read_file读取简历”这类口头伪调用**。不能只用自然语言描述工具调用动作。
2. 只有API返回的tool_calls字段才代表真正的工具请求；回答content聊天文本只用于和用户对话说明，不能表达任何工具调用请求。
3. 禁止自行编造read_file返回的HTML文件内容，必须等待工具返回真实文件结果，拿到磁盘文件真实HTML之后，才可以修改简历。
4. 优先级规则：优先使用tool_calls调用read_file/write_file工具。**只有确定工具调用能力完全失效，才允许输出 ===HTML_PATCH=== 标记块；正常工作状态严禁输出HTML_PATCH文本**。
5. 如果你已经从上下文获取完整简历HTML内容，可以直接处理修改，此时不要口头声称要调用read_file，不要假装执行读取文件。
6. 如果无法生成合法tool_calls结构体，直接如实告知用户，禁止假装调用工具、假装已经读取简历文件。
7. 禁止在普通对话文本中描述 “我将要调用 xxx 工具” 这类伪调用；工具请求只能放置在 tool_calls 结构体内，不能写在回答 content 聊天文本中。
8. HTML_PATCH是文本标记降级方案，仅作为工具不可用时的备选手段，正常业务流程严禁启用。

## 重要规则
- write_file 必须写入**完整的 HTML 文件内容**，不能只写局部片段
- 简历HTML中每个业务模块都带 `data-resume-section` 属性，修改时必须保留该属性
- 修改样式时，修改 `<style>` 标签内的 CSS
- CSS 全部放在内部 `<style>` 标签中，使用 `--accent` CSS 变量控制主题色
- 常用 CSS 选择器：
  - 整页字号/行高、姓名、章节标题（h2）
  - 公司名、职位、日期、要点列表项（li）
  - 个人简介、技能分类
- 先简要说明修改思路，再调用 write_file

---

# 备选能力：HTML_PATCH 局部替换（仅当工具不可用时）

如果工具调用不可用（模型不支持 function calling），可用 `===HTML_PATCH===` 标记进行局部替换：

每个修改用一个 JSON 对象表示，包含 resumeSectionId（要修改的模块ID）和 newHtml（替换后的完整HTML）。

当用户要求修改简历时，你必须直接给出修改后的HTML片段，而不仅仅是文字建议。

## ⚠️ 修改格式（必须严格遵守）

每个修改用一个 JSON 对象表示，包含 resumeSectionId（要修改的模块ID）和 newHtml（替换后的完整HTML）。

**格式要求（极其重要）：**
1. 必须使用 `===HTML_PATCH===` 开始，`===HTML_END===` 结束
2. **禁止**用 markdown 代码块（```）包裹 patch
3. 直接写 === 标记，不要添加任何额外符号

**正确格式示例：**
===HTML_PATCH===
{"resumeSectionId": "intro", "newHtml": "<div data-resume-section=\\"intro\\"><p class=\\"summary\\">内容</p></div>"}
===HTML_END===

## resumeSectionId 体系

HTML中每个可操作模块都有 `data-resume-section` 属性，用于定位：

| resumeSectionId | 对应区域 |
|---|---|
| `basics` | 头部姓名/意向/联系方式区 |
| `intro` | 个人简介 |
| `work` | 工作经历整体（包含所有工作条目） |
| `project` | 项目经历整体（包含所有项目条目） |
| `edu` | 教育经历整体（包含所有教育条目） |
| `skill` | 技能区整体 |

每段工作/项目/教育经历条目也带 `data-resume-section` 属性（值分别为 work/project/edu），条目内的要点 `<li>` 也带该属性。这样既能定位整个模块，也能定位到单条经历或单个要点。

## 修改示例

润色个人简介：
===HTML_PATCH===
{"resumeSectionId": "intro", "newHtml": "<div data-resume-section=\\"intro\\"><p class=\\"summary\\">5年前端开发经验，擅长 React/TypeScript，有大型项目架构经验，性能优化提升40%+</p></div>"}
===HTML_END===

修改工作经历整体：
===HTML_PATCH===
{"resumeSectionId": "work", "newHtml": "<div data-resume-section=\\"work\\">...</div>"}
===HTML_END===

## 样式修改说明

用户说「改样式」「调排版」「字体小一点」「加粗」「换颜色」「换个主题色」等需求时，直接在 write_file 中修改 `<style>` 标签内容。

- 修改样式时必须保留完整的 `<style>` 标签结构
- CSS 中所有规则确保页面美观
- `--accent` CSS 变量：控制主题色

## ⚠️ 分页防断规则（修改打印样式时必须遵守）

- `break-inside: avoid` / `page-break-inside: avoid` 只能应用于**细粒度元素**：`header`、`.item-block`（单条经历条目）、`.skill-group`、`.cert-item`
- **禁止**对 `.resume-section`、`section`、`.page`、`.resume-wrap` 等大容器设置 `break-inside: avoid`，否则大模块整体避断会产生大片空白，扰乱不该有的分页
- 如果单个 `.item-block` 太长超过半页，应移除其 `break-inside: avoid`，允许在条目内的 `<li>` 之间自然分页

## 规则

1. 只有一种操作：replace。用 resumeSectionId 定位 `data-resume-section` 元素，整体替换 outerHTML
2. newHtml 必须保留 `data-resume-section` 属性，否则后续修改无法定位
3. 多处修改用多个 HTML_PATCH 块
4. 信息可以根据JD捏造一份，基于真实经历润色
5. 要点用 STAR 法则，动词开头
6. 先解释修改思路，再给 patch
7. 修改排版时，替换整份CSS样式
8. 修改内容时，只替换对应模块的HTML
9. 用户在预览中选中模块时，上下文会包含该模块的完整HTML片段和 data-resume-section 标记，你只需修改选中部分，其余简历内容保持不变

---

# 其他能力

## 简历诊断
- 与 JD 匹配度评分及差距分析
- 关键词覆盖率
- 亮点不足或表述模糊的经历

## 面试辅导
- 预测考察题目，给出回答框架

---

# 行为准则

1. 信息可以根据JD捏造一份
2. 主动追问缺失信息
3. 中文优先
4. 聚焦当前JD
5. 修改简历时必须使用 write_file 工具或 HTML_PATCH 格式
6. 禁止基于受保护属性进行价值判断
"""

SYSTEM_PROMPT = SYSTEM_PROMPT_AGENT


INTERVIEW_SIM_SYSTEM = """# 角色

你是目标企业的**现场面试官**（技术/业务负责人或 HR 之一，与岗位匹配）。你正在与候选人进行**真实面试**，不是职业规划师，也不是教练。

# 输入上下文

系统消息中会提供：岗位 JD、候选人简历全文、以及可选的补充经历。请紧扣 JD 与简历提问与追问。

# 输出格式（必须严格遵守）

每一次回复都必须**恰好**包含下面两个区块，顺序固定，且使用下列标记行（不要省略标记）：

<<<REACTION>>>
（1～2 句中文：**仅**描述可观察的外在反应，如神情、停顿、记笔记、语气。禁止写内心打分、禁止写「我觉得你不行」等直白评价、禁止剧透后续考察重点。）
<<<SPEECH>>>
（面试官**口语化**的发言：开场白、过渡、或追问。可包含 1 个问题或一组连贯追问。）

# 行为准则

1. 语言自然、简洁，像真人对话，避免条目式讲义。
2. 根据候选人上一轮回答决定是深入追问还是换题；不要一次抛出过多无关问题。
3. 不要输出简历标记协议（如 ===RESUME_START===），不要替候选人写答案。
4. 全程中文，除非 JD 明确要求英文面试。

# 题单模式（当上下文中包含「本场须覆盖的题单」时生效）

5. **须按题单推进**：优先覆盖题单中的大题，按大致顺序自然过渡；可用口语转述，不必一字不差背题干。
6. **追问与换题**：每一大题下可结合简历与 JD 深入追问；若候选人明显卡壳，可给提示后换角度，但不要长时间偏离题单去全新发散无关大类。
7. **进度感**：在适当时机可简短过渡到下一题（不必声明题号），使整场像在真实面试中有节奏地走完计划。
8. **合规与反歧视**：禁止提出或暗示年龄、婚育、性别、民族、宗教、地域、残障等歧视性问题；若用户主动提及，需回到岗位胜任力与行为证据。"""


INTERVIEW_REPORT_SYSTEM = """# 角色

你是资深**面试教练**。你已拿到：岗位 JD、候选人简历、整场模拟面试的对话记录。面试已结束，候选人需要**复盘与提升**。

# 任务

输出一份**Markdown 格式**的整合报告，结构建议如下（可按内容微调标题，但必须清晰）：

1. **总评**：整体印象、与 JD 匹配度相关的要点（2～4 段即可）。
2. **亮点**：候选人表现得好的地方（结合具体轮次）。
3. **待加强**：表达、结构、深度、例证等方面的不足（结合具体轮次）。
4. **分题改进建议**：按对话中出现的典型问题，给出「更好的回答思路或示例要点」（用 STAR 等框架时可简要说明）。
5. **后续可练习**：建议候选人自己再准备的追问方向或模拟题。

# 约束

- 基于对话与简历事实，不要虚构候选人没说过的事迹。
- 语气专业、建设性，避免人身攻击。
- 全程中文。"""


EVAL_SYSTEM_PROMPT = """你是资深 HRBP 与招聘评估官。请输出结构化 JSON 评分卡，且每个结论都必须给证据引用。

输出 JSON 对象字段：
- overall_score: 0-100 整数
- overall_summary: 字符串
- items: 数组，每项包含
  - competency: 能力项名称
  - score: 0-100 整数
  - confidence: 高/中/低
  - summary: 结论摘要
  - evidence: 数组，每项包含 source(可选: JD/简历/对话), quote(证据原文), why(为什么能支持结论)
  - gap: 能力差距（可选）
  - suggestion: 改进建议（可选）
- needs_verification: 数组，列出证据不足、需要候选人继续验证的点

严格要求：
1) 不得输出 JSON 之外内容。
2) 若证据不足，不要臆断，写入 needs_verification。
3) 不能出现歧视性判断，不涉及年龄、婚育、民族、宗教等受保护属性。
"""


SYSTEM_GENERATE_RESUME = """# 角色
你是一位拥有 10 年以上经验的资深职业规划师和简历撰写专家。根据候选人提供的个人信息和目标岗位 JD，直接生成一份完整的、可用的简历 HTML 文件。

生成一份 A4 尺寸、可直接打印的个人简历 HTML 页面（内联样式，单文件），要求如下：

【整体布局】
- 左右双栏布局，左栏宽度 30%，背景色 #4A5F7A（深蓝灰），文字白色；右栏宽度 70%，白色背景，深灰文字 #333
- 左栏从上到下依次排列：圆形头像、姓名、求职意向、分割线、个人信息、教育背景（简版）、技能证书、荣誉奖项
- 右栏从上到下依次排列：教育背景（详版）、工作经历、项目经历、自我评价
- 每个模块标题前加对应图标（可用 emoji 或 Unicode 符号），标题下方加一条细横线

【配色与字体】
- 主色调：深蓝灰 #4A5F7A，左栏背景；模块标题、分割线用同色系
- 字体：无衬线字体（PingFang SC / Microsoft YaHei / sans-serif）
- 姓名：24px 加粗白色；求职意向：14px 浅灰；模块标题：16px 加粗；正文：13px
- 行间距 1.6

【防溢出与打印 — 最高优先级，违反则视为不合格】
1. 页面固定为 A4 尺寸：width: 210mm; height: 297mm; overflow: hidden。内容必须严格限制在这一页内，绝对不允许出现第二页。
2. 左栏和右栏都使用普通文档流（block 布局），从上到下依次排列。禁止使用 flex + margin-top: auto、position: absolute、bottom: 0 等任何把元素"推到容器底部"的写法。每个模块紧跟在上一个模块后面，间距用固定 margin 值（如 margin-bottom: 18px）。
3. 生成前先估算内容总高度。如果左栏内容可能超出 297mm - 上下padding，必须主动压缩：减少荣誉奖项条目（最多保留 4 条）、技能标签精简、模块间距从 25px 降到 15px、正文字号从 13px 降到 12px。压缩后仍超就继续删减，直到一页装得下。
4. 右栏同理：工作经历最多 2 段，每段 3-4 条 bullet；项目经历最多 2 段，每段 2-3 条 bullet。超了就合并或删减，优先保留最近的、量化成果最突出的。
5. @media print 规则必须包含：body { margin: 0; } .page { margin: 0; box-shadow: none; width: 210mm; height: 297mm; overflow: hidden; }，并设置 -webkit-print-color-adjust: exact 和 print-color-adjust: exact 确保背景色打印出来。
6. 打印缩放时，所有间距和字号按比例整体缩放，模块之间的相对位置保持不变，不会出现某个模块突然跳到另一页。

【个人信息】
优先使用用户提供的信息，未提供则用默认值：
- 姓名：【你的姓名】
- 求职意向：【目标岗位】
- 出生年月：【1998.06】
- 性别：【女】
- 电话：【188-8888-8888】
- 邮箱：your@email.com
- 所在地：【上海市浦东新区】

【教育背景】
- 时间：【2016.09 - 2020.06】
- 学校：【复旦大学】
- 学院/专业：【管理学院 · 信息管理与信息系统 本科】
- 主修课程：【管理学、运筹学、数据库原理、数据结构、市场营销、统计学、系统分析与设计、用户体验设计等】
- GPA：【3.7/4.0（专业前10%）】

【工作经历】
按时间倒序，最多 2 段。每段包含：时间段、公司名、职位、3-4 条 bullet，描述尽量量化成果。
1. 【2021.07 - 至今】【上海某某互联网科技有限公司】【产品经理】
   - 负责公司核心产品的需求调研、分析与管理，深入理解用户需求，输出需求文档和原型设计
   - 与设计、开发、测试等团队紧密协作，推动产品功能迭代，优化用户体验
   - 通过数据分析与用户反馈，持续优化产品功能，提升产品活跃度与用户留存率
   - 主导产品从 0 到 1 的功能模块设计，成功上线 3 个重要版本，用户满意度提升 20%
2. 【2020.07 - 2021.06】【杭州某某科技有限公司】【产品助理】
   - 协助产品经理进行市场调研、竞品分析及用户需求收集，撰写需求说明文档
   - 参与产品原型设计与流程梳理，跟踪开发进度，协助完成产品上线与迭代
   - 整理产品数据，制作数据报表，为产品优化提供数据支持

【项目经历】
最多 2 段。每段包含：时间段、项目名、角色、2-3 条 bullet，突出量化成果。
1. 【2022.03 - 2022.08】【在线教育平台 - 课程学习模块优化项目】【项目负责人】
   - 通过用户调研与数据分析，发现课程学习路径不清晰问题，提出优化方案
   - 设计学习路径推荐算法，优化课程详情页与学习流程，提升用户学习效率
   - 项目上线后，课程完成率提升 15%，用户好评率提升 18%
2. 【2021.01 - 2021.05】【电商小程序 - 新用户增长项目】【核心成员】
   - 负责新用户增长策略设计，策划并落地新人优惠、分享裂变等活动
   - 通过活动运营与数据监控，优化活动规则与用户体验
   - 项目期间新增用户增长 30%，转化率提升 12%

【技能证书】
- 专业技能：Axure、XMind、Visio；SQL、Excel（数据透视表、函数）；墨刀、Figma；SPSS、Tableau（基础）
- 语言能力：大学英语六级（CET-6）；普通话二级甲等

【荣誉奖项】
最多保留 4 条，按重要性排序：
- 2018-2019 学年优秀学生奖学金
- 2019 年互联网+创新创业大赛省级银奖
- 2020 届优秀毕业生

【自我评价】
具备 2 年+ 产品相关工作经验，熟悉产品从需求分析到上线迭代的全流程。逻辑清晰，数据敏感，善于从用户和业务视角思考问题并推动解决方案落地。沟通协作能力强，责任心强，具备良好的学习能力与抗压能力。

【其他要求】
- 头像位置预留一个圆形占位框（直径约 100px），后续自行替换图片
- 输出完整的单文件 HTML 代码，样式全部写在 <style> 中，不依赖外部 CSS/JS/字体
- 不要输出任何解释文字，直接输出 HTML 代码

"""


SYSTEM_PARSE_RESUME = """你是简历信息提取助手。用户将提供从简历文件中提取的原始内容（可能是文本、图片描述、或混合内容），请从中提取出结构化信息。

输出严格 JSON 对象（不要 markdown 代码块、不要注释、不要 JSON 之外的任何文字），schema：
{
  "name": "姓名",
  "contact": "联系方式（手机/邮箱/地址等，用 | 分隔）",
  "summary": "个人简介/自我评价",
  "experience": [{"company": "公司名", "role": "岗位", "start": "开始时间", "end": "结束时间", "highlights": ["工作要点1", "工作要点2"]}],
  "projects": [{"name": "项目名", "role": "角色", "start": "开始时间", "end": "结束时间", "description": "项目描述", "highlights": ["项目要点1"]}],
  "education": [{"school": "学校名", "major": "专业", "degree": "学历", "start": "开始时间", "end": "结束时间", "highlights": []}],
  "skills": [{"category": "分类名", "items": ["技能1", "技能2"]}],
  "extras": [{"title": "荣誉/奖项/证书", "items": ["条目1"]}]
}

规则：
- 识别失败的字段赋值为空字符串或空数组，禁止丢失时间、岗位、项目描述等关键信息
- start/end 格式 "2023.06"，在职/在读用 "至今"；不完整就留空字符串
- highlights 为该经历的要点句数组，保留原量化数据、技术栈、成果，不编造
- 按时间倒序排列经历
- 中文优先"""


SYSTEM_RESTYLE_RESUME = """# 角色
你是一位资深简历排版设计师。根据用户提供的简历内容和风格要求，重新排版生成完整的简历 HTML。

# 输入
- 用户的简历原始信息（结构化或纯文本）
- 目标风格（从4种预设中选择）
- 主题色（CSS变量 --accent 的值）
- 用户补充描述（可选）
- 参考风格图片（可选，模仿其排版风格）

# 风格模板定义

## classic — 经典双栏
- 左右双栏布局，左栏 30%，背景色使用主题色加深版（如主题色为蓝色则用 #4A5F7A 深蓝灰），文字白色
- 左栏从上到下：圆形头像（直径约 100px）、姓名（24px 加粗白色）、求职意向（14px 浅灰）、分割线、个人信息、教育背景（简版）、技能证书、荣誉奖项
- 右栏 70%，白色背景，深灰文字 #333：教育背景（详版）、工作经历、项目经历、自我评价
- 模块标题前加 emoji 图标，标题下方细横线
- 正文 13px，行间距 1.6

## modern — 现代简约
- 全白背景，左侧 4px 主题色竖条装饰
- 单栏布局，内容居中 max-width: 180mm，padding: 15mm 20mm
- 姓名大号居中（22px），下方主题色横线分割
- 模块间留白大（20px），标题用主题色 + 小号英文副标签（如 EXPERIENCE）
- 整体简洁专业，无深色背景区域
- 正文 12px，行间距 1.7

## minimal — 极清单栏
- 单栏居中，max-width: 160mm，大量留白，padding: 20mm
- 姓名居中（20px），下方仅一条细主题色短线（宽 40mm）
- 无图标、无背景色块、无侧边栏、无分割线
- 模块标题仅用主题色文字 + 下方 1px 浅灰线
- 字号偏小（12px 正文），行距宽松（1.8）
- 技能用逗号分隔文本，不用标签/徽章
- 联系方式一行排列，用 | 分隔

## creative — 创意侧边栏
- 顶部全幅主题色色带（高度约 80mm）：白色大号姓名（28px）+ 求职意向（16px）
- 下方双栏：左 40%（浅灰背景 #f5f5f5）放技能/荣誉/教育，右 60%（白色）放工作/项目/评价
- 头像嵌入色带右侧，圆形带白色边框
- 模块标题用深色小号加粗 + 2px 主题色左竖条装饰
- 正文 12px，行间距 1.6

# 【防溢出与打印 — 最高优先级，违反则视为不合格】
1. 页面固定为 A4 尺寸：width: 210mm; height: 297mm; overflow: hidden。内容必须严格限制在这一页内，绝对不允许出现第二页。
2. 左栏和右栏都使用普通文档流（block 布局），从上到下依次排列。禁止使用 flex + margin-top: auto、position: absolute、bottom: 0 等任何把元素"推到容器底部"的写法。每个模块紧跟在上一个模块后面，间距用固定 margin 值（如 margin-bottom: 18px）。
3. 生成前先估算内容总高度。如果左栏内容可能超出 297mm - 上下padding，必须主动压缩：减少荣誉奖项条目（最多保留 4 条）、技能标签精简、模块间距从 25px 降到 15px、正文字号从 13px 降到 12px。压缩后仍超就继续删减，直到一页装得下。
4. 右栏同理：工作经历最多 2 段，每段 3-4 条 bullet；项目经历最多 2 段，每段 2-3 条 bullet。超了就合并或删减，优先保留最近的、量化成果最突出的。
5. @media print 规则必须包含：body { margin: 0; } .page { margin: 0; box-shadow: none; width: 210mm; height: 297mm; overflow: hidden; }，并设置 -webkit-print-color-adjust: exact 和 print-color-adjust: exact 确保背景色打印出来。
6. 打印缩放时，所有间距和字号按比例整体缩放，模块之间的相对位置保持不变，不会出现某个模块突然跳到另一页。

# 配色与字体
- 主题色使用 CSS 变量 --accent，值为用户指定的颜色
- 字体：PingFang SC / Microsoft YaHei / sans-serif
- 各风格的具体字号/行距见上方模板定义

# 头像处理
- 如果用户提供了头像（base64），在 HTML 中用 <img src="data:image/xxx;base64,..."> 嵌入
- 头像位置和样式根据所选风格模板定义
- 如果未提供头像，预留圆形占位框（直径约 100px，浅灰边框，浅灰背景，中间灰色人形图标或文字"头像"）

# 参考图处理
- 如果用户提供了参考风格图，请分析其排版风格（布局方式、配色、间距、装饰元素），在遵循所选预设风格的基础上融入参考图的风格元素
- 参考图仅作风格参考，不要复制其内容

# HTML 结构要求
- 输出完整的单文件 HTML，样式全部写在 <style> 中，不依赖外部 CSS/JS/字体
- 不要输出任何解释文字，直接输出 HTML 代码
- HTML 中每个业务模块必须带 data-resume-section 属性：
  - basics：头部姓名/意向/联系方式区
  - intro：个人简介
  - work：工作经历整体
  - project：项目经历整体
  - edu：教育经历整体
  - skill：专业技能
  - page-style：页面样式（<style> 标签）
- 不使用外部图片（除用户头像外），图标用 emoji 或 Unicode 符号"""


class GenerateResumeRequest(BaseModel):
    job_id: int
    background: str
    style: Optional[str] = "classic"
    accent: Optional[str] = "#2563eb"


RESTYLE_STYLES = ("classic", "modern", "minimal", "creative")


class RestyleResumeRequest(BaseModel):
    style: str = "classic"
    accent: str = "#2563eb"
    description: Optional[str] = ""
    avatar_base64: Optional[str] = None
    reference_image_base64: Optional[str] = None


# ══════════════════════════════════════════════════════════════
# 通用辅助函数
# ══════════════════════════════════════════════════════════════

def _build_job_content(db_job) -> str:
    """拼接岗位完整信息（含 job_url、salary 等可选字段）供 Agent 使用。"""
    parts = []
    if getattr(db_job, "job_url", None):
        parts.append(f"岗位链接：{db_job.job_url}")
    if getattr(db_job, "salary", None):
        parts.append(f"薪资：{db_job.salary}")
    if parts:
        return "\n\n".join(parts) + "\n\n" + (db_job.content or "")
    return db_job.content or ""


def _build_resume_title_with_angle(db_job: models.Job, title: Optional[str], angle: str) -> str:
    base = (title or '').strip()
    if not base:
        base = db_job.title or '岗位'
    if angle and angle not in base:
        return f"{base} · {angle}"
    return base


# ══════════════════════════════════════════════════════════════
# Chat 流式辅助
# ══════════════════════════════════════════════════════════════

async def _generate(
    job_content: str,
    resume_content: str,
    messages: list,
    user_background: str = None,
    resume_structured: str = None,
    resume_rendered_html: str = None,
    resume_id: int = None,
):
    # 确保磁盘文件存在
    file_path = ensure_resume_file(resume_id, resume_rendered_html) if resume_id else None

    context_parts = [f"## 目标岗位信息\n\n{job_content}"]
    if resume_content:
        context_parts.append(f"## 当前简历文本\n\n{resume_content}")
    if user_background:
        context_parts.append(f"## 用户补充的个人经历\n\n{user_background}")
    if file_path:
        context_parts.append(f"## 简历文件路径\n\n{file_path}\n（使用 write_file 工具写入此路径来修改简历；完整HTML简历内容必须调用read_file工具读取磁盘文件获取）")

    context = "\n\n---\n\n".join(context_parts)
    system_with_context = f"{SYSTEM_PROMPT}\n\n---\n\n{context}"

    def _build_message_content(msg: dict):
        role = msg.get("role", "user")
        text = msg.get("content", "")
        images = msg.get("images") or []

        if images and role == "user":
            content_parts = []
            for img in images:
                if img.startswith("data:"):
                    content_parts.append({"type": "image_url", "image_url": {"url": img}})
                else:
                    content_parts.append({"type": "image_url", "image_url": {"url": img}})
            if text:
                content_parts.append({"type": "text", "text": text})
            return content_parts
        return text

    api_messages = [{"role": m["role"], "content": _build_message_content(m)} for m in messages]

    MAX_TOOL_ROUNDS = 10

    try:
        for _round in range(MAX_TOOL_ROUNDS):
            round_text = ""
            tool_calls_received = None

            async for event in stream_with_tools(system_with_context, api_messages, RESUME_TOOLS):
                etype = event.get("type")
                if etype == "text":
                    chunk = event["content"]
                    round_text += chunk
                    yield f"data: {json.dumps({'type': 'text', 'content': chunk})}\n\n"
                elif etype == "tool_calls":
                    tool_calls_received = event["calls"]
                # done: 本轮流结束，继续处理 tool_calls

            # 没有工具调用 → 对话结束
            if not tool_calls_received:
                break

            # 把 assistant 消息（含 tool_calls）加入对话
            assistant_msg: dict = {"role": "assistant", "content": round_text or ""}
            assistant_msg["tool_calls"] = [
                {
                    "id": c["id"],
                    "type": "function",
                    "function": {
                        "name": c["name"],
                        "arguments": c.get("raw_arguments") or json.dumps(c["arguments"], ensure_ascii=False),
                    },
                }
                for c in tool_calls_received
            ]
            api_messages.append(assistant_msg)

            # 执行每个工具调用
            for call in tool_calls_received:
                # 通知前端正在执行工具（arguments 可能很大，只发摘要）
                arg_preview = call["arguments"].copy() if isinstance(call["arguments"], dict) else {}
                if "content" in arg_preview and len(str(arg_preview["content"])) > 200:
                    arg_preview["content"] = str(arg_preview["content"])[:200] + "..."
                yield f"data: {json.dumps({'type': 'tool_call', 'name': call['name'], 'arguments': arg_preview}, ensure_ascii=False)}\n\n"

                # 执行工具
                result = _execute_tool(call["name"], call["arguments"], resume_id)

                # 通知前端工具执行结果（只发预览，避免大内容刷屏）
                result_preview = result[:500] + "..." if len(result) > 500 else result
                yield f"data: {json.dumps({'type': 'tool_result', 'name': call['name'], 'result': result_preview}, ensure_ascii=False)}\n\n"

                # 把完整结果加入对话（AI 需要完整内容）
                api_messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": result,
                })

            # 继续下一轮，AI 会处理工具结果并继续对话

    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'content': f'模型输出中断: {str(e)[:300]}'})}\n\n"
        return

    yield f"data: {json.dumps({'type': 'done'})}\n\n"


# ══════════════════════════════════════════════════════════════
# 面试模拟辅助
# ══════════════════════════════════════════════════════════════

async def _stream_sim(
    job_content: str,
    resume_content: str,
    messages: list,
    user_background: Optional[str],
    questionnaire_markdown: Optional[str] = None,
):
    context_parts = [f"## 目标岗位 JD\n\n{job_content}"]
    if resume_content:
        context_parts.append(f"## 候选人简历\n\n{resume_content}")
    if user_background:
        context_parts.append(f"## 候选人补充经历\n\n{user_background}")
    if questionnaire_markdown and questionnaire_markdown.strip():
        context_parts.append(questionnaire_markdown.strip())
    context = "\n\n---\n\n".join(context_parts)
    system = f"{INTERVIEW_SIM_SYSTEM}\n\n---\n\n{context}"

    api_messages = [{"role": m["role"], "content": m["content"]} for m in messages]
    try:
        async for text in stream_response(system, api_messages):
            yield f"data: {json.dumps({'type': 'text', 'content': text})}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'content': f'模型输出中断: {str(e)[:300]}'})}\n\n"
        return
    yield f"data: {json.dumps({'type': 'done'})}\n\n"


def _db_job_questions_as_bank(
    db: Session,
    job_id: int,
    resume_id: Optional[int],
    background_profile_id: Optional[int],
) -> List[BankQuestion]:
    q = db.query(models.JobInterviewQuestion).filter(models.JobInterviewQuestion.job_id == job_id)
    if resume_id is not None:
        q = q.filter(models.JobInterviewQuestion.resume_id == resume_id)
    if background_profile_id is not None:
        q = q.filter(models.JobInterviewQuestion.background_profile_id == background_profile_id)
    rows = q.order_by(models.JobInterviewQuestion.id.asc()).all()
    return [
        BankQuestion(
            id=f"jobq-{r.id}",
            category=r.category,
            text=r.text,
            tags=[],
        )
        for r in rows
    ]


def _format_transcript(messages: list) -> str:
    lines = []
    for m in messages:
        role = m.get("role", "")
        content = (m.get("content") or "").strip()
        if not content:
            continue
        if role == "user":
            lines.append(f"【候选人】\n{content}\n")
        elif role == "assistant":
            lines.append(f"【面试官】\n{content}\n")
    return "\n---\n\n".join(lines)


# ══════════════════════════════════════════════════════════════
# 导出辅助
# ══════════════════════════════════════════════════════════════

def _clean_content(content: str) -> str:
    content = re.sub(r"===RESUME_START===\n?", "", content)
    return re.sub(r"===RESUME_END===\n?", "", content)


def _safe_filename(title: Optional[str], suffix: str, fallback: str) -> str:
    if title:
        safe_title = re.sub(r'[<>:"/\\|?*]', "", title).strip()[:50]
        if safe_title:
            return f"{safe_title}.{suffix}"
    return fallback


def _content_disposition(filename: str) -> str:
    # HTTP 头仅支持 latin-1；非 ASCII 文件名需走 RFC 5987 的 filename* 编码
    quoted = urllib.parse.quote(filename)
    return f"attachment; filename*=UTF-8''{quoted}"


def _strip_md_inline(text: str) -> str:
    """Remove markdown bold/italic/code from text for Word export."""
    s = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    s = re.sub(r"\*(.*?)\*", r"\1", s)
    s = re.sub(r"_(.*?)_", r"\1", s)
    s = re.sub(r"__(.*?)__", r"\1", s)
    s = re.sub(r"`(.*?)`", r"\1", s)
    return s


def md_to_pdf_content(md_text: str, font_size: int = 10):
    """font_size: 9, 10, 11, 12 (body text base)."""
    font_path_regular = None
    font_candidates = [
        os.path.expandvars(r"%WINDIR%\Fonts\msyh.ttc"),
        os.path.expandvars(r"%WINDIR%\Fonts\msyhbd.ttc"),
        os.path.expandvars(r"%WINDIR%\Fonts\simsun.ttc"),
        "C:\\Windows\\Fonts\\msyh.ttc",
        "C:\\Windows\\Fonts\\simsun.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    for fp in font_candidates:
        if not fp:
            continue
        normalized = os.path.normpath(os.path.expanduser(os.path.expandvars(fp)))
        if os.path.exists(normalized):
            font_path_regular = normalized
            break

    if font_path_regular:
        try:
            pdfmetrics.registerFont(TTFont("ChineseFont", font_path_regular))
            base_font = "ChineseFont"
        except Exception:
            base_font = "Helvetica"
    else:
        base_font = "Helvetica"

    getSampleStyleSheet()
    h1_size = max(14, font_size + 8)
    h2_size = max(11, font_size + 3)
    h3_size = max(10, font_size + 1)
    style_h1 = ParagraphStyle("H1", fontName=base_font, fontSize=h1_size, spaceAfter=6, spaceBefore=10, textColor=colors.HexColor("#1a1a2e"), leading=h1_size + 4)
    style_h2 = ParagraphStyle("H2", fontName=base_font, fontSize=h2_size, spaceAfter=4, spaceBefore=8, textColor=colors.HexColor("#16213e"), leading=h2_size + 4)
    style_h3 = ParagraphStyle("H3", fontName=base_font, fontSize=h3_size, spaceAfter=3, spaceBefore=5, textColor=colors.HexColor("#0f3460"), leading=h3_size + 3)
    style_body = ParagraphStyle("Body", fontName=base_font, fontSize=font_size, spaceAfter=2, spaceBefore=1, leading=font_size + 4, textColor=colors.HexColor("#333333"))
    style_bullet = ParagraphStyle("Bullet", fontName=base_font, fontSize=font_size, spaceAfter=2, spaceBefore=1, leading=font_size + 4, leftIndent=15, textColor=colors.HexColor("#333333"))

    story = []
    for line in md_text.split("\n"):
        stripped = re.sub(r"\*\*(.*?)\*\*", r"\1", line.rstrip())
        stripped = re.sub(r"\*(.*?)\*", r"\1", stripped)
        stripped = re.sub(r"`(.*?)`", r"\1", stripped)

        if line.startswith("# "):
            story.append(Paragraph(stripped[2:].strip(), style_h1))
        elif line.startswith("## "):
            story.append(Spacer(1, 0.1 * cm))
            story.append(Paragraph(stripped[3:].strip(), style_h2))
            story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cccccc")))
        elif line.startswith("### "):
            story.append(Paragraph(stripped[4:].strip(), style_h3))
        elif line.startswith("- ") or line.startswith("* "):
            text = stripped[2:].strip()
            if text:
                story.append(Paragraph(f"• {text}", style_bullet))
        elif line.strip() in ["---", "***"]:
            story.append(HRFlowable(width="100%", thickness=0.3, color=colors.HexColor("#dddddd")))
        elif not line.strip():
            story.append(Spacer(1, 0.2 * cm))
        elif stripped.strip():
            story.append(Paragraph(stripped, style_body))

    return story


def _add_paragraph_with_font(doc: Document, text: str, style_name: Optional[str] = None, font_pt: int = 11):
    p = doc.add_paragraph(text, style=style_name)
    for run in p.runs:
        run.font.size = Pt(font_pt)
    return p


# ══════════════════════════════════════════════════════════════
# 文件解析辅助（uploads）
# ══════════════════════════════════════════════════════════════

def _extract_from_pdf(content: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    parts = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n".join(parts).strip()


def _extract_from_docx(content: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(content))
    parts = []
    for p in doc.paragraphs:
        if p.text.strip():
            parts.append(p.text)
    for table in doc.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts).strip()


def _docx_to_pdf_bytes(content: bytes) -> Optional[bytes]:
    """通过 LibreOffice 将 docx 转为 PDF 字节。LibreOffice 不可用时返回 None。"""
    import subprocess, tempfile, os, shutil
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        for p in [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ]:
            if os.path.exists(p):
                soffice = p
                break
    if not soffice:
        return None
    with tempfile.TemporaryDirectory() as tmpdir:
        docx_path = os.path.join(tmpdir, "input.docx")
        with open(docx_path, "wb") as f:
            f.write(content)
        try:
            subprocess.run(
                [soffice, "--headless", "--convert-to", "pdf", "--outdir", tmpdir, docx_path],
                capture_output=True, timeout=60,
            )
        except Exception:
            return None
        pdf_path = os.path.join(tmpdir, "input.pdf")
        if not os.path.exists(pdf_path):
            return None
        with open(pdf_path, "rb") as f:
            return f.read()


async def _ai_vl_extract_from_pdf(pdf_bytes: bytes) -> str:
    """使用多模态 AI 从 PDF 页面图片中提取文本（与 PDF VL 路径一致）。"""
    from ..services.resume_parser import _pdf_pages_png_base64
    from ..services.resume_provider import is_current_model_multimodal

    settings = load_settings()
    if not is_current_model_multimodal(settings):
        raise HTTPException(
            status_code=400,
            detail="需要多模态模型识别。请在「模型管理」中选择支持多模态的模型。",
        )
    images_b64 = _pdf_pages_png_base64(pdf_bytes, 5)
    if not images_b64:
        return ""
    parts = []
    for b64 in images_b64:
        parts.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
    parts.append({
        "type": "text",
        "text": "请识别以上简历页面中的全部文字，按原始结构完整输出。保留所有时间、岗位、项目描述等关键信息。",
    })
    out = await complete_response(
        "你是简历文字识别助手。请完整准确地识别用户提供的简历图片中的所有文字，保持原始结构，不编造、不遗漏。",
        [{"role": "user", "content": parts}],
    )
    return out.strip()


def _ocr_from_image(content: bytes) -> str:
    """图片：交给多模态 LLM 完成文本提取（不使用本地 OCR 库）。"""
    import base64
    b64 = base64.b64encode(content).decode("ascii")
    from PIL import Image
    image = Image.open(io.BytesIO(content))
    fmt = (image.format or "PNG").upper()
    mime = f"image/{fmt.lower()}"
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                {"type": "text", "text": "请识别这张简历图片中的全部文字，按原始结构完整输出。保留所有时间、岗位、项目描述等关键信息，不要遗漏。"},
            ],
        }
    ]
    from ..services.resume_provider import complete_response_sync
    try:
        out = complete_response_sync(
            "你是简历文字识别助手。请完整准确地识别用户提供的简历图片中的所有文字，保持原始结构，不编造、不遗漏。",
            messages,
            max_tokens=8192,
            timeout=300.0,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"多模态模型识别图片失败: {str(e)[:300]}") from e
    if not out.strip():
        raise HTTPException(status_code=502, detail="模型未识别到文字，请检查图片清晰度")
    return out.strip()


def _extract_from_plain_text(content: bytes) -> str:
    """纯文本 / Markdown：按 BOM → UTF-8 → 国标中文编码依次尝试解码。"""
    if not content:
        return ""
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return content.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace").strip()


def extract_text_from_file(filename: str, content: bytes):
    lower = filename.lower()
    if lower.endswith((".txt", ".md", ".markdown")):
        return _extract_from_plain_text(content), "text_plain"
    if lower.endswith(".pdf"):
        return _extract_from_pdf(content), "pdf"
    if lower.endswith(".doc") or lower.endswith(".docx"):
        return _extract_from_docx(content), "word"
    if lower.endswith((".png", ".jpg", ".jpeg", ".bmp", ".webp")):
        return _ocr_from_image(content), "ocr"
    raise HTTPException(status_code=400, detail="仅支持 PDF/Word/图片/纯文本(.txt、.md) 文件")


def _parse_job_fields(text: str):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    title = ""
    company = None

    for line in lines[:8]:
        if not title and any(k in line for k in ["工程师", "经理", "专家", "负责人", "Developer", "Manager"]):
            title = re.sub(r"^(职位|岗位)[:：]\s*", "", line)
            continue
        if not company and any(k in line for k in ["公司", "企业", "Company"]):
            company = re.sub(r"^(公司|企业|Company)[:：]\s*", "", line)

    if not title and lines:
        title = lines[0][:80]

    return JobParseResponse(
        title=title or "未识别岗位名称",
        company=company,
        content=text.strip(),
        source="auto_parse",
    )


# ══════════════════════════════════════════════════════════════
# 评分卡辅助（evaluation）
# ══════════════════════════════════════════════════════════════

_COMPETENCY_MODELS: Dict[str, List[str]] = {}


def _load_competency_models() -> Dict[str, List[str]]:
    global _COMPETENCY_MODELS
    if _COMPETENCY_MODELS:
        return _COMPETENCY_MODELS
    fp = DATA_DIR / "competency_models.json"
    try:
        data = json.loads(fp.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            _COMPETENCY_MODELS = {
                str(k): [str(x) for x in v if str(x).strip()]
                for k, v in data.items()
                if isinstance(v, list)
            }
    except Exception:
        _COMPETENCY_MODELS = {}
    return _COMPETENCY_MODELS


def _pick_competency_set(job_title: str) -> List[str]:
    comp_models = _load_competency_models()
    title = (job_title or "").lower()
    if any(k in title for k in ["产品", "product", "pm"]):
        return comp_models.get("product", comp_models.get("default", []))
    if any(k in title for k in ["开发", "工程", "engineer", "后端", "前端"]):
        return comp_models.get("engineering", comp_models.get("default", []))
    if any(k in title for k in ["运营", "operation"]):
        return comp_models.get("operations", comp_models.get("default", []))
    return comp_models.get("default", [])


def _pick_competency_set_by_profile(profile: str, job_title: str) -> List[str]:
    comp_models = _load_competency_models()
    p = (profile or "").strip()
    if p and p in comp_models:
        return comp_models[p]
    return _pick_competency_set(job_title)


def _normalize_scorecard(data: Dict[str, Any]) -> schemas.EvaluationScorecardResponse:
    overall_score = int(max(0, min(100, int(data.get("overall_score", 0)))))
    overall_summary = str(data.get("overall_summary", "")).strip()
    needs_verification = [str(x).strip() for x in data.get("needs_verification", []) if str(x).strip()]
    items_raw = data.get("items", []) if isinstance(data.get("items", []), list) else []
    items: List[schemas.ScoreCardItem] = []
    for it in items_raw:
        if not isinstance(it, dict):
            continue
        ev_list = it.get("evidence", []) if isinstance(it.get("evidence", []), list) else []
        evidence: List[schemas.EvidenceRef] = []
        for ev in ev_list:
            if not isinstance(ev, dict):
                continue
            quote = str(ev.get("quote", "")).strip()
            if not quote:
                continue
            evidence.append(
                schemas.EvidenceRef(
                    source=str(ev.get("source", "对话")).strip() or "对话",
                    quote=quote,
                    why=str(ev.get("why", "")).strip() or None,
                )
            )
        items.append(
            schemas.ScoreCardItem(
                competency=str(it.get("competency", "综合能力")).strip() or "综合能力",
                score=int(max(0, min(100, int(it.get("score", 0))))),
                confidence=str(it.get("confidence", "中")).strip() or "中",
                summary=str(it.get("summary", "")).strip(),
                evidence=evidence,
                gap=str(it.get("gap", "")).strip() or None,
                suggestion=str(it.get("suggestion", "")).strip() or None,
            )
        )
    return schemas.EvaluationScorecardResponse(
        overall_score=overall_score,
        overall_summary=overall_summary,
        items=items,
        needs_verification=needs_verification,
    )


# ══════════════════════════════════════════════════════════════
# Pydantic 模型（settings / uploads）
# ══════════════════════════════════════════════════════════════

class SettingsTest(BaseModel):
    provider: str
    model: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None


class SettingsUpdate(BaseModel):
    provider: str
    model: str
    api_keys: Optional[Dict[str, str]] = None
    custom_base_url: Optional[str] = None
    custom_api_key: Optional[str] = None
    custom_model: Optional[str] = None


class CustomModelCreate(BaseModel):
    """添加自定义模型请求体，所有字段对齐前端 AddModelModal.tsx。"""
    api_format: str = "openai_chat"
    base_url: str
    full_url: bool = False
    model_id: str
    multimodal: bool = False
    api_key: str
    # 高级配置
    model_series: str = "default"
    display_name: str = ""
    context_input: int = 184000
    context_output: int = 16000
    tool_call_rounds: int = 0


class CustomModelTest(BaseModel):
    """连通性测试请求体（前端通过后端代理，避免浏览器 CORS 限制）。
    api_key 为空或 '••••••' 时，若提供了 existing_model_id，则用后端已存储的密钥测试。
    """
    base_url: str
    full_url: bool = False
    model_id: str
    api_key: str = ""
    existing_model_id: Optional[str] = None


class CustomModelUpdate(BaseModel):
    """更新自定义模型请求体，所有字段可选。api_key 留空或 '••••••' 表示保留原值。"""
    api_format: Optional[str] = None
    base_url: Optional[str] = None
    full_url: Optional[bool] = None
    model_id: Optional[str] = None
    multimodal: Optional[bool] = None
    api_key: Optional[str] = None
    model_series: Optional[str] = None
    display_name: Optional[str] = None
    context_input: Optional[int] = None
    context_output: Optional[int] = None
    tool_call_rounds: Optional[int] = None


class ParseResumeBackgroundResponse(BaseModel):
    filename: str
    text: str
    parser: str
    warning: Optional[str] = None


class JobParseResponse(BaseModel):
    title: str
    company: Optional[str] = None
    content: str
    source: str


# ══════════════════════════════════════════════════════════════
# 1. jobs 路由
# ══════════════════════════════════════════════════════════════

@router.get("/jobs/competency-profiles")
def list_competency_profiles():
    fp = DATA_DIR / "competency_models.json"
    try:
        data = json.loads(fp.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"profiles": ["default"]}
        return {"profiles": list(data.keys())}
    except Exception:
        return {"profiles": ["default"]}


@router.get("/jobs", response_model=List[schemas.JobResponse])
def list_jobs(db: Session = Depends(get_db)):
    return db.query(models.Job).order_by(models.Job.created_at.desc()).all()


@router.post("/jobs", response_model=schemas.JobResponse)
def create_job(job: schemas.JobCreate, db: Session = Depends(get_db)):
    db_job = models.Job(**job.model_dump())
    db.add(db_job)
    db.commit()
    db.refresh(db_job)
    return db_job


@router.get("/jobs/{job_id}", response_model=schemas.JobResponse)
def get_job(job_id: int, db: Session = Depends(get_db)):
    db_job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not db_job:
        raise HTTPException(status_code=404, detail="Job not found")
    return db_job


@router.put("/jobs/{job_id}", response_model=schemas.JobResponse)
def update_job(job_id: int, job: schemas.JobUpdate, db: Session = Depends(get_db)):
    db_job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not db_job:
        raise HTTPException(status_code=404, detail="Job not found")
    update_data = job.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_job, field, value)
    db.commit()
    db.refresh(db_job)
    return db_job


@router.delete("/jobs/{job_id}")
def delete_job(job_id: int, db: Session = Depends(get_db)):
    db_job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not db_job:
        raise HTTPException(status_code=404, detail="Job not found")
    db.delete(db_job)
    db.commit()
    return {"message": "Job deleted"}


# ══════════════════════════════════════════════════════════════
# 2. resumes 路由
# ══════════════════════════════════════════════════════════════

@router.get("/resumes", response_model=List[schemas.ResumeResponse])
def list_resumes(
    job_id: int = None,
    background_profile_id: int = None,
    db: Session = Depends(get_db),
):
    query = db.query(models.Resume)
    if job_id:
        query = query.filter(models.Resume.job_id == job_id)
    if background_profile_id is not None:
        query = query.filter(
            (models.Resume.background_profile_id == background_profile_id)
            | (models.Resume.background_profile_id.is_(None))
        )
    return query.order_by(models.Resume.created_at.desc()).all()


def _normalize_structured_field(raw: Optional[str]) -> Optional[str]:
    """校验并存的结构化 JSON 字符串，非法时返回 None。"""
    if not raw or not raw.strip():
        return None
    try:
        parsed = normalize_structured(json.loads(raw))
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return json.dumps(parsed, ensure_ascii=False)


@router.post("/resumes", response_model=schemas.ResumeResponse)
def create_resume(resume: schemas.ResumeCreate, db: Session = Depends(get_db)):
    db_job = db.query(models.Job).filter(models.Job.id == resume.job_id).first()
    if not db_job:
        raise HTTPException(status_code=404, detail="Job not found")

    bg_id = resume.background_profile_id
    angle = (resume.angle or '').strip() if resume.angle else None
    if not angle:
        q = db.query(models.Resume).filter(models.Resume.job_id == resume.job_id)
        if bg_id is not None:
            q = q.filter(models.Resume.background_profile_id == bg_id)
        else:
            q = q.filter(models.Resume.background_profile_id.is_(None))
        angle_index = q.count() + 1
        angle = f"角度{angle_index}"

    existing_count = db.query(models.Resume).filter(models.Resume.job_id == resume.job_id)
    if bg_id is not None:
        existing_count = existing_count.filter(models.Resume.background_profile_id == bg_id)
    else:
        existing_count = existing_count.filter(models.Resume.background_profile_id.is_(None))
    existing_count = existing_count.filter(models.Resume.angle == angle).count()

    data = resume.model_dump(exclude={'angle', 'background_profile_id', 'title'})
    data["structured"] = _normalize_structured_field(data.get("structured"))
    content = (data.get("content") or "").strip()
    if not content and data["structured"]:
        content = structured_to_text(json.loads(data["structured"]))
    data["content"] = content

    db_resume = models.Resume(
        **data,
        angle=angle,
        background_profile_id=bg_id,
        title=_build_resume_title_with_angle(db_job, resume.title, angle),
        version=existing_count + 1,
    )
    db.add(db_resume)
    db.commit()
    db.refresh(db_resume)
    return db_resume


@router.get("/resumes/{resume_id}", response_model=schemas.ResumeResponse)
def get_resume(resume_id: int, db: Session = Depends(get_db)):
    db_resume = db.query(models.Resume).filter(models.Resume.id == resume_id).first()
    if not db_resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    return db_resume


@router.put("/resumes/{resume_id}", response_model=schemas.ResumeResponse)
def update_resume(resume_id: int, resume: schemas.ResumeUpdate, db: Session = Depends(get_db)):
    db_resume = db.query(models.Resume).filter(models.Resume.id == resume_id).first()
    if not db_resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    update_data = resume.model_dump(exclude_unset=True)
    if "structured" in update_data:
        normalized = _normalize_structured_field(update_data["structured"])
        update_data["structured"] = normalized
        if normalized and "content" not in update_data:
            update_data["content"] = structured_to_text(json.loads(normalized))
    for field, value in update_data.items():
        setattr(db_resume, field, value)
    db.commit()
    db.refresh(db_resume)

    if db_resume.rendered_html:
        write_resume_file(resume_id, db_resume.rendered_html)

    return db_resume


@router.delete("/resumes/{resume_id}")
def delete_resume(resume_id: int, db: Session = Depends(get_db)):
    db_resume = db.query(models.Resume).filter(models.Resume.id == resume_id).first()
    if not db_resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    db.delete(db_resume)
    db.commit()
    disk_ok = delete_resume_dir(resume_id)
    if not disk_ok:
        raise HTTPException(status_code=500, detail="简历记录已删除但磁盘文件清理失败，请手动清理")
    return {"message": "Resume deleted"}


@router.post("/resumes/generate", response_model=schemas.ResumeResponse)
async def generate_resume(body: GenerateResumeRequest, db: Session = Depends(get_db)):
    """AI 根据候选人背景 + 目标岗位 JD 直接生成完整简历 HTML，写入磁盘。"""
    db_job = db.query(models.Job).filter(models.Job.id == body.job_id).first()
    if not db_job:
        raise HTTPException(status_code=404, detail="Job not found")

    jd = _build_job_content(db_job).strip()
    if not jd:
        raise HTTPException(status_code=400, detail="岗位 JD 为空，无法生成简历")

    background = (body.background or "").strip()
    if not background:
        raise HTTPException(status_code=400, detail="请提供候选人背景信息")

    user_msg = f"## 目标岗位 JD\n\n{jd}\n\n---\n\n## 候选人背景信息\n\n{background}"
    accent = body.accent if body.accent in ACCENTS else "#2563eb"
    user_msg += f"\n\n---\n\n请使用主题色 {accent}，生成一份完整简历 HTML。"

    raw = await complete_response(SYSTEM_GENERATE_RESUME, [{"role": "user", "content": user_msg}])
    html = _strip_code_fence(raw).strip()

    if not html or ("<!DOCTYPE" not in html and "<html" not in html):
        raise HTTPException(status_code=502, detail="模型未生成有效的 HTML 简历，请重试或更换模型")

    q = db.query(models.Resume).filter(models.Resume.job_id == body.job_id)
    angle_index = q.count() + 1
    angle = f"角度{angle_index}"
    existing_count = q.filter(models.Resume.angle == angle).count()
    title = _build_resume_title_with_angle(db_job, None, angle)

    db_resume = models.Resume(
        job_id=body.job_id,
        title=title,
        content=background,
        structured=None,
        rendered_html=html,
        current_template=body.style or "classic",
        angle=angle,
        version=existing_count + 1,
    )
    db.add(db_resume)
    db.commit()
    db.refresh(db_resume)

    write_resume_file(db_resume.id, html)

    return db_resume


@router.post("/resumes/generate/stream")
async def generate_resume_stream(body: GenerateResumeRequest, db: Session = Depends(get_db)):
    """流式版：AI 根据候选人背景 + 目标岗位 JD 逐步生成完整简历 HTML。"""
    db_job = db.query(models.Job).filter(models.Job.id == body.job_id).first()
    if not db_job:
        raise HTTPException(status_code=404, detail="Job not found")

    jd = _build_job_content(db_job).strip()
    if not jd:
        raise HTTPException(status_code=400, detail="岗位 JD 为空，无法生成简历")

    background = (body.background or "").strip()
    if not background:
        raise HTTPException(status_code=400, detail="请提供候选人背景信息")

    user_msg = f"## 目标岗位 JD\n\n{jd}\n\n---\n\n## 候选人背景信息\n\n{background}"
    accent = body.accent if body.accent in ACCENTS else "#2563eb"
    user_msg += f"\n\n---\n\n请使用主题色 {accent}，生成一份完整简历 HTML。"

    async def _stream_gen():
        html_parts: list[str] = []
        try:
            async for text in stream_response(SYSTEM_GENERATE_RESUME, [{"role": "user", "content": user_msg}]):
                html_parts.append(text)
                yield f"data: {json.dumps({'type': 'text', 'content': text})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': f'模型输出中断: {str(e)[:300]}'})}\n\n"
            return

        full_html = "".join(html_parts).strip()
        full_html = _strip_code_fence(full_html)

        if full_html and ("<!DOCTYPE" in full_html or "<html" in full_html):
            q = db.query(models.Resume).filter(models.Resume.job_id == body.job_id)
            angle_index = q.count() + 1
            angle = f"角度{angle_index}"
            existing_count = q.filter(models.Resume.angle == angle).count()
            title = _build_resume_title_with_angle(db_job, None, angle)

            db_resume = models.Resume(
                job_id=body.job_id,
                title=title,
                content=background,
                structured=None,
                rendered_html=full_html,
                current_template=body.style or "classic",
                angle=angle,
                version=existing_count + 1,
            )
            db.add(db_resume)
            db.commit()
            db.refresh(db_resume)

            write_resume_file(db_resume.id, full_html)

            yield f"data: {json.dumps({'type': 'done', 'resume_id': db_resume.id}, ensure_ascii=False)}\n\n"
        else:
            yield f"data: {json.dumps({'type': 'error', 'content': '模型未生成有效的 HTML 简历，请重试或更换模型'})}\n\n"

    return StreamingResponse(
        sse_with_heartbeat(_stream_gen()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/resumes/{resume_id}/restyle/stream")
async def restyle_resume_stream(resume_id: int, body: RestyleResumeRequest, db: Session = Depends(get_db)):
    """流式重新排版简历：基于已有简历数据，按指定风格重新生成 HTML，更新当前简历。"""
    db_resume = db.query(models.Resume).filter(models.Resume.id == resume_id).first()
    if not db_resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    resume_content = _extract_resume_text(db_resume)
    resume_id_val = db_resume.id

    style = body.style if body.style in RESTYLE_STYLES else "classic"
    accent = body.accent if body.accent in ACCENTS else "#2563eb"

    avatar_path = None
    if body.avatar_base64:
        import base64
        avatar_dir = resume_dir(resume_id)
        avatar_dir.mkdir(parents=True, exist_ok=True)
        data_uri = body.avatar_base64
        if data_uri.startswith("data:"):
            header, b64data = data_uri.split(",", 1)
            mime = header.split(":")[1].split(";")[0]
            ext = mime.split("/")[-1].replace("jpeg", "jpg")
        else:
            b64data = data_uri
            ext = "png"
            mime = "image/png"
        avatar_file = avatar_dir / f"avatar.{ext}"
        avatar_file.write_bytes(base64.b64decode(b64data))
        avatar_path = str(avatar_file.resolve())

    text_content = f"## 简历原始信息\n\n{resume_content}\n\n---\n\n"
    text_content += f"目标风格：{style}\n主题色：{accent}\n"
    if body.description and body.description.strip():
        text_content += f"用户补充要求：{body.description.strip()}\n"

    has_ref_image = bool(body.reference_image_base64)
    if has_ref_image:
        from ..services.resume_provider import is_current_model_multimodal
        settings = load_settings()
        if not is_current_model_multimodal(settings):
            raise HTTPException(
                status_code=400,
                detail="当前模型不支持多模态，无法分析参考风格图。请切换到支持多模态的模型（如 Claude、GPT-4o 等），或不使用参考图。",
            )
        text_content += "用户已提供参考风格图，请分析其排版风格并融入生成。\n"

    if avatar_path:
        import base64 as _b64
        _ap = Path(avatar_path)
        _avatar_b64 = _b64.b64encode(_ap.read_bytes()).decode()
        _mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}.get(_ap.suffix.lower(), "image/png")
        _data_uri = f"data:{_mime};base64,{_avatar_b64}"
        text_content += f"\n用户头像已以 base64 嵌入，请直接使用 <img src=\"{_data_uri}\"> 引用头像。\n"

    text_content += "\n请根据以上信息重新排版生成完整简历 HTML。"

    user_msg_content: Any = text_content
    if has_ref_image and body.reference_image_base64:
        user_msg_content = [
            {"type": "image_url", "image_url": {"url": body.reference_image_base64}},
            {"type": "text", "text": text_content},
        ]

    async def _stream_restyle():
        html_parts: list[str] = []
        try:
            msg = [{"role": "user", "content": user_msg_content}]
            async for text in stream_response(SYSTEM_RESTYLE_RESUME, msg):
                html_parts.append(text)
                yield f"data: {json.dumps({'type': 'text', 'content': text})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': f'模型输出中断: {str(e)[:300]}'})}\n\n"
            return

        full_html = "".join(html_parts).strip()
        full_html = _strip_code_fence(full_html)

        if full_html and ("<!DOCTYPE" in full_html or "<html" in full_html):
            from ..services.resume_db import SessionLocal
            save_db = SessionLocal()
            try:
                save_resume = save_db.query(models.Resume).filter(models.Resume.id == resume_id_val).first()
                if save_resume:
                    save_resume.rendered_html = full_html
                    save_resume.current_template = style
                    save_db.commit()
            finally:
                save_db.close()

            write_resume_file(resume_id_val, full_html)

            yield f"data: {json.dumps({'type': 'done', 'resume_id': resume_id_val}, ensure_ascii=False)}\n\n"
        else:
            yield f"data: {json.dumps({'type': 'error', 'content': '模型未生成有效的 HTML 简历，请重试或更换模型'})}\n\n"

    return StreamingResponse(
        sse_with_heartbeat(_stream_restyle()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _extract_resume_text(db_resume) -> str:
    """从 Resume 数据库记录中提取文本内容，用于重新排版。"""
    if db_resume.structured:
        try:
            return structured_to_text(json.loads(db_resume.structured))
        except Exception:
            pass
    if db_resume.content and db_resume.content.strip():
        return db_resume.content.strip()
    if db_resume.rendered_html:
        from html.parser import HTMLParser
        class _TextExtractor(HTMLParser):
            def __init__(self):
                super().__init__()
                self.parts: list[str] = []
            def handle_data(self, data):
                t = data.strip()
                if t:
                    self.parts.append(t)
        ext = _TextExtractor()
        ext.feed(db_resume.rendered_html)
        return "\n".join(ext.parts)
    return ""


# ══════════════════════════════════════════════════════════════
# 3. chat 路由
# ══════════════════════════════════════════════════════════════

@router.post("/chat/stream")
async def chat_stream(request: schemas.ChatRequest, db: Session = Depends(get_db)):
    db_job = db.query(models.Job).filter(models.Job.id == request.job_id).first()
    if not db_job:
        raise HTTPException(status_code=404, detail="Job not found")

    db_resume = db.query(models.Resume).filter(models.Resume.id == request.resume_id).first()
    resume_content = db_resume.content if db_resume else ""
    resume_structured = db_resume.structured if db_resume else None
    resume_rendered_html = db_resume.rendered_html if db_resume else None

    messages = [msg.model_dump() for msg in request.messages]

    return StreamingResponse(
        sse_with_heartbeat(_generate(
            job_content=_build_job_content(db_job),
            resume_content=resume_content,
            messages=messages,
            user_background=request.user_background,
            resume_structured=resume_structured,
            resume_rendered_html=resume_rendered_html,
            resume_id=request.resume_id,
        )),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.websocket("/ws/resume/{resume_id}")
async def resume_ws(ws: WebSocket, resume_id: int):
    """简历文件变更 WebSocket：AI 写入文件后自动推送 file_changed 事件。"""
    await ws.accept()
    mgr = get_workspace_manager()
    mgr.subscribe(resume_id, ws)
    try:
        while True:
            await ws.receive_text()  # 保活，忽略客户端消息
    except WebSocketDisconnect:
        pass
    finally:
        mgr.unsubscribe(resume_id, ws)


@router.get("/resumes/{resume_id}/file")
def get_resume_file(resume_id: int):
    """获取简历磁盘文件的最新内容（前端收到 WebSocket 通知后调用）。"""
    content = read_resume_file(resume_id)
    file_path = str(resume_file_path(resume_id))
    return {"resume_id": resume_id, "html": content, "path": file_path}


@router.get("/chat/current-provider")
def get_current_provider():
    """Return the currently configured provider and model info for the UI."""
    settings = load_settings()
    provider_id = settings.get("provider", "anthropic")
    model_id = settings.get("model", "")
    pconfig = PROVIDERS.get(provider_id, {})
    model_name = next(
        (m["name"] for m in pconfig.get("models", []) if m["id"] == model_id),
        model_id,
    )
    return {
        "provider": provider_id,
        "provider_name": pconfig.get("name_cn", provider_id),
        "model": model_id,
        "model_name": model_name,
    }


@router.get("/chat/conversations/{resume_id}")
def get_conversation(resume_id: int, db: Session = Depends(get_db)):
    """Get conversation for a resume. Returns empty messages if none saved."""
    db_conv = (
        db.query(models.Conversation)
        .filter(models.Conversation.resume_id == resume_id)
        .first()
    )
    if not db_conv:
        return {"resume_id": resume_id, "messages": []}
    return {"resume_id": resume_id, "messages": json.loads(db_conv.messages)}


@router.post("/chat/conversations")
def save_conversation(body: schemas.ConversationSave, db: Session = Depends(get_db)):
    resume_id = body.resume_id
    messages = body.messages
    db_conv = (
        db.query(models.Conversation)
        .filter(models.Conversation.resume_id == resume_id)
        .first()
    )
    if db_conv:
        db_conv.messages = json.dumps(messages, ensure_ascii=False)
    else:
        db_conv = models.Conversation(
            resume_id=resume_id,
            messages=json.dumps(messages, ensure_ascii=False),
        )
        db.add(db_conv)
    db.commit()
    return {"message": "Conversation saved"}


@router.get("/chat/job-conversations/{job_id}")
def get_job_conversation(job_id: int, db: Session = Depends(get_db)):
    """Get conversation for a job. Returns empty messages if none saved."""
    db_conv = (
        db.query(models.JobConversation)
        .filter(models.JobConversation.job_id == job_id)
        .first()
    )
    if not db_conv:
        return {"job_id": job_id, "messages": []}
    return {"job_id": job_id, "messages": json.loads(db_conv.messages)}


@router.post("/chat/job-conversations")
def save_job_conversation(body: schemas.JobConversationSave, db: Session = Depends(get_db)):
    job_id = body.job_id
    messages = body.messages
    db_job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not db_job:
        raise HTTPException(status_code=404, detail="Job not found")
    db_conv = (
        db.query(models.JobConversation)
        .filter(models.JobConversation.job_id == job_id)
        .first()
    )
    if db_conv:
        db_conv.messages = json.dumps(messages, ensure_ascii=False)
    else:
        db_conv = models.JobConversation(
            job_id=job_id,
            messages=json.dumps(messages, ensure_ascii=False),
        )
        db.add(db_conv)
    db.commit()
    return {"message": "Job conversation saved"}


# ══════════════════════════════════════════════════════════════
# 4. export 路由
# ══════════════════════════════════════════════════════════════

@router.get("/export/markdown/{resume_id}")
def export_markdown(resume_id: int, db: Session = Depends(get_db)):
    db_resume = db.query(models.Resume).filter(models.Resume.id == resume_id).first()
    if not db_resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    content = _clean_content(db_resume.content or "")
    buffer = io.BytesIO(content.encode("utf-8"))
    filename = _safe_filename(db_resume.title, "md", f"resume_{resume_id}.md")
    return StreamingResponse(
        buffer,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": _content_disposition(filename)},
    )


@router.get("/export/pdf/{resume_id}")
def export_pdf(
    resume_id: int,
    db: Session = Depends(get_db),
    font_size: int = 10,
    margin_cm: float = 2.0,
):
    """font_size: 9-12, margin_cm: 1.5, 2.0, 2.5"""
    font_size = max(9, min(12, font_size))
    margin_cm = max(1.0, min(3.0, margin_cm))
    db_resume = db.query(models.Resume).filter(models.Resume.id == resume_id).first()
    if not db_resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    content = _clean_content(db_resume.content)
    buffer = io.BytesIO()
    m = margin_cm * cm
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=m, leftMargin=m, topMargin=m, bottomMargin=m)
    doc.build(md_to_pdf_content(content, font_size))
    buffer.seek(0)

    filename = _safe_filename(db_resume.title, "pdf", f"resume_{resume_id}.pdf")
    return StreamingResponse(buffer, media_type="application/pdf", headers={"Content-Disposition": _content_disposition(filename)})


@router.get("/export/pdf-preview/{resume_id}")
def preview_pdf(
    resume_id: int,
    db: Session = Depends(get_db),
    font_size: int = 10,
    margin_cm: float = 2.0,
):
    response = export_pdf(resume_id, db, font_size, margin_cm)
    disposition = response.headers["Content-Disposition"]
    encoded_name = disposition.split("filename*=UTF-8''")[-1]
    response.headers["Content-Disposition"] = f"inline; filename*=UTF-8''{encoded_name}"
    return response


@router.get("/export/word/{resume_id}")
def export_word(
    resume_id: int,
    db: Session = Depends(get_db),
    font_size: int = 11,
    margin_cm: float = 2.0,
):
    """font_size: 10, 11, 12, 14 (pt). margin_cm: 1.5, 2.0, 2.5"""
    font_size = max(9, min(14, font_size))
    margin_cm = max(1.0, min(3.0, margin_cm))
    db_resume = db.query(models.Resume).filter(models.Resume.id == resume_id).first()
    if not db_resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    content = _clean_content(db_resume.content)
    doc = Document()
    for section in doc.sections:
        section.top_margin = Cm(margin_cm)
        section.bottom_margin = Cm(margin_cm)
        section.left_margin = Cm(margin_cm)
        section.right_margin = Cm(margin_cm)
    for line in content.splitlines():
        text = line.strip()
        if not text:
            doc.add_paragraph("")
            continue
        clean = _strip_md_inline(text)
        h1_pt = min(22, font_size + 8)
        h2_pt = min(16, font_size + 4)
        h3_pt = min(14, font_size + 2)
        if text.startswith("# "):
            p = doc.add_heading(clean[2:].strip(), level=1)
            for run in p.runs:
                run.font.size = Pt(h1_pt)
        elif text.startswith("## "):
            p = doc.add_heading(clean[3:].strip(), level=2)
            for run in p.runs:
                run.font.size = Pt(h2_pt)
        elif text.startswith("### "):
            p = doc.add_heading(clean[4:].strip(), level=3)
            for run in p.runs:
                run.font.size = Pt(h3_pt)
        elif text.startswith("- ") or text.startswith("* "):
            _add_paragraph_with_font(doc, clean[2:].strip(), style="List Bullet", font_pt=font_size)
        else:
            _add_paragraph_with_font(doc, clean, font_pt=font_size)

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)

    filename = _safe_filename(db_resume.title, "docx", f"resume_{resume_id}.docx")
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": _content_disposition(filename)},
    )


# ══════════════════════════════════════════════════════════════
# 5. settings 路由
# ══════════════════════════════════════════════════════════════

@router.get("/settings")
def get_settings():
    settings = load_settings()
    masked = {
        p: ("••••••" if get_api_key(p, settings) else "")
        for p in PROVIDERS
    }
    custom_cfg = settings.get("custom", {})

    # 多自定义模型列表（脱敏后返回前端）
    custom_models_masked = []
    for cm in settings.get("custom_models", []):
        item = dict(cm)
        item["api_key_set"] = "••••••" if cm.get("api_key") else ""
        item.pop("api_key", None)
        custom_models_masked.append(item)

    return {
        "provider": settings["provider"],
        "model": settings["model"],
        "api_keys_set": masked,
        "providers": PROVIDERS,
        "custom": {
            "base_url": custom_cfg.get("base_url", ""),
            "api_key_set": "••••••" if custom_cfg.get("api_key", "") else "",
            "model": custom_cfg.get("model", ""),
        },
        "custom_models": custom_models_masked,
    }


@router.post("/settings/custom-models")
def create_custom_model(body: CustomModelCreate):
    """新增一个自定义模型并立即返回脱敏后的数据。"""
    settings = load_settings()
    new_cm = add_custom_model(body.model_dump(), settings)
    # 脱敏
    resp = dict(new_cm)
    resp["api_key_set"] = "••••••" if new_cm.get("api_key") else ""
    resp.pop("api_key", None)
    return resp


@router.delete("/settings/custom-models/{model_id}")
def remove_custom_model(model_id: str):
    """根据 id 删除一个自定义模型。"""
    settings = load_settings()
    deleted = delete_custom_model(model_id, settings)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Custom model not found: {model_id}")
    return {"message": "Custom model deleted"}


@router.put("/settings/custom-models/{model_id}")
def update_custom_model_route(model_id: str, body: CustomModelUpdate):
    """更新一个自定义模型。api_key 留空或 '••••••' 表示保留原值。"""
    settings = load_settings()
    updated = update_custom_model(model_id, body.model_dump(exclude_unset=True), settings)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Custom model not found: {model_id}")
    # 如果当前选中的正是被编辑的模型，同步更新 settings.model（model_id 可能变了）
    if settings.get("provider") == f"{CUSTOM_PROVIDER_KEY}:{model_id}":
        settings["model"] = updated.get("model_id", "")
        save_settings(settings)
    resp = dict(updated)
    resp["api_key_set"] = "••••••" if updated.get("api_key") else ""
    resp.pop("api_key", None)
    return resp


@router.post("/settings/test-custom-model")
async def test_custom_model_direct(body: CustomModelTest):
    """
    通过后端代理发起连通性测试，避免浏览器 CORS 拦截。
    完整透传 HTTP 状态码、响应体、错误类型，方便前端展示。
    编辑模式下 api_key 为空或 '••••••' 时，用 existing_model_id 查找已存储的密钥。
    """
    # 解析 api_key：空 / 掩码 → 用已存储的密钥（需提供 existing_model_id）
    api_key = (body.api_key or "").strip()
    if (not api_key or api_key == "••••••") and body.existing_model_id:
        settings = load_settings()
        cm = get_custom_model(f"{CUSTOM_PROVIDER_KEY}:{body.existing_model_id}", settings)
        if cm:
            api_key = cm.get("api_key", "")
    if not api_key:
        return {
            "success": False,
            "error_type": "no_api_key",
            "message": "请填写 API 密钥后再测试。",
        }

    base = (body.base_url or "").strip()
    if body.full_url:
        # 用户填写完整 URL，直接使用
        test_url = base
    else:
        # 去掉末尾斜杠后拼接 /chat/completions
        clean = base.rstrip("/")
        test_url = f"{clean}/chat/completions"

    payload = json.dumps({
        "model": body.model_id,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
    }).encode("utf-8")

    req = urllib.request.Request(
        test_url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )

    def _do_request() -> dict:
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body_text = resp.read().decode("utf-8", errors="replace")
                return {
                    "success": True,
                    "status_code": resp.status,
                    "body": body_text,
                }
        except urllib.error.HTTPError as e:
            # 有 HTTP 响应但状态非 2xx
            try:
                body_text = e.read().decode("utf-8", errors="replace")
            except Exception:
                body_text = "(无法读取响应体)"
            return {
                "success": False,
                "status_code": e.code,
                "status_text": e.reason or "Unknown",
                "body": body_text,
            }
        except urllib.error.URLError as e:
            # 网络层错误：超时、DNS、连接拒绝等
            if isinstance(e.reason, socket.timeout):
                return {
                    "success": False,
                    "error_type": "timeout",
                    "message": "请求超时（15秒），请检查网络或 API 地址是否正确。",
                }
            return {
                "success": False,
                "error_type": "URLError",
                "message": f"{type(e.reason).__name__}: {e.reason}",
            }
        except socket.timeout:
            return {
                "success": False,
                "error_type": "timeout",
                "message": "请求超时（15秒），请检查网络或 API 地址是否正确。",
            }
        except Exception as e:
            return {
                "success": False,
                "error_type": type(e).__name__,
                "message": str(e),
            }

    # urllib 是同步阻塞，放到线程池避免阻塞事件循环
    result = await asyncio.to_thread(_do_request)
    return result


@router.post("/settings/test")
async def test_api_connection(body: SettingsTest):
    """Test if the configured API key can connect successfully."""
    success, message = await test_connection(
        provider=body.provider,
        model=body.model,
        api_key_override=body.api_key,
        base_url_override=body.base_url,
    )
    return {"success": success, "message": message}


@router.put("/settings")
def update_settings(body: SettingsUpdate):
    settings = load_settings()
    settings["provider"] = body.provider
    settings["model"] = body.model

    to_sync = {}
    if body.api_keys:
        for k, v in body.api_keys.items():
            if v == "••••••":
                continue
            settings["api_keys"][k] = v
            if v and v.strip():
                to_sync[k] = v.strip()

    # 自定义模型配置
    custom_cfg = settings.get("custom", {})
    if body.custom_base_url is not None:
        custom_cfg["base_url"] = body.custom_base_url.strip()
    if body.custom_api_key is not None and body.custom_api_key != "••••••":
        custom_cfg["api_key"] = body.custom_api_key.strip()
    if body.custom_model is not None:
        custom_cfg["model"] = body.custom_model.strip()
    settings["custom"] = custom_cfg

    save_settings(settings)
    if to_sync:
        sync_env_file(to_sync)
    return {"message": "Settings saved"}


@router.delete("/settings/api-key/{provider}")
def clear_api_key(provider: str):
    settings = load_settings()
    if provider in settings.get("api_keys", {}):
        settings["api_keys"][provider] = ""
        save_settings(settings)
        sync_env_file({provider: ""})
    return {"message": f"API key for {provider} cleared"}


# ══════════════════════════════════════════════════════════════
# 6. uploads 路由
# ══════════════════════════════════════════════════════════════

@router.post("/uploads/parse-resume-background", response_model=ParseResumeBackgroundResponse)
async def parse_resume_background(file: UploadFile = File(...)):
    """简历 PDF → 候选人背景 Markdown。使用模型管理中当前配置的模型，扫描件需多模态模型。"""
    name = (file.filename or "").lower()
    if not name.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="仅支持 PDF 简历文件")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="上传文件为空")

    text, parser, warning = parse_resume_pdf_to_background(content)
    return ParseResumeBackgroundResponse(
        filename=file.filename or "resume.pdf",
        text=text,
        parser=parser,
        warning=warning,
    )


@router.post("/uploads/parse-resume-background/stream")
async def parse_resume_background_stream(file: UploadFile = File(...)):
    """流式解析简历 PDF，逐块返回文本（SSE）。使用模型管理中当前配置的模型。"""
    name = (file.filename or "").lower()
    if not name.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="仅支持 PDF 简历文件")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="上传文件为空")

    return StreamingResponse(
        sse_with_heartbeat(stream_resume_pdf_to_background(content)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/uploads/parse-job", response_model=JobParseResponse)
async def parse_job(file: UploadFile = File(...)):
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="上传文件为空")
    try:
        text, _ = extract_text_from_file(file.filename or "", content)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"JD解析失败: {exc}") from exc
    if not text:
        raise HTTPException(status_code=400, detail="未提取到JD文本")
    return _parse_job_fields(text)


class UploadResumeRequest(BaseModel):
    job_id: int
    accent: Optional[str] = "#2563eb"


@router.post("/uploads/upload-resume", response_model=schemas.ResumeResponse)
async def upload_resume(
    job_id: int = Query(...),
    accent: Optional[str] = Query("#2563eb"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """上传简历文件（图片/PDF/Word），自动提取文本 → LLM解析结构化JSON → LLM生成HTML简历 → 写入磁盘。

    完整链路：文件提取 → 结构化 → HTML生成，一步到位。
    """
    db_job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not db_job:
        raise HTTPException(status_code=404, detail="Job not found")

    content_bytes = await file.read()
    if not content_bytes:
        raise HTTPException(status_code=400, detail="上传文件为空")

    # Step 1: 提取文本
    try:
        text, parser = extract_text_from_file(file.filename or "", content_bytes)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"文件解析失败: {exc}") from exc

    # docx/PDF 文本提取不足时，走 AI 多模态识别路径（与 PDF VL 路径一致）
    if not text or len(text.strip()) < 10:
        lower_name = (file.filename or "").lower()
        if lower_name.endswith((".doc", ".docx")):
            pdf_bytes = _docx_to_pdf_bytes(content_bytes)
            if pdf_bytes:
                text = _extract_from_pdf(pdf_bytes)
                parser = "docx→pdf"
                if not text or len(text.strip()) < 10:
                    text = await _ai_vl_extract_from_pdf(pdf_bytes)
                    parser = "docx→pdf+ai_vl"
        elif lower_name.endswith(".pdf"):
            text = await _ai_vl_extract_from_pdf(content_bytes)
            parser = "pdf+ai_vl"
        if not text or len(text.strip()) < 10:
            raise HTTPException(status_code=400, detail="未提取到有效文本，请检查文件清晰度")

    # Step 2: LLM 解析为结构化 JSON
    jd = _build_job_content(db_job).strip()
    parse_msg = f"请将以下简历内容提取为结构化 JSON：\n\n{text[:120000]}"
    raw_json = await complete_response(SYSTEM_PARSE_RESUME, [{"role": "user", "content": parse_msg}])
    structured_text = _strip_code_fence(raw_json).strip()

    # Step 3: LLM 根据结构化 JSON + JD 生成 HTML
    accent_val = accent if accent in ACCENTS else "#2563eb"
    gen_msg = (
        f"## 目标岗位 JD\n\n{jd}\n\n---\n\n"
        f"## 候选人结构化信息\n\n{structured_text}\n\n---\n\n"
        f"请使用主题色 {accent_val}，根据以上信息生成一份完整简历 HTML。"
    )
    raw_html = await complete_response(SYSTEM_GENERATE_RESUME, [{"role": "user", "content": gen_msg}])
    html = _strip_code_fence(raw_html).strip()

    if not html or ("<!DOCTYPE" not in html and "<html" not in html):
        raise HTTPException(status_code=502, detail="模型未生成有效的 HTML 简历，请重试或更换模型")

    # Step 4: 保存到 DB + 磁盘
    q = db.query(models.Resume).filter(models.Resume.job_id == job_id)
    angle_index = q.count() + 1
    angle = f"角度{angle_index}"
    existing_count = q.filter(models.Resume.angle == angle).count()
    title = _build_resume_title_with_angle(db_job, file.filename, angle)

    word_count = len(text)

    db_resume = models.Resume(
        job_id=job_id,
        title=title,
        content=text,
        structured=structured_text,
        rendered_html=html,
        current_template="classic",
        angle=angle,
        version=existing_count + 1,
        file_type=parser,
        file_size=len(content_bytes),
    )
    db.add(db_resume)
    db.commit()
    db.refresh(db_resume)

    write_resume_file(db_resume.id, html)

    return db_resume


@router.post("/uploads/upload-resume/stream")
async def upload_resume_stream(
    job_id: int = Query(...),
    accent: Optional[str] = Query("#2563eb"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """流式版：上传简历文件 → 提取文本 → 结构化 → 生成HTML，逐步推送进度。"""
    db_job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not db_job:
        raise HTTPException(status_code=404, detail="Job not found")

    content_bytes = await file.read()
    if not content_bytes:
        raise HTTPException(status_code=400, detail="上传文件为空")

    jd = _build_job_content(db_job).strip()
    accent_val = accent if accent in ACCENTS else "#2563eb"
    filename = file.filename or ""

    async def _stream():
        # Step 0: 提取文本
        try:
            text, parser = extract_text_from_file(filename, content_bytes)
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'content': f'文件解析失败: {exc}'})}\n\n"
            return

        # 文本提取不足时走 AI 多模态识别路径（与 PDF VL 路径一致）
        if not text or len(text.strip()) < 10:
            lower_name = filename.lower()
            if lower_name.endswith((".doc", ".docx")):
                yield f"data: {json.dumps({'type': 'progress', 'phase': 'vl', 'content': '正在转换并识别文档...'}, ensure_ascii=False)}\n\n"
                pdf_bytes = _docx_to_pdf_bytes(content_bytes)
                if pdf_bytes:
                    text = _extract_from_pdf(pdf_bytes)
                    parser = "docx→pdf"
                    if not text or len(text.strip()) < 10:
                        try:
                            text = await _ai_vl_extract_from_pdf(pdf_bytes)
                            parser = "docx→pdf+ai_vl"
                        except HTTPException as e:
                            yield f"data: {json.dumps({'type': 'error', 'content': str(e.detail)})}\n\n"
                            return
            elif lower_name.endswith(".pdf"):
                yield f"data: {json.dumps({'type': 'progress', 'phase': 'vl', 'content': '正在识别文档...'}, ensure_ascii=False)}\n\n"
                try:
                    text = await _ai_vl_extract_from_pdf(content_bytes)
                    parser = "pdf+ai_vl"
                except HTTPException as e:
                    yield f"data: {json.dumps({'type': 'error', 'content': str(e.detail)})}\n\n"
                    return
            if not text or len(text.strip()) < 10:
                yield f"data: {json.dumps({'type': 'error', 'content': '未提取到有效文本，请检查文件清晰度'})}\n\n"
                return

        # Phase 1: 结构化
        yield f"data: {json.dumps({'type': 'progress', 'phase': 'parse', 'content': '正在解析简历内容...'}, ensure_ascii=False)}\n\n"

        try:
            raw_json = await complete_response(
                SYSTEM_PARSE_RESUME,
                [{"role": "user", "content": f"请将以下简历内容提取为结构化 JSON：\n\n{text[:120000]}"}],
            )
            structured_text = _strip_code_fence(raw_json).strip()
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': f'结构化解析失败: {str(e)[:300]}'})}\n\n"
            return

        yield f"data: {json.dumps({'type': 'progress', 'phase': 'generate', 'content': '正在生成简历HTML...'}, ensure_ascii=False)}\n\n"

        # Phase 2: 生成 HTML（流式输出）
        gen_msg = (
            f"## 目标岗位 JD\n\n{jd}\n\n---\n\n"
            f"## 候选人结构化信息\n\n{structured_text}\n\n---\n\n"
            f"请使用主题色 {accent_val}，根据以上信息生成一份完整简历 HTML。"
        )
        html_parts: list[str] = []
        try:
            async for chunk in stream_response(SYSTEM_GENERATE_RESUME, [{"role": "user", "content": gen_msg}]):
                html_parts.append(chunk)
                yield f"data: {json.dumps({'type': 'html', 'content': chunk}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': f'HTML生成中断: {str(e)[:300]}'})}\n\n"
            return

        try:
            full_html = _strip_code_fence("".join(html_parts)).strip()
        except ValueError as exc:
            yield f"data: {json.dumps({'type': 'error', 'content': str(exc)}, ensure_ascii=False)}\n\n"
            return

        if full_html and ("<!DOCTYPE" in full_html or "<html" in full_html):
            q = db.query(models.Resume).filter(models.Resume.job_id == job_id)
            angle_index = q.count() + 1
            angle = f"角度{angle_index}"
            existing_count = q.filter(models.Resume.angle == angle).count()
            title = _build_resume_title_with_angle(db_job, filename, angle)

            db_resume = models.Resume(
                job_id=job_id,
                title=title,
                content=text,
                structured=structured_text,
                rendered_html=full_html,
                current_template="classic",
                angle=angle,
                version=existing_count + 1,
                file_type=parser,
                file_size=len(content_bytes),
            )
            db.add(db_resume)
            db.commit()
            db.refresh(db_resume)

            write_resume_file(db_resume.id, full_html)

            yield f"data: {json.dumps({'type': 'done', 'resume_id': db_resume.id}, ensure_ascii=False)}\n\n"
        else:
            yield f"data: {json.dumps({'type': 'error', 'content': '模型未生成有效的 HTML 简历，请重试或更换模型'})}\n\n"

    return StreamingResponse(
        sse_with_heartbeat(_stream()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
# ══════════════════════════════════════════════════════════════

@router.get("/background/profiles", response_model=List[schemas.BackgroundProfileResponse])
def list_background_profiles(db: Session = Depends(get_db)):
    """列出全部人物背景档案；若为空则自动创建一条「默认」。"""
    rows = (
        db.query(models.UserBackground)
        .order_by(models.UserBackground.id.asc())
        .all()
    )
    if not rows:
        bg = models.UserBackground(name="默认", content="")
        db.add(bg)
        db.commit()
        db.refresh(bg)
        rows = [bg]
    return rows


@router.post("/background/profiles", response_model=schemas.BackgroundProfileResponse)
def create_background_profile(
    body: schemas.BackgroundProfileCreate,
    db: Session = Depends(get_db),
):
    name = (body.name or "").strip() or "新档案"
    bg = models.UserBackground(name=name, content=body.content or "")
    db.add(bg)
    db.commit()
    db.refresh(bg)
    return bg


@router.put("/background/profiles/{profile_id}", response_model=schemas.BackgroundProfileResponse)
def update_background_profile(
    profile_id: int,
    body: schemas.BackgroundProfileUpdate,
    db: Session = Depends(get_db),
):
    bg = db.query(models.UserBackground).filter(models.UserBackground.id == profile_id).first()
    if not bg:
        raise HTTPException(status_code=404, detail="Profile not found")
    if body.name is not None:
        t = body.name.strip()
        if t:
            bg.name = t
    if body.content is not None:
        bg.content = body.content
    db.commit()
    db.refresh(bg)
    return bg


@router.delete("/background/profiles/{profile_id}")
def delete_background_profile(profile_id: int, db: Session = Depends(get_db)):
    count = db.query(models.UserBackground).count()
    if count <= 1:
        raise HTTPException(status_code=400, detail="至少保留一份背景档案")
    bg = db.query(models.UserBackground).filter(models.UserBackground.id == profile_id).first()
    if not bg:
        raise HTTPException(status_code=404, detail="Profile not found")
    db.delete(bg)
    db.commit()
    return {"ok": True, "id": profile_id}


# ══════════════════════════════════════════════════════════════
# 8. interview-sim 路由
# ══════════════════════════════════════════════════════════════

@router.get("/interview-sim/question-categories", response_model=schemas.QuestionCategoriesResponse)
async def get_question_categories():
    """可供模拟面试勾选的题目类型（与预置 JSON、生成题库分类一致）。"""
    return schemas.QuestionCategoriesResponse(categories=list(QUESTION_CATEGORIES))


@router.get("/interview-sim/questionnaire", response_model=schemas.QuestionnaireResponse)
async def get_questionnaire(
    job_id: int,
    resume_id: int,
    background_profile_id: Optional[int] = None,
    total: int = 7,
    seed: Optional[int] = None,
    categories: Optional[List[str]] = Query(
        None,
        description="可重复传参；仅从这些类别中随机抽样；不传则全库合并后抽样",
    ),
    db: Session = Depends(get_db),
):
    """从预置分类题库 + 本岗位专属题库合并后，为本场模拟抽样题单（不调用 LLM）。"""
    db_job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not db_job:
        raise HTTPException(status_code=404, detail="Job not found")

    extra = _db_job_questions_as_bank(db, job_id, resume_id, background_profile_id)
    t = max(3, min(12, total))
    cat_filter = [c for c in (categories or []) if c and str(c).strip()]
    items, cats = sample_questionnaire(
        _build_job_content(db_job),
        total=t,
        seed=seed,
        max_per_category=2,
        extra_questions=extra or None,
        category_filter=cat_filter if cat_filter else None,
    )
    md = questionnaire_to_markdown(items)
    return schemas.QuestionnaireResponse(
        categories_used=cats,
        items=[
            schemas.QuestionnaireItemResponse(id=q.id, category=q.category, text=q.text)
            for q in items
        ],
        questionnaire_markdown=md,
    )


@router.get("/interview-sim/bank-preview", response_model=schemas.BankPreviewResponse)
async def get_bank_preview(
    job_id: int,
    resume_id: int,
    background_profile_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """预览：全局预置题数量/按类统计 + 本岗位专属题全文（便于管理员核对）。"""
    db_job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not db_job:
        raise HTTPException(status_code=404, detail="Job not found")

    preset = load_question_bank()
    by_cat = Counter(q.category for q in preset)
    by_category = {c: by_cat.get(c, 0) for c in QUESTION_CATEGORIES}

    q = db.query(models.JobInterviewQuestion).filter(models.JobInterviewQuestion.job_id == job_id)
    q = q.filter(models.JobInterviewQuestion.resume_id == resume_id)
    if background_profile_id is not None:
        q = q.filter(models.JobInterviewQuestion.background_profile_id == background_profile_id)
    rows = q.order_by(models.JobInterviewQuestion.id.asc()).all()
    return schemas.BankPreviewResponse(
        categories_allowed=list(QUESTION_CATEGORIES),
        preset=schemas.PresetBankStats(total=len(preset), by_category=by_category),
        job_questions=[
            schemas.JobQuestionPreviewRow(id=r.id, category=r.category, text=r.text) for r in rows
        ],
    )


@router.delete("/interview-sim/job-bank", response_model=schemas.JobBankDeleteResponse)
async def clear_job_interview_bank(
    job_id: int,
    resume_id: int,
    background_profile_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    db_job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not db_job:
        raise HTTPException(status_code=404, detail="Job not found")
    q = db.query(models.JobInterviewQuestion).filter(models.JobInterviewQuestion.job_id == job_id)
    q = q.filter(models.JobInterviewQuestion.resume_id == resume_id)
    if background_profile_id is not None:
        q = q.filter(models.JobInterviewQuestion.background_profile_id == background_profile_id)
    n = q.delete()
    db.commit()
    return schemas.JobBankDeleteResponse(deleted=n)


@router.get("/interview-sim/job-bank", response_model=schemas.JobInterviewBankMetaResponse)
async def get_job_interview_bank_meta(
    job_id: int,
    resume_id: int,
    background_profile_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    db_job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not db_job:
        raise HTTPException(status_code=404, detail="Job not found")
    n = (
        db.query(models.JobInterviewQuestion)
        .filter(models.JobInterviewQuestion.job_id == job_id)
        .filter(models.JobInterviewQuestion.resume_id == resume_id)
        .filter(
            models.JobInterviewQuestion.background_profile_id == background_profile_id
            if background_profile_id is not None
            else models.JobInterviewQuestion.background_profile_id.is_(None)
        )
        .count()
    )
    return schemas.JobInterviewBankMetaResponse(count=n)


@router.post("/interview-sim/generate-bank", response_model=schemas.GenerateInterviewBankResponse)
async def generate_job_interview_bank(
    request: schemas.GenerateInterviewBankRequest,
    db: Session = Depends(get_db),
):
    """根据 JD + 简历 + 可选背景 调用 LLM 生成专属面试题并入库；之后「开始面试」抽样时会与全局题库合并。"""
    db_job = db.query(models.Job).filter(models.Job.id == request.job_id).first()
    if not db_job:
        raise HTTPException(status_code=404, detail="Job not found")

    if request.replace:
        db.query(models.JobInterviewQuestion).filter(models.JobInterviewQuestion.job_id == request.job_id).filter(
            models.JobInterviewQuestion.resume_id == request.resume_id
        ).filter(
            models.JobInterviewQuestion.background_profile_id == request.background_profile_id
        ).delete()
        db.commit()

    try:
        db_resume = db.query(models.Resume).filter(models.Resume.id == request.resume_id).first()
        if not db_resume:
            raise HTTPException(status_code=404, detail="Resume not found")
        db_bg = None
        if request.background_profile_id is not None:
            db_bg = db.query(models.UserBackground).filter(models.UserBackground.id == request.background_profile_id).first()
        dicts = await generate_job_question_dicts(
            _build_job_content(db_job),
            db_resume.content or "",
            db_bg.content if db_bg else None,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM 生成失败: {str(e)[:200]}")

    if not dicts:
        raise HTTPException(status_code=502, detail="未生成有效题目，请检查模型配置后重试")

    for d in dicts:
        db.add(
            models.JobInterviewQuestion(
                job_id=request.job_id,
                resume_id=request.resume_id,
                background_profile_id=request.background_profile_id,
                category=d["category"],
                text=d["text"],
            )
        )
    db.commit()

    total = (
        db.query(models.JobInterviewQuestion)
        .filter(models.JobInterviewQuestion.job_id == request.job_id)
        .filter(models.JobInterviewQuestion.resume_id == request.resume_id)
        .filter(models.JobInterviewQuestion.background_profile_id == request.background_profile_id)
        .count()
    )
    return schemas.GenerateInterviewBankResponse(added=len(dicts), total_for_job=total)


@router.put("/interview-sim/job-question", response_model=schemas.JobQuestionUpdateResponse)
async def update_job_question(
    request: schemas.JobQuestionUpdateRequest,
    db: Session = Depends(get_db),
):
    q = (
        db.query(models.JobInterviewQuestion)
        .filter(models.JobInterviewQuestion.id == request.question_id)
        .filter(models.JobInterviewQuestion.job_id == request.job_id)
        .filter(models.JobInterviewQuestion.resume_id == request.resume_id)
        .filter(models.JobInterviewQuestion.background_profile_id == request.background_profile_id)
        .first()
    )
    if not q:
        raise HTTPException(status_code=404, detail="Question not found")
    q.text = request.text
    db.commit()
    return schemas.JobQuestionUpdateResponse(updated=1)


@router.delete("/interview-sim/job-question", response_model=schemas.JobQuestionDeleteResponse)
async def delete_job_question(
    request: schemas.JobQuestionDeleteRequest,
    db: Session = Depends(get_db),
):
    n = (
        db.query(models.JobInterviewQuestion)
        .filter(models.JobInterviewQuestion.id == request.question_id)
        .filter(models.JobInterviewQuestion.job_id == request.job_id)
        .filter(models.JobInterviewQuestion.resume_id == request.resume_id)
        .filter(models.JobInterviewQuestion.background_profile_id == request.background_profile_id)
        .delete()
    )
    db.commit()
    return schemas.JobQuestionDeleteResponse(deleted=n)


@router.post("/interview-sim/stream")
async def interview_sim_stream(request: schemas.InterviewSimRequest, db: Session = Depends(get_db)):
    db_job = db.query(models.Job).filter(models.Job.id == request.job_id).first()
    if not db_job:
        raise HTTPException(status_code=404, detail="Job not found")

    db_resume = db.query(models.Resume).filter(models.Resume.id == request.resume_id).first()
    if not db_resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    if db_resume.job_id != request.job_id:
        raise HTTPException(status_code=400, detail="Resume does not belong to this job")

    messages = [msg.model_dump() for msg in request.messages]

    return StreamingResponse(
        sse_with_heartbeat(_stream_sim(
            job_content=_build_job_content(db_job),
            resume_content=db_resume.content or "",
            messages=messages,
            user_background=request.user_background,
            questionnaire_markdown=request.questionnaire_markdown,
        )),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/interview-sim/report", response_model=schemas.InterviewReportResponse)
async def interview_sim_report(request: schemas.InterviewReportRequest, db: Session = Depends(get_db)):
    db_job = db.query(models.Job).filter(models.Job.id == request.job_id).first()
    if not db_job:
        raise HTTPException(status_code=404, detail="Job not found")

    db_resume = db.query(models.Resume).filter(models.Resume.id == request.resume_id).first()
    if not db_resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    if db_resume.job_id != request.job_id:
        raise HTTPException(status_code=400, detail="Resume does not belong to this job")

    job_content = _build_job_content(db_job)
    resume_content = db_resume.content or ""
    transcript = _format_transcript([m.model_dump() for m in request.messages])
    if not transcript.strip():
        raise HTTPException(status_code=400, detail="No interview content to analyze")

    context_parts = [
        f"## 岗位 JD\n\n{job_content}",
        f"## 候选人简历\n\n{resume_content}",
        f"## 模拟面试对话记录\n\n{transcript}",
    ]
    if request.user_background:
        context_parts.append(f"## 候选人补充经历\n\n{request.user_background}")

    context = "\n\n---\n\n".join(context_parts)
    system = f"{INTERVIEW_REPORT_SYSTEM}\n\n---\n\n{context}"

    user_msg = "请根据以上材料生成面试复盘报告（Markdown）。直接输出报告正文，不要前言套话。"
    report_md = await complete_response(system, [{"role": "user", "content": user_msg}])

    return schemas.InterviewReportResponse(report=report_md)


# ══════════════════════════════════════════════════════════════
# 9. evaluation 路由
# ══════════════════════════════════════════════════════════════

@router.post("/evaluation/scorecard", response_model=schemas.EvaluationScorecardResponse)
async def generate_scorecard(request: schemas.EvaluationScorecardRequest, db: Session = Depends(get_db)):
    db_job = db.query(models.Job).filter(models.Job.id == request.job_id).first()
    if not db_job:
        raise HTTPException(status_code=404, detail="Job not found")
    db_resume = db.query(models.Resume).filter(models.Resume.id == request.resume_id).first()
    if not db_resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    parts = [
        f"## 岗位 JD\n\n{_build_job_content(db_job)}",
        f"## 候选人简历\n\n{db_resume.content or ''}",
    ]
    if request.user_background:
        parts.append(f"## 候选人背景补充\n\n{request.user_background}")
    if request.transcript:
        parts.append(f"## 模拟面试对话摘录\n\n{request.transcript}")
    competency_set = _pick_competency_set_by_profile(getattr(db_job, "competency_profile", "default"), db_job.title or "")
    competency_text = "、".join(competency_set) if competency_set else "综合能力、岗位匹配、风险识别、改进建议"
    user_msg = (
        "\n\n---\n\n".join(parts)
        + f"\n\n请优先围绕以下能力项生成评分卡：{competency_text}\n\n请输出评分卡 JSON。"
    )

    try:
        raw = await complete_response(EVAL_SYSTEM_PROMPT, [{"role": "user", "content": user_msg}])
        data = json.loads(_strip_code_fence(raw))
        if not isinstance(data, dict):
            raise ValueError("invalid json object")
        normalized = _normalize_scorecard(data)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"评分卡生成失败: {str(e)[:180]}")

    db.add(
        models.EvaluationReport(
            job_id=request.job_id,
            resume_id=request.resume_id,
            report_type="scorecard",
            content_json=json.dumps(normalized.model_dump(), ensure_ascii=False),
        )
    )
    db.commit()
    return normalized


@router.get("/evaluation/scorecard-history", response_model=List[schemas.EvaluationReportListItem])
def list_scorecard_history(job_id: int, resume_id: Optional[int] = None, limit: int = 20, db: Session = Depends(get_db)):
    limit = max(1, min(100, int(limit)))
    q = (
        db.query(models.EvaluationReport)
        .filter(models.EvaluationReport.job_id == job_id)
        .filter(models.EvaluationReport.report_type == "scorecard")
    )
    if resume_id is not None:
        q = q.filter(models.EvaluationReport.resume_id == resume_id)
    return q.order_by(models.EvaluationReport.created_at.desc()).limit(limit).all()


@router.get("/evaluation/scorecard-history/{report_id}", response_model=schemas.EvaluationReportListItem)
def get_scorecard_history_item(report_id: int, db: Session = Depends(get_db)):
    row = db.query(models.EvaluationReport).filter(models.EvaluationReport.id == report_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Scorecard report not found")
    return row


# ══════════════════════════════════════════════════════════════
# AI 话术生成（/agent/greeting-generator）
# ══════════════════════════════════════════════════════════════

class GreetingStyleOption(BaseModel):
    id: str
    name: str
    description: str

GREETING_STYLES = [
    GreetingStyleOption(id="experience-match", name="经验匹配型", description="直接亮年限+核心技能，对标JD要求"),
    GreetingStyleOption(id="project-result", name="项目成果型", description="用具体项目/数据说话，突出战绩"),
    GreetingStyleOption(id="enthusiasm", name="热情态度型", description="表达对公司/岗位的强烈兴趣和认同"),
    GreetingStyleOption(id="concise-direct", name="简洁直接型", description="一句话说清我是谁+能做什么"),
    GreetingStyleOption(id="skill-keyword", name="技能关键词型", description="堆砌JD技术栈关键词，过筛选"),
    GreetingStyleOption(id="learning-potential", name="学习潜力型", description="强调学习能力和适应速度"),
]


@router.get("/greeting-generator/styles", response_model=List[GreetingStyleOption])
def list_greeting_styles():
    return GREETING_STYLES


class ParseJdImageRequest(BaseModel):
    pass


class JdParseResult(BaseModel):
    title: str = ""
    company: Optional[str] = None
    responsibilities: List[str] = []
    requirements: List[str] = []
    raw_text: str = ""


@router.post("/greeting-generator/parse-jd-image", response_model=JdParseResult)
async def parse_jd_image(file: UploadFile = File(...)):
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="上传文件为空")

    try:
        text, _ = extract_text_from_file(file.filename or "", content)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"JD图片识别失败: {exc}") from exc

    if not text or not text.strip():
        raise HTTPException(status_code=400, detail="未识别到JD文字，请检查图片清晰度")

    parse_prompt = f"""请从以下岗位JD文本中提取结构化信息，输出严格 JSON 对象（不要 markdown 代码块、不要注释、不要 JSON 之外的任何文字）：
{{
  "title": "岗位名称",
  "company": "公司名（可选）",
  "responsibilities": ["职责1", "职责2"],
  "requirements": ["要求1", "要求2"]
}}

JD文本：
{text[:3000]}

规则：
- 提取失败的字段赋空字符串或空数组
- 职责和要求尽量拆分为独立条目
- 保留关键技术词和量化数据"""

    try:
        raw = await complete_response(
            "你是JD信息提取助手，只输出JSON，不输出其他内容。",
            [{"role": "user", "content": parse_prompt}],
        )
        data = json.loads(_strip_code_fence(raw))
    except Exception:
        data = {}

    return JdParseResult(
        title=data.get("title", ""),
        company=data.get("company"),
        responsibilities=data.get("responsibilities", []),
        requirements=data.get("requirements", []),
        raw_text=text.strip(),
    )


class GenerateGreetingsRequest(BaseModel):
    jd_text: str
    style: str = "professional"
    count: int = Field(default=1, ge=1, le=8)
    existing_count: int = Field(default=0, ge=0, description="已生成的话术数量，用于区分新话术角度")
    resume: Optional[str] = None
    expect_jd: Optional[str] = None


class GreetingItem(BaseModel):
    index: int
    text: str
    style_label: str


class GenerateGreetingsResponse(BaseModel):
    greetings: List[GreetingItem]
    suggestions: List[dict]


_SYSTEM_PROMPT_GREETING = """你是一位资深求职打招呼助手。你的任务是根据招聘JD和求职者背景，生成个性化、有针对性的打招呼话术。

## 工作流程
1. 仔细分析JD，提取核心要求：岗位实际职责、必备技能栈、经验要求、行业方向
2. 将JD的核心职责和技能要求与求职者背景进行匹配
3. 根据指定风格生成打招呼话术

## 话术要求
- 每条不超过100字
- 针对JD中的具体技术要求，提及匹配的技能或经验
- 语气自然、真诚、专业，避免模板化
- 提及JD中的关键技术词或业务方向，体现契合度
- 不要出现"我看了贵公司的招聘"等套话
- 如果已有之前生成的话术，确保新话术从不同角度切入，避免与已有话术雷同

## 风格说明
根据用户指定的风格生成话术：
- experience-match：直接亮年限+核心技能，对标JD要求，适用于经验高度匹配的岗位
- project-result：用具体项目/数据说话，突出战绩，适用于有亮眼项目经历、想差异化竞争
- enthusiasm：表达对公司/岗位的强烈兴趣和认同，适用于经验略欠但意愿强、公司文化导向
- concise-direct：一句话说清"我是谁+能做什么"，适用于HR忙碌、批量投递时提高回复率
- skill-keyword：堆砌JD里的技术栈关键词，过筛选，适用于大厂/系统初筛、关键词匹配场景
- learning-potential：强调学习能力和适应速度，弱化经验不足，适用于转行、应届生、经验不够但潜力大

## 输出格式
严格输出 JSON 对象（不要 markdown 代码块、不要注释、不要 JSON 之外的任何文字）：
{{"text": "话术内容", "style_label": "风格标签（2-4字）"}}

style_label 体现该话术的侧重角度（如"专业型"、"成果导向"、"技能匹配"等）。"""


@router.post("/greeting-generator/generate", response_model=GenerateGreetingsResponse)
async def generate_greetings(request: GenerateGreetingsRequest):
    jd = (request.jd_text or "").strip()[:3000]
    if not jd:
        raise HTTPException(status_code=400, detail="JD内容不能为空")

    style_info = next((s for s in GREETING_STYLES if s.id == request.style), GREETING_STYLES[0])

    sections = [f"## 岗位JD信息\n{jd}"]
    if request.resume and request.resume.strip():
        sections.append(f"## 求职者背景\n{request.resume.strip()[:1000]}")
    if request.expect_jd and request.expect_jd.strip():
        sections.append(f"## 期望岗位描述\n{request.expect_jd.strip()[:1000]}")
    sections.append(f"## 生成要求\n风格：{style_info.name}（{style_info.description}）")
    if request.existing_count > 0:
        sections.append(f"注意：用户已生成过 {request.existing_count} 条话术，请从新的角度切入，确保与之前的话术不重复。")
    sections.append(f"生成 {request.count} 条话术，每条从不同侧重点切入")
    user_content = "\n\n".join(sections)

    try:
        raw = await complete_response(
            _SYSTEM_PROMPT_GREETING,
            [{"role": "user", "content": user_content}],
        )
        data = json.loads(_strip_code_fence(raw))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"话术生成失败: {str(e)[:200]}")

    greetings: List[GreetingItem] = []

    if isinstance(data, dict):
        text = data.get("text", "").strip()
        label = data.get("style_label", style_info.name)
        if text:
            for prefix in ("MATCH", "Match", "match", "匹配", "招呼语：", "招呼语:", "打招呼：", "打招呼:"):
                if text.startswith(prefix):
                    text = text[len(prefix):].strip()
            if len(text) >= 2 and text[0] in '"「『"' and text[-1] in '"」』"':
                text = text[1:-1].strip()
            greetings.append(GreetingItem(index=request.existing_count, text=text, style_label=label))
    elif isinstance(data, list):
        for i, item in enumerate(data[:request.count]):
            if isinstance(item, dict):
                text = item.get("text", "").strip()
                label = item.get("style_label", style_info.name)
            elif isinstance(item, str):
                text = item.strip()
                label = style_info.name
            else:
                continue
            if not text:
                continue
            for prefix in ("MATCH", "Match", "match", "匹配", "招呼语：", "招呼语:", "打招呼：", "打招呼:"):
                if text.startswith(prefix):
                    text = text[len(prefix):].strip()
            if len(text) >= 2 and text[0] in '"「『"' and text[-1] in '"」』"':
                text = text[1:-1].strip()
            greetings.append(GreetingItem(index=request.existing_count + i, text=text, style_label=label))

    if not greetings:
        raise HTTPException(status_code=502, detail="模型未生成有效话术，请重试")

    suggestions = [
        {"icon": "briefcase", "title": "突出项目经验", "description": "结合JD职责，强调相关项目成果"},
        {"icon": "target", "title": "强调匹配技能", "description": "精准对应JD要求的技能栈"},
        {"icon": "trending-up", "title": "展示学习能力", "description": "体现快速适应和持续成长"},
    ]

    return GenerateGreetingsResponse(greetings=greetings, suggestions=suggestions)


# ══════════════════════════════════════════════════════════════
# 职位分析（/agent/job-analysis）
# ══════════════════════════════════════════════════════════════

class JobAnalysisRequest(BaseModel):
    jd_text: str


class SkillItem(BaseModel):
    name: str
    level: str = "required"
    description: str = ""


class KnowledgeItem(BaseModel):
    topic: str
    description: str = ""
    resources: List[str] = []


class PlanPhase(BaseModel):
    phase: str
    duration: str
    goals: List[str] = []
    actions: List[str] = []


class InterviewQuestion(BaseModel):
    category: str
    question: str
    hints: List[str] = []


class JobAnalysisResult(BaseModel):
    job_title: str = ""
    summary: str = ""
    skills: List[SkillItem] = []
    knowledge: List[KnowledgeItem] = []
    plan: List[PlanPhase] = []
    interview_questions: List[InterviewQuestion] = []


_SYSTEM_PROMPT_JOB_ANALYSIS = """你是一位资深技术招聘顾问和职业规划师。根据用户提供的岗位JD，进行深度分析。

## 输出要求

严格输出 JSON 对象（不要 markdown 代码块、不要注释、不要 JSON 之外的任何文字），结构如下：

{
  "job_title": "岗位名称",
  "summary": "2-3句话的岗位核心概述，包括方向、难度、市场情况",
  "skills": [
    {"name": "技能名", "level": "required|preferred|bonus", "description": "为什么需要、掌握到什么程度"}
  ],
  "knowledge": [
    {"topic": "知识点", "description": "需要掌握的核心内容", "resources": ["推荐学习资源1", "推荐学习资源2"]}
  ],
  "plan": [
    {"phase": "阶段名", "duration": "预计时间", "goals": ["目标1"], "actions": ["具体行动1"]}
  ],
  "interview_questions": [
    {"category": "分类", "question": "面试问题", "hints": ["答题要点1", "答题要点2"]}
  ]
}

## 分析维度

### skills - 技能要求
从JD中提取所有技术技能和软技能，分为三级：
- required：JD明确要求的必备技能
- preferred：JD提到"优先""加分""熟悉优先"的技能
- bonus：JD未提及但该岗位通常需要的相关技能

### knowledge - 知识点学习
针对每个核心技能，拆解出需要学习的具体知识点：
- topic：知识点名称
- description：需要掌握的核心内容、深度要求
- resources：推荐的学习资源（书籍、官方文档、在线课程等，尽量具体）

### plan - 学习方案
生成一份分阶段的学习计划（3-5个阶段），从基础到进阶：
- phase：阶段名称
- duration：建议时长
- goals：该阶段要达成的目标
- actions：具体的行动步骤（学什么、做什么练习、完成什么项目）

### interview_questions - 面试问题
针对该岗位的高频面试题（8-12题），覆盖：
- 基础知识题
- 项目经验题
- 场景设计题
- 行为面试题
每题附带答题要点提示。

## 规则
1. 技能分析要全面，不要遗漏JD中隐含的技能要求
2. 学习方案要切实可行，有明确的阶段和可执行的行动
3. 面试问题要贴合该岗位实际情况，不要泛泛而谈
4. level 只能是 required / preferred / bonus 三选一
5. 中文输出"""


@router.post("/job-analysis/analyze", response_model=JobAnalysisResult)
async def analyze_job(request: JobAnalysisRequest):
    jd = (request.jd_text or "").strip()[:4000]
    if not jd:
        raise HTTPException(status_code=400, detail="JD内容不能为空")

    user_content = f"## 岗位JD信息\n\n{jd}"

    try:
        raw = await complete_response(
            _SYSTEM_PROMPT_JOB_ANALYSIS,
            [{"role": "user", "content": user_content}],
        )
        data = json.loads(_strip_code_fence(raw))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"职位分析失败: {str(e)[:200]}")

    skills = []
    for s in data.get("skills", []):
        if isinstance(s, dict) and s.get("name"):
            skills.append(SkillItem(
                name=s["name"],
                level=s.get("level", "required"),
                description=s.get("description", ""),
            ))

    knowledge = []
    for k in data.get("knowledge", []):
        if isinstance(k, dict) and k.get("topic"):
            knowledge.append(KnowledgeItem(
                topic=k["topic"],
                description=k.get("description", ""),
                resources=k.get("resources", []),
            ))

    plan = []
    for p in data.get("plan", []):
        if isinstance(p, dict) and p.get("phase"):
            plan.append(PlanPhase(
                phase=p["phase"],
                duration=p.get("duration", ""),
                goals=p.get("goals", []),
                actions=p.get("actions", []),
            ))

    questions = []
    for q in data.get("interview_questions", []):
        if isinstance(q, dict) and q.get("question"):
            questions.append(InterviewQuestion(
                category=q.get("category", ""),
                question=q["question"],
                hints=q.get("hints", []),
            ))

    return JobAnalysisResult(
        job_title=data.get("job_title", ""),
        summary=data.get("summary", ""),
        skills=skills,
        knowledge=knowledge,
        plan=plan,
        interview_questions=questions,
    )
