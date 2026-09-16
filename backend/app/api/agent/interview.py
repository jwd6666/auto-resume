from __future__ import annotations

import json
import random
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Tuple

from pydantic import BaseModel, Field

from ...services.resume_provider import complete_response
from ...core.text_utils import strip_code_fence as _strip_code_fence


_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_BANK_PATH = _DATA_DIR / "interview_question_bank.json"

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

    by_cat: dict[str, list[BankQuestion]] = {}
    for q in all_q:
        by_cat.setdefault(q.category, []).append(q)

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


def parse_llm_question_list(raw: str) -> List[dict]:
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
) -> List[dict]:
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
