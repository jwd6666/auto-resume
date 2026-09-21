"""更新检查服务：定期从云端拉取最新版本，与本地版本对比。

- 版本号来源：环境变量 AUTORESUME_APP_VERSION（Electron 打包时注入 package.json 的 version）
- 用户偏好（是否提示 / 跳过的版本）持久化在 data/update_settings.json
- 前端只与本模块暴露的本地接口交互，不直连云端
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
from typing import Any

import httpx

from .config import APP_VERSION, CLOUD_SERVER_URL, DATA_DIR

logger = logging.getLogger("autoresume.updates")

CHECK_INTERVAL_SECONDS = 3600  # 登录状态下每小时检查一次
SETTINGS_FILE = DATA_DIR / "update_settings.json"


def compare_versions(a: str, b: str) -> int:
    """语义化版本比较：a>b 返回 1，a<b 返回 -1，相等返回 0。"""

    def norm(v: str) -> list[int]:
        core = v.split("-")[0]
        return [int(x) for x in core.split(".")]

    na, nb = norm(a), norm(b)
    length = max(len(na), len(nb))
    na += [0] * (length - len(na))
    nb += [0] * (length - len(nb))
    for x, y in zip(na, nb):
        if x != y:
            return 1 if x > y else -1
    return 0


class UpdateService:
    def __init__(self) -> None:
        self.latest: dict[str, Any] | None = None  # 云端最新已发布版本
        self.last_checked_at: dt.datetime | None = None
        self._task: asyncio.Task | None = None

    # ---------- 用户偏好 ----------

    def load_settings(self) -> dict[str, Any]:
        defaults: dict[str, Any] = {"prompt_enabled": True, "skipped_version": None}
        try:
            if SETTINGS_FILE.exists():
                data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                return {**defaults, **data}
        except (OSError, json.JSONDecodeError):
            pass
        return defaults

    def save_settings(self, prompt_enabled: bool | None = None, skip_version: str | None = None) -> dict[str, Any]:
        settings = self.load_settings()
        if prompt_enabled is not None:
            settings["prompt_enabled"] = prompt_enabled
        if skip_version is not None:
            settings["skipped_version"] = skip_version or None
        try:
            SETTINGS_FILE.write_text(json.dumps(settings, ensure_ascii=False), encoding="utf-8")
        except OSError:
            logger.exception("更新设置写入失败")
        return settings

    # ---------- 检查 ----------

    def update_available(self) -> bool:
        if not self.latest:
            return False
        return compare_versions(self.latest.get("version", ""), APP_VERSION) > 0

    def status(self) -> dict[str, Any]:
        settings = self.load_settings()
        available = self.update_available()
        # 强制更新不受"关闭提示"和"跳过版本"影响
        forced = available and bool(self.latest and self.latest.get("force"))
        skipped = (
            not forced
            and available
            and bool(self.latest)
            and self.latest.get("version") == settings.get("skipped_version")
        )
        should_prompt = available and (forced or (settings.get("prompt_enabled", True) and not skipped))
        return {
            "current_version": APP_VERSION,
            "latest": self.latest,
            "update_available": available,
            "force": forced,
            "prompt_enabled": settings.get("prompt_enabled", True),
            "skipped_version": settings.get("skipped_version"),
            "should_prompt": should_prompt,
            "last_checked_at": self.last_heartbeat_iso(),
        }

    def last_heartbeat_iso(self) -> str | None:
        if not self.last_checked_at:
            return None
        return self.last_checked_at.isoformat()

    async def check_once(self, token: str) -> None:
        """带云端 token 拉一次最新版本。失败静默（更新检查不能影响主流程）。"""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{CLOUD_SERVER_URL}/client/latest-release",
                    headers={"Authorization": f"Bearer {token}"},
                )
            if resp.status_code == 200:
                data = resp.json()
                self.latest = data if data else None
                self.last_checked_at = dt.datetime.utcnow()
                if self.latest:
                    logger.info("云端最新版本：%s", self.latest.get("version"))
            elif resp.status_code == 404:
                self.latest = None
            # 401/403（未登录/封禁）：由心跳模块处理，这里不管
        except httpx.HTTPError:
            pass

    def start_periodic_check(self, token_provider) -> None:
        """登录成功后启动。token_provider 是返回当前云端 token 的可调用。"""
        if self._task and not self._task.done():
            return

        async def loop() -> None:
            while True:
                token = token_provider()
                if token:
                    await self.check_once(token)
                await asyncio.sleep(CHECK_INTERVAL_SECONDS)

        self._task = asyncio.get_event_loop().create_task(loop())

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None


# 全局单例
update_service = UpdateService()
