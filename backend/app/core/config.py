"""全局配置：路径、默认参数。

数据目录优先级：
  1. 环境变量 AUTORESUME_DATA_DIR（打包后由 run_server.py 注入到 %APPDATA%/AutoResume）
  2. 项目根 backend/data（开发期默认）
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
_env_data = os.environ.get("AUTORESUME_DATA_DIR")
DATA_DIR = Path(_env_data) if _env_data else BASE_DIR / "data"
PROFILES_DIR = DATA_DIR / "profiles"
LOGS_DIR = DATA_DIR / "logs"
WORKSPACE_DIR = DATA_DIR / "workspace"
RESUME_STORE_DIR = DATA_DIR / "resume_store"
AVATARS_DIR = DATA_DIR / "avatars"
GREET_IMAGES_DIR = DATA_DIR / "greet_images"
DB_PATH = DATA_DIR / "auto_resume.sqlite"
RESUME_DB_PATH = DATA_DIR / "resume_agent.db"

DATA_DIR.mkdir(parents=True, exist_ok=True)
PROFILES_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
RESUME_STORE_DIR.mkdir(parents=True, exist_ok=True)
AVATARS_DIR.mkdir(parents=True, exist_ok=True)
GREET_IMAGES_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_INTERVAL_SECONDS = 5
DEFAULT_DAILY_LIMIT = 10
DEFAULT_CLICK_DELAY_SECONDS = 5  # 点开左侧岗位 → 等多久 → 点右侧「立即沟通」
BOSS_HOME = "https://www.zhipin.com/"
BOSS_SEARCH_URL = "https://www.zhipin.com/web/geek/job"
BOSS_CHAT_URL = "https://www.zhipin.com/web/geek/chat"

# 云端管控服务器地址：开发环境 → 本地；生产环境（Electron 打包注入） → 云端
# 环境变量优先，未设置时根据是否由 sidecar 注入 API_TOKEN 判断环境
_api_token = os.environ.get("AUTORESUME_API_TOKEN", "")
if os.environ.get("AUTORESUME_CLOUD_URL"):
    CLOUD_SERVER_URL = os.environ["AUTORESUME_CLOUD_URL"]
elif _api_token:
    CLOUD_SERVER_URL = "https://agentht.jwdo.top"
else:
    CLOUD_SERVER_URL = "http://127.0.0.1:8000"

# 本地 sidecar 访问令牌：Electron 主进程每次启动随机生成并经环境变量注入。
# 为空表示开发模式（uvicorn 手动启动），此时跳过令牌校验。
API_TOKEN: str = os.environ.get("AUTORESUME_API_TOKEN", "")

# 应用版本号（Electron 打包时注入 package.json 的 version，用于更新检查对比）
APP_VERSION = os.environ.get("AUTORESUME_APP_VERSION", "0.0.0-dev")
