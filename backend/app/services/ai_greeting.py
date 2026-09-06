"""AI 招呼语生成服务：根据岗位 JD 信息调用大模型生成个性化打招呼内容。

支持两种模式：
1. 复用模型管理的统一配置（provider 为模型管理的 key，如 deepseek/zhipu/custom:xxx）
2. 兼容旧配置（直接指定 base_url/api_key/model，旧版 AIConfig 自带 key）
"""
from __future__ import annotations

import asyncio
import json
import urllib.request
import urllib.error
from typing import Optional, Tuple

from ..schemas.task import AIConfig
from .resume_provider import complete_response_with_provider, PROVIDERS, CUSTOM_PROVIDER_KEY

_PROVIDER_DEFAULTS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1/chat/completions",
        "model": "deepseek-chat",
    },
    "glm": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "model": "glm-4-flash",
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "model": "qwen-turbo",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1/chat/completions",
        "model": "gpt-4o-mini",
    },
}

_SYSTEM_PROMPT = (
    "你是一位资深求职打招呼助手。你的任务是根据招聘JD和求职者的背景，判断匹配度并生成让HR觉得求职者很适合该岗位的招呼语。\n\n"
    "## 工作流程\n"
    "1. 仔细分析JD，提取核心要求：岗位实际职责、必备技能栈、经验要求、行业方向\n"
    "2. 将JD的核心职责和技能要求与求职者的背景进行严格匹配\n"
    "3. 根据匹配结果生成招呼语或返回SKIP\n\n"
    "## 严格匹配规则（重要）\n"
    "- 匹配判断必须基于岗位实际职责和技能栈，而不是关键词字面相似\n"
    "- 求职意向为「AI 全栈/全栈开发」时，匹配的岗位必须是：使用AI技术做软件开发/工程的岗位，"
    "职责包含大模型应用开发、Agent开发、RAG、前后端开发、模型微调训练等\n"
    "- 以下类型必须 SKIP（即使含「AI」字样）：\n"
    "  * AI内容创作（短剧编剧、漫画/漫剧制作、AI绘画生图等）\n"
    "  * AI产品运营/推广/直播/销售\n"
    "  * 行业与AI结合但无需工程开发（法律/医疗/教育等领域的AI运营）\n"
    "  * JD核心技能不含编程语言/框架/模型开发的岗位\n"
    "- 核心技能或职责不重合的岗位一律 SKIP，宁缺毋滥\n\n"
    "## 招呼语要求（仅匹配时）\n"
    "- 不超过100字\n"
    "- 针对JD中的具体技术要求，提及求职者与之匹配的技能或经验\n"
    "- 语气自然、真诚、专业，避免模板化\n"
    "- 提及JD中的关键技术词或业务方向，体现契合度\n\n"
    "## 注意事项\n"
    "- 不要输出 MATCH、匹配、不匹配等判断标签\n"
    "- 不要加引号、前缀、解释或任何多余文字\n"
    "- 不要出现'我看了贵公司的招聘'等套话\n"
    "- 只输出 SKIP 或招呼语内容，二选一"
)


def _is_managed_provider(provider: str) -> bool:
    if not provider:
        return False
    if provider.startswith(f"{CUSTOM_PROVIDER_KEY}:"):
        return True
    if provider in PROVIDERS:
        return True
    return False


def _call_api(base_url: str, model: str, api_key: str, system_prompt: str, user_content: str) -> str:
    url = base_url.rstrip('/')
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": 300,
        "temperature": 0.7,
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            data = json.loads(body)
            return data["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"AI API 返回错误 {e.code}: {body[:300]}")
    except Exception as e:
        raise RuntimeError(f"AI API 调用失败: {e}")


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
        sections.append(f"## 期望岗位描述（匹配判断依据）\n{expect_jd.strip()[:1500]}\n\n请将下方「岗位JD信息」与此期望岗位描述严格比对，职责/技能栈不重合则输出 SKIP。")
    if resume and resume.strip():
        sections.append(f"## 求职者背景\n{resume.strip()[:1000]}")
    sections.append(f"## 岗位JD信息\n{jd_text}")
    sections.append("请根据以上信息判断匹配度，匹配则生成针对该JD的招呼语，不匹配则输出 SKIP。")
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
        defaults = _PROVIDER_DEFAULTS.get(config.provider, _PROVIDER_DEFAULTS["deepseek"])
        base_url = config.base_url.strip() or defaults["base_url"]
        model = config.model.strip() or defaults["model"]
        api_key = config.api_key.strip()
        if not api_key:
            raise RuntimeError("AI API Key 未配置")
        result = await asyncio.to_thread(_call_api, base_url, model, api_key, _SYSTEM_PROMPT, user_content)

    result = _clean_result(result)

    if result.upper() == "SKIP" or result.upper().startswith("SKIP"):
        return False, ""

    return True, result
