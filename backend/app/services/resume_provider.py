"""简历 Agent 多 AI 提供商抽象层 — 统一入口（re-export）。

设置文件路径：backend/app/ai_settings.json
.env 文件路径：backend/.env

实现已拆分至：
  - provider_settings.py  配置管理、内置 provider 定义、自定义模型 CRUD
  - provider_openai.py    OpenAI 兼容适配、JSON 参数修复
  - provider_anthropic.py Anthropic Claude 适配、格式转换
  - provider_core.py      公共 API 调度、debug 日志、SSE 心跳
"""

from .provider_settings import (
    PROVIDERS,
    CUSTOM_PROVIDER_KEY,
    DEBUG_LOG_ENABLED,
    SETTINGS_FILE,
    _DEFAULT_SETTINGS,
    load_settings,
    save_settings,
    get_api_key,
    get_custom_model,
    add_custom_model,
    delete_custom_model,
    update_custom_model,
    _resolve_base_url,
    _resolve_current_provider,
    _get_context_input,
    _get_context_output,
    is_current_model_multimodal,
    is_cloud_provider,
    get_cloud_template_id,
)

from .provider_anthropic import (
    _convert_openai_images_to_anthropic,
    _convert_openai_tools_to_anthropic,
    _convert_openai_messages_to_anthropic_tool_messages,
    _stream_anthropic,
    _stream_anthropic_with_tools,
)

from .provider_openai import (
    _stream_openai_compat,
)

from .provider_core import (
    test_connection,
    stream_response,
    complete_response,
    complete_response_with_provider,
    complete_response_sync,
    sse_with_heartbeat,
    stream_with_tools,
    sanitize_anthropic_history,
    ConversationDebugLog,
)
