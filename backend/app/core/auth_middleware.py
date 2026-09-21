"""ASGI 鉴权中间件。

- 令牌校验（生产模式）：所有请求须携带主进程注入的随机令牌（HTTP: X-Api-Token
  头或 token 查询参数；WebSocket: token 查询参数），防本机其他程序直接调用接口
- 白名单：/health、/api/auth/*（登录本身）始终放行
- 已登录：全部放行
- 被封禁：除白名单外全部拦截（HTTP 403 / WebSocket 1008）
- 未登录（跳过登录直接使用）：业务功能全部放行，
  仅拦截需要登录的功能（云端模型、自定义模型管理）
"""
from __future__ import annotations

import hmac
import json
from urllib.parse import parse_qsl

from starlette.types import ASGIApp, Receive, Scope, Send

from ..core.config import API_TOKEN
from ..core.cloud_auth import STATUS_ACTIVE, STATUS_BANNED, cloud_auth

WHITELIST_PREFIXES = ("/health", "/api/auth")

LOGIN_REQUIRED_EXACT = (
    "/api/auth/cloud-models",
    "/api/auth/cloud-activate",
    "/api/auth/change-password",
)
LOGIN_REQUIRED_PREFIXES = (
    "/agent/settings/custom-models",
    "/agent/settings/test-custom-model",
)


def _is_whitelisted(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") or path.startswith(p + "?") for p in WHITELIST_PREFIXES) or path in WHITELIST_PREFIXES


def _requires_login(path: str) -> bool:
    if path in LOGIN_REQUIRED_EXACT:
        return True
    return any(path == p or path.startswith(p + "/") or path.startswith(p + "?") for p in LOGIN_REQUIRED_PREFIXES)


class CloudAuthMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        # 生产模式：校验主进程注入的随机令牌（开发模式 API_TOKEN 为空，跳过）
        if API_TOKEN:
            token = self._extract_token(scope)
            if not token or not hmac.compare_digest(token, API_TOKEN):
                await self._reject(scope, send, 401, "invalid api token")
                return

        path: str = scope.get("path", "")
        if _is_whitelisted(path) and not _requires_login(path):
            await self.app(scope, receive, send)
            return

        status = cloud_auth.status
        if status == STATUS_ACTIVE:
            await self.app(scope, receive, send)
            return

        if status == STATUS_BANNED:
            await self._reject(scope, send, 403, cloud_auth.ban_reason or "账户已被禁用")
            return

        if _requires_login(path):
            await self._reject(scope, send, 401, "该功能需要登录后使用，请先登录")
            return

        await self.app(scope, receive, send)

    @staticmethod
    def _extract_token(scope: Scope) -> str | None:
        """提取访问令牌：优先 X-Api-Token 头；兼容 token 查询参数。

        查询参数兜底是必须的：WebSocket 无法自定义请求头，
        webview/导出链接等场景也无法携带自定义头。
        """
        for name, value in scope.get("headers", []):
            if name == b"x-api-token":
                return value.decode("latin-1")
        query_string: bytes = scope.get("query_string", b"")
        if query_string:
            for key, value in parse_qsl(query_string.decode("latin-1")):
                if key == "token" and value:
                    return value
        return None

    @staticmethod
    async def _reject(scope: Scope, send: Send, code: int, message: str) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008, "reason": "unauthorized"})
            return
        body = json.dumps({"detail": message})
        await send(
            {
                "type": "http.response.start",
                "status": code,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body.encode())).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body.encode()})
