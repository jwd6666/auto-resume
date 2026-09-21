"""云端鉴权客户端：登录、token 持久化、心跳保活、封禁检测。

职责：
  - 启动时加载本地缓存 session，向云端验证一次
  - 运行中每 60s 心跳一次，云端封禁后本地立即进入 banned 状态
  - 网络中断给予宽限期（HEARTBEAT_GRACE_HOURS），超时强制重新登录
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
from pathlib import Path
from typing import Any

import httpx

from .config import CLOUD_SERVER_URL, DATA_DIR
from .updates import update_service

logger = logging.getLogger("autoresume.cloud_auth")

HEARTBEAT_INTERVAL_SECONDS = 60
HEARTBEAT_GRACE_HOURS = 24  # 断网宽限期：超过则要求重新登录

SESSION_FILE = DATA_DIR / "cloud_session.json"

# 状态：not_logged_in / active / banned
STATUS_NOT_LOGGED_IN = "not_logged_in"
STATUS_ACTIVE = "active"
STATUS_BANNED = "banned"


class CloudAuthError(Exception):
    """云端返回的业务错误（如密码错误、被封禁）。"""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class CloudAuth:
    def __init__(self) -> None:
        self.status: str = STATUS_NOT_LOGGED_IN
        self.ban_reason: str | None = None
        self.user_info: dict[str, Any] | None = None
        self._token: str | None = None
        self._last_heartbeat_ok: dt.datetime | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    # ---------- 状态查询 ----------

    @property
    def logged_in(self) -> bool:
        return self.status == STATUS_ACTIVE

    def current_token(self) -> str | None:
        """供更新检查等模块使用的当前云端 token。"""
        return self._token

    def snapshot(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "user": self.user_info,
            "ban_reason": self.ban_reason,
            "cloud_server": CLOUD_SERVER_URL,
        }

    # ---------- 登录 / 登出 ----------

    async def login(self, account: str, password: str) -> dict[str, Any]:
        async with self._lock:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.post(
                        f"{CLOUD_SERVER_URL}/auth/login",
                        json={"account": account, "password": password},
                    )
            except httpx.HTTPError as e:
                raise CloudAuthError(f"无法连接服务器：{e}", 502)

            if resp.status_code == 200:
                data = resp.json()
                self._apply_login(data["token"], data["user"])
                self._start_heartbeat()
                return self.snapshot()

            detail = self._error_detail(resp)
            raise CloudAuthError(detail, resp.status_code)

    async def logout(self) -> dict[str, Any]:
        async with self._lock:
            self._reset()
            self._persist_session()
            self._stop_heartbeat()
            update_service.stop()
            return self.snapshot()

    # ---------- 启动恢复 ----------

    async def restore_session(self) -> None:
        """进程启动时调用：有缓存 token 则验证并恢复会话。"""
        cached = self._load_session()
        if not cached or not cached.get("token"):
            return
        self._token = cached["token"]
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{CLOUD_SERVER_URL}/auth/heartbeat",
                    headers=self._auth_headers(),
                )
        except httpx.HTTPError:
            # 云端不可达：宽限期内允许离线使用
            saved_at = self._parse_time(cached.get("saved_at"))
            if saved_at and (dt.datetime.utcnow() - saved_at).total_seconds() < HEARTBEAT_GRACE_HOURS * 3600:
                self.status = STATUS_ACTIVE
                self.user_info = cached.get("user")
                self._last_heartbeat_ok = saved_at
                self._start_heartbeat()
                logger.info("云端不可达，会话在宽限期内继续有效")
            else:
                self._reset()
            return

        if resp.status_code == 200:
            await self._refresh_user_info()
            self.status = STATUS_ACTIVE
            self._last_heartbeat_ok = dt.datetime.utcnow()
            self._persist_session()
            self._start_heartbeat()
            update_service.start_periodic_check(self.current_token)
            logger.info("会话恢复成功： %s", self.user_info and self.user_info.get("email"))
        elif resp.status_code == 403:
            self.status = STATUS_BANNED
            self.ban_reason = self._error_detail(resp)
            logger.warning("账户已被封禁")
        else:
            # token 过期等
            self._reset()

    async def _refresh_user_info(self) -> None:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{CLOUD_SERVER_URL}/auth/me", headers=self._auth_headers()
                )
            if resp.status_code == 200:
                self.user_info = resp.json()
        except httpx.HTTPError:
            pass  # 用户信息刷新失败不影响登录态

    # ---------- 心跳 ----------

    def _start_heartbeat(self) -> None:
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.get_event_loop().create_task(self._heartbeat_loop())

    def _stop_heartbeat(self) -> None:
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
        self._heartbeat_task = None

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
            try:
                await self._heartbeat_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 心跳线程不能因未知异常退出
                logger.exception("心跳异常")

    async def _heartbeat_once(self) -> None:
        if self.status not in (STATUS_ACTIVE,):
            return
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{CLOUD_SERVER_URL}/auth/heartbeat",
                    headers=self._auth_headers(),
                )
        except httpx.HTTPError:
            # 断网宽限检查
            if self._last_heartbeat_ok and (
                dt.datetime.utcnow() - self._last_heartbeat_ok
            ).total_seconds() >= HEARTBEAT_GRACE_HOURS * 3600:
                self._reset()
                logger.warning("断网超过宽限期，要求重新登录")
            return

        if resp.status_code == 200:
            self._last_heartbeat_ok = dt.datetime.utcnow()
        elif resp.status_code == 403:
            self.status = STATUS_BANNED
            self.ban_reason = self._error_detail(resp)
            logger.warning("心跳检测到账户被封禁")
        elif resp.status_code == 401:
            self._reset()
            logger.warning("会话已过期，要求重新登录")

    # ---------- 内部工具 ----------

    def _auth_headers(self) -> dict[str, str]:
        if not self._token:
            raise CloudAuthError("未登录", 401)
        return {"Authorization": f"Bearer {self._token}"}

    def _apply_login(self, token: str, user: dict[str, Any]) -> None:
        self._token = token
        self.user_info = user
        self.status = STATUS_ACTIVE
        self.ban_reason = None
        self._last_heartbeat_ok = dt.datetime.utcnow()
        self._persist_session()
        update_service.start_periodic_check(self.current_token)

    def _reset(self) -> None:
        self._token = None
        self.user_info = None
        self.status = STATUS_NOT_LOGGED_IN
        self.ban_reason = None
        self._last_heartbeat_ok = None

    def _persist_session(self) -> None:
        try:
            if not self._token:
                SESSION_FILE.unlink(missing_ok=True)
                return
            SESSION_FILE.write_text(
                json.dumps(
                    {
                        "token": self._token,
                        "user": self.user_info,
                        "saved_at": dt.datetime.utcnow().isoformat(),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except OSError:
            logger.exception("会话缓存写入失败")

    def _load_session(self) -> dict[str, Any] | None:
        try:
            if not SESSION_FILE.exists():
                return None
            return json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    @staticmethod
    def _parse_time(value: str | None) -> dt.datetime | None:
        if not value:
            return None
        try:
            return dt.datetime.fromisoformat(value)
        except ValueError:
            return None

    @staticmethod
    def _error_detail(resp: httpx.Response) -> str:
        try:
            data = resp.json()
            return data.get("detail") or f"服务器返回 {resp.status_code}"
        except ValueError:
            return f"服务器返回 {resp.status_code}"


# 全局单例
cloud_auth = CloudAuth()
