"""AI 招呼语生成服务：根据岗位 JD 信息调用大模型生成个性化打招呼内容。

支持 OpenAI 兼容 API 格式的多个提供商：
- DeepSeek
- GLM（智谱）
- Qwen（通义千问）
- OpenAI
"""
from __future__ import annotations

import asyncio
import json
import urllib.request
import urllib.error
from typing import Optional, Tuple

from ..schemas.task import AIConfig

# 各提供商默认配置（base_url + model）
# base_url 是完整的 chat completions 端点，直接使用不做拼接
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

# 系统提示：先判断 JD 是否与求职意向匹配，匹配则根据 JD 核心要求生成有针对性的招呼语
_SYSTEM_PROMPT = (
    "你是一位资深求职打招呼助手。你的任务是根据招聘JD和求职者的背景，判断匹配度并生成让HR觉得求职者很适合该岗位的招呼语。\n\n"
    "## 工作流程\n"
    "1. 仔细分析JD，提取核心要求：岗位关键词、必备技能、经验要求、加分项\n"
    "2. 将JD要求与求职者背景进行匹配评估\n"
    "3. 根据匹配结果生成招呼语或返回SKIP\n\n"
    "## 规则\n"
    "- 不匹配（核心技能/经验差距过大）：只回复 SKIP\n"
    "- 匹配：直接回复打招呼内容，要求：\n"
    "  * 不超过100字\n"
    "  * 针对JD中的具体要求，提及求职者与之匹配的技能或经验\n"
    "  * 展示对岗位的理解和诚意\n"
    "  * 语气自然、真诚、专业，避免模板化\n"
    "  * 适当提及JD中的关键技术词或业务方向，体现契合度\n\n"
    "## 注意事项\n"
    "- 不要输出 MATCH、匹配、不匹配等判断标签\n"
    "- 不要加引号、前缀、解释或任何多余文字\n"
    "- 不要出现'我看了贵公司的招聘'等套话\n"
    "- 只输出 SKIP 或招呼语内容，二选一"
)


def _resolve_config(config: AIConfig) -> tuple[str, str, str]:
    """返回 (base_url, model, api_key)，空值用 provider 默认填充。"""
    defaults = _PROVIDER_DEFAULTS.get(config.provider, _PROVIDER_DEFAULTS["deepseek"])
    base_url = config.base_url.strip() or defaults["base_url"]
    model = config.model.strip() or defaults["model"]
    api_key = config.api_key.strip()
    return base_url, model, api_key


def _call_api(base_url: str, model: str, api_key: str, system_prompt: str, user_content: str) -> str:
    """同步调用 OpenAI 兼容 API，返回 AI 响应文本。直接使用传入的 URL，不做拼接。"""
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


async def generate_greeting(config: AIConfig, jd_text: str, keyword: str = "", resume: str = "") -> Tuple[bool, str]:
    """根据 JD 文本调用 AI 判断是否匹配并生成招呼语。

    参数：
        config: AI 配置（provider/api_key 等）
        jd_text: 岗位 JD 全文
        keyword: 求职搜索关键词，如 "Python 后端"
        resume: 求职者个人简介/技能摘要（可选），用于生成更有针对性的招呼语

    返回 (should_greet, greeting)：
    - should_greet=True, greeting=AI 生成的招呼语
    - should_greet=False, greeting="" 表示 AI 判断不匹配，应跳过
    如果调用失败会抛出 RuntimeError。
    """
    base_url, model, api_key = _resolve_config(config)
    if not api_key:
        raise RuntimeError("AI API Key 未配置")

    # JD 文本截断，避免过长
    jd_text = jd_text[:2000] if len(jd_text) > 2000 else jd_text

    # 构造结构化的用户消息，让 AI 能充分理解 JD 要求和求职者背景
    sections = [f"## 求职意向\n{keyword or '未指定'}"]
    if resume and resume.strip():
        sections.append(f"## 求职者背景\n{resume.strip()[:1000]}")
    sections.append(f"## 岗位JD信息\n{jd_text}")
    sections.append("请根据以上信息判断匹配度，匹配则生成针对该JD的招呼语，不匹配则输出 SKIP。")
    user_content = "\n\n".join(sections)

    # 在线程池中执行同步 HTTP 请求
    result = await asyncio.to_thread(_call_api, base_url, model, api_key, _SYSTEM_PROMPT, user_content)

    # 清理 AI 可能输出的多余前缀（MATCH、匹配、招呼语：等）
    result = result.strip()
    for prefix in ("MATCH", "Match", "match", "匹配", "招呼语：", "招呼语:", "打招呼：", "打招呼:"):
        if result.startswith(prefix):
            result = result[len(prefix):].strip()

    # AI 返回 SKIP 表示不匹配，应跳过
    if result.upper() == "SKIP" or result.upper().startswith("SKIP"):
        return False, ""

    # 去掉首尾引号
    if len(result) >= 2 and result[0] in '"「『"' and result[-1] in '"」』"':
        result = result[1:-1].strip()

    return True, result
