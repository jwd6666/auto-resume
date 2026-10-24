"""AI 招呼语生成服务：根据岗位 JD 信息调用大模型生成个性化打招呼内容。

仅复用模型管理的统一自定义模型配置（provider 为模型管理的 key，如 custom:xxx）。
"""
from __future__ import annotations

from typing import Tuple

from ..schemas.task import AIConfig
from .resume_provider import complete_response_with_provider, CUSTOM_PROVIDER_KEY, is_cloud_provider

_SYSTEM_PROMPT = (
    "你是一位资深求职打招呼助手。你的任务是根据招聘JD和求职者的背景，判断匹配度并生成让HR觉得求职者很适合该岗位的招呼语。\n\n"
    "## 匹配判断优先级（必须严格按此顺序）\n"
    "1. 如果用户提供了「期望岗位描述」，必须以该描述作为匹配判断的主要依据：将岗位JD与此期望岗位描述严格比对，职责/技能栈不重合则输出 SKIP\n"
    "2. 如果没有「期望岗位描述」，则根据「求职意向」搜索关键词来判断：岗位的核心职责应与搜索关键词所属领域相关\n"
    "3. 匹配判断必须基于岗位实际职责和技能栈，而不是关键词字面相似\n\n"
    "## 招呼语生成规则（仅匹配时）\n"
    "- 不超过100字\n"
    "- 如果用户提供了求职者背景（学校、经历、技能等），必须基于这些真实信息来写招呼语，提及与之匹配的技能或经验\n"
    "- 如果没有提供求职者背景，则针对JD中的具体技术要求，泛化地表达求职者的适配意愿，但不编造具体的项目或经验\n"
    "- 语气自然、真诚、专业，避免模板化\n"
    "- 提及JD中的关键技术词或业务方向，体现契合度\n\n"
    "## 严禁编造（最高优先级）\n"
    "- 招呼语中提到的技能、经验、项目、学校、工作年限等信息，必须是用户提供的背景信息中明确包含的\n"
    "- 禁止根据JD反向编造求职者不具备的经验或技能\n"
    "- 如果背景信息不足，宁可只写泛化表达，也绝不凭空捏造具体经历\n\n"
    "## 输出格式\n"
    "- 不要输出 MATCH、匹配、不匹配等判断标签\n"
    "- 不要加引号、前缀、解释或任何多余文字\n"
    "- 不要出现'我看了贵公司的招聘'等套话\n"
    "- 只输出 SKIP 或招呼语内容，二选一"
)


def _is_managed_provider(provider: str) -> bool:
    if not provider:
        return False
    if provider.startswith(f"{CUSTOM_PROVIDER_KEY}:") or provider == CUSTOM_PROVIDER_KEY:
        return True
    # 云端官方模型（cloud:xxx）：密钥由云端代理管理，无需本地配置 API Key
    return is_cloud_provider(provider)


def _clean_result(result: str) -> str:
    result = result.strip()
    for prefix in ("MATCH", "Match", "match", "匹配", "招呼语：", "招呼语:", "打招呼：", "打招呼:"):
        if result.startswith(prefix):
            result = result[len(prefix):].strip()
    if len(result) >= 2 and result[0] in '"「『"' and result[-1] in '"」』"':
        result = result[1:-1].strip()
    return result


async def generate_greeting(config: AIConfig, jd_text: str, keyword: str = "", resume: str = "", expect_jd: str = "") -> Tuple[bool, str]:
    jd_text = jd_text[:2000] if len(jd_text) > 2000 else jd_text

    sections = [f"## 求职意向\n{keyword or '未指定'}"]
    if expect_jd and expect_jd.strip():
        sections.append(f"## 期望岗位描述（匹配判断的主要依据）\n{expect_jd.strip()[:1500]}\n\n⚠️ 请将下方「岗位JD信息」与此期望岗位描述严格比对，职责/技能栈不重合则输出 SKIP。有此描述时，以此描述为准进行判断，不要仅凭搜索关键词判断。")
    if resume and resume.strip():
        sections.append(f"## 求职者真实背景（招呼语必须基于此信息，禁止编造未提及的经历/技能/项目）\n{resume.strip()[:1000]}")
    sections.append(f"## 岗位JD信息\n{jd_text}")
    if expect_jd and expect_jd.strip():
        sections.append("请将岗位JD与「期望岗位描述」严格比对：匹配则基于求职者真实背景生成招呼语，不匹配则输出 SKIP。")
    else:
        sections.append("请根据搜索关键词所属领域与岗位核心职责判断匹配度：匹配则基于求职者真实背景生成招呼语，不匹配则输出 SKIP。")
    user_content = "\n\n".join(sections)

    if _is_managed_provider(config.provider) and not config.api_key:
        result = await complete_response_with_provider(
            config.provider,
            config.model or "",
            _SYSTEM_PROMPT,
            [{"role": "user", "content": user_content}],
            max_tokens=300,
        )
    else:
        raise RuntimeError("招呼语仅支持「模型管理」中配置的自定义模型或云端官方模型，请检查 provider 配置")

    result = _clean_result(result)

    if result.upper() == "SKIP" or result.upper().startswith("SKIP"):
        return False, ""

    return True, result
