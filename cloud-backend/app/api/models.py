"""模型模板管理 API：管理员 CRUD + 客户端拉取 + 云端代理聊天。"""
from __future__ import annotations

import asyncio
import datetime as dt
import json

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..core import quota
from ..core.deps import get_admin_user, get_current_user, get_db
from ..db.models import ModelTemplate
from ..schemas.auth import (
    ModelTemplateClientOut,
    ModelTemplateCreate,
    ModelTemplateOut,
    ModelTemplateUpdate,
)

admin_router = APIRouter(prefix="/admin/models", tags=["admin-models"], dependencies=[Depends(get_admin_user)])
client_router = APIRouter(prefix="/client/models", tags=["client-models"])


def _to_out(t: ModelTemplate) -> dict:
    d = {
        "id": t.id,
        "display_name": t.display_name,
        "api_format": t.api_format,
        "base_url": t.base_url,
        "full_url": t.full_url,
        "model_id": t.model_id,
        "multimodal": t.multimodal,
        "model_series": t.model_series,
        "api_key_set": bool(t.api_key),
        "context_input": t.context_input,
        "context_output": t.context_output,
        "tool_call_rounds": t.tool_call_rounds,
        "published": t.published,
        "sort_order": t.sort_order,
        "created_at": t.created_at,
        "updated_at": t.updated_at,
    }
    return d


# ── 管理端 ──


@admin_router.get("", response_model=dict)
def list_templates(
    db: Session = Depends(get_db),
    published: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    q = db.query(ModelTemplate)
    if published is not None:
        q = q.filter(ModelTemplate.published == published)
    total = q.count()
    items = q.order_by(ModelTemplate.sort_order, ModelTemplate.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"total": total, "page": page, "page_size": page_size, "items": [_to_out(t) for t in items]}


@admin_router.post("", response_model=dict)
def create_template(body: ModelTemplateCreate, db: Session = Depends(get_db)):
    t = ModelTemplate(**body.model_dump())
    db.add(t)
    db.commit()
    db.refresh(t)
    return _to_out(t)


@admin_router.put("/{template_id}", response_model=dict)
def update_template(template_id: int, body: ModelTemplateUpdate, db: Session = Depends(get_db)):
    t = db.get(ModelTemplate, template_id)
    if t is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    update_data = body.model_dump(exclude_unset=True)
    for k, v in update_data.items():
        setattr(t, k, v)
    t.updated_at = dt.datetime.utcnow()
    db.commit()
    db.refresh(t)
    return _to_out(t)


@admin_router.delete("/{template_id}", response_model=dict)
def delete_template(template_id: int, db: Session = Depends(get_db)):
    t = db.get(ModelTemplate, template_id)
    if t is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    db.delete(t)
    db.commit()
    return {"ok": True}


@admin_router.post("/{template_id}/publish", response_model=dict)
def toggle_publish(template_id: int, body: dict, db: Session = Depends(get_db)):
    t = db.get(ModelTemplate, template_id)
    if t is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    t.published = bool(body.get("published", True))
    t.updated_at = dt.datetime.utcnow()
    db.commit()
    db.refresh(t)
    return _to_out(t)


# ── 客户端 ──


@client_router.get("", response_model=list[ModelTemplateClientOut])
def list_published_templates(user=Depends(get_current_user), db: Session = Depends(get_db)):
    items = db.query(ModelTemplate).filter(ModelTemplate.published == True).order_by(ModelTemplate.sort_order, ModelTemplate.id).all()
    return [ModelTemplateClientOut.model_validate(t, from_attributes=True) for t in items]


class CloudChatRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    template_id: int
    messages: list[dict] = Field(min_length=1)
    max_tokens: int = Field(default=4096, ge=1, le=128000)
    stream: bool = False
    tools: list[dict] | None = None
    tool_choice: str | None = None
    # 功能来源（额度用量明细）：greeting/chat/copy/interview/resume/test，缺省 other
    source: str = Field(default="other", max_length=32)


@client_router.post("/chat")
async def cloud_chat(body: CloudChatRequest, user=Depends(get_current_user), db: Session = Depends(get_db)):
    """云端代理：用模板中存储的 API Key 转发请求到模型服务商。"""
    t = db.get(ModelTemplate, body.template_id)
    if t is None or not t.published:
        raise HTTPException(status_code=404, detail="模型模板不存在或未发布")
    if not t.api_key:
        raise HTTPException(status_code=400, detail="该模板未配置 API Key，请联系管理员")
    if not t.base_url:
        raise HTTPException(status_code=400, detail="该模板未配置 Base URL")

    # 关键：提前把 ORM 属性提取为普通变量。FastAPI ≥0.106 在返回 StreamingResponse 后、
    # 流式输出前就会关闭依赖会话；生成器内再访问 ORM 属性会触发 DetachedInstanceError，
    # 导致连接被硬切断（客户端表现为 incomplete chunked read）且配额结转永远不执行。
    api_key = t.api_key
    user_id = user.id
    source = body.source

    base_url = t.base_url.rstrip("/")
    # full_url=True：base_url 已是完整接口地址，原样使用；否则按 OpenAI 兼容拼接
    url = base_url if t.full_url else f"{base_url}/chat/completions"

    payload = {
        "model": t.model_id,
        "messages": body.messages,
        "max_tokens": body.max_tokens,
        "stream": body.stream,
    }
    if body.tools:
        payload["tools"] = body.tools
        if body.tool_choice is not None:
            payload["tool_choice"] = body.tool_choice

    # ── 配额预留：输入估算 + max_tokens，请求期间占用，结束后按实际用量结转 ──
    # 生效额度：个人额度覆盖 > 整体默认额度（管理后台可调）> 环境变量默认
    reserved, est_input = quota.estimate_request_tokens(body.messages, body.tools, body.max_tokens)
    day = quota.today_str()
    cap = quota.effective_quota(db, user.id)
    ok, used = quota.reserve_tokens(db, user.id, reserved, day, cap)
    if not ok:
        raise HTTPException(
            status_code=429,
            detail=(
                f"今日云端模型配额不足（已用 {used} / {cap} tokens），"
                "请减小请求规模（降低 max_tokens）、联系管理员提升额度或明天再试"
            ),
        )
    # 配额准入成功后同步记录按来源的用量明细（仅统计展示用）
    quota.reserve_source_tokens(db, user.id, source, reserved, day)

    if body.stream:
        from fastapi.responses import StreamingResponse

        async def _stream():
            output_chars = 0
            actual_usage: int | None = None
            settled_actual: int | None = None

            def _account_chunk(data_str: str) -> None:
                """解析 chunk 记录 usage 与输出字符数，仅用于配额结转，不影响转发。"""
                nonlocal output_chars, actual_usage
                try:
                    obj = json.loads(data_str)
                    if not isinstance(obj, dict):
                        return
                    usage = obj.get("usage")
                    if isinstance(usage, dict) and usage.get("total_tokens"):
                        actual_usage = int(usage["total_tokens"])
                    choices = obj.get("choices") or []
                    if choices:
                        delta = (choices[0] or {}).get("delta") or {}
                        content = delta.get("content")
                        if isinstance(content, str):
                            output_chars += len(content)
                        for tc in delta.get("tool_calls") or []:
                            args = ((tc or {}).get("function") or {}).get("arguments")
                            if isinstance(args, str):
                                output_chars += len(args)
                except Exception:
                    pass

            async def _relay():
                """读取上游并产出 SSE 字节；任意等待阶段都可能长时间无输出。"""
                nonlocal output_chars, actual_usage, settled_actual
                try:
                    async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=15.0)) as client:
                        async with client.stream("POST", url, json=payload, headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        }) as resp:
                            if resp.status_code != 200:
                                error_body = await resp.aread()
                                settled_actual = 0  # 上游报错不扣配额
                                try:
                                    err = json.loads(error_body)
                                    yield f"data: {json.dumps({'error': err.get('detail', f'HTTP {resp.status_code}')}, ensure_ascii=False)}\n\n".encode()
                                except Exception:
                                    yield f"data: {json.dumps({'error': f'HTTP {resp.status_code}'})}\n\n".encode()
                                yield b"data: [DONE]\n\n"
                                return

                            sse_buf = b""
                            done_seen = False
                            upstream_error: str | None = None
                            try:
                                async for chunk in resp.aiter_bytes():
                                    sse_buf += chunk
                                    while b"\n" in sse_buf:
                                        line, sse_buf = sse_buf.split(b"\n", 1)
                                        decoded = line.decode("utf-8", errors="replace").strip()
                                        if not decoded or decoded.startswith(":") or decoded.startswith("event:"):
                                            continue
                                        if decoded.startswith("data:"):
                                            data_str = decoded[5:].strip()
                                            if data_str == "[DONE]":
                                                done_seen = True
                                                break
                                            if data_str:
                                                _account_chunk(data_str)
                                                yield f"data: {data_str}\n\n".encode()
                                        else:
                                            yield f"data: {decoded}\n\n".encode()
                                    if done_seen:
                                        break
                            except httpx.HTTPError as e:
                                err_str = str(e)
                                is_incomplete_chunked = "incomplete chunked" in err_str or "StreamClosed" in err_str or "peer closed" in err_str
                                if not done_seen:
                                    if is_incomplete_chunked and output_chars > 0:
                                        done_seen = True
                                    else:
                                        settled_actual = 0
                                        upstream_error = f"上游模型连接中断，输出可能不完整: {err_str[:120]}"

                            # flush 残留 buffer
                            if not done_seen and sse_buf.strip():
                                decoded = sse_buf.decode("utf-8", errors="replace").strip()
                                if decoded.startswith("data:"):
                                    data_str = decoded[5:].strip()
                                    if data_str == "[DONE]":
                                        done_seen = True
                                    elif data_str:
                                        _account_chunk(data_str)
                                        yield f"data: {data_str}\n\n".encode()
                                elif not decoded.startswith(":"):
                                    yield f"data: {decoded}\n\n".encode()

                            if upstream_error:
                                yield f"data: {json.dumps({'error': upstream_error}, ensure_ascii=False)}\n\n".encode()
                            yield b"data: [DONE]\n\n"
                except Exception as e:
                    # 兜底：未预期异常也以 SSE error 事件收尾，避免响应被硬切断（客户端会报 incomplete chunked read）
                    settled_actual = 0
                    yield f"data: {json.dumps({'error': f'云端代理内部错误: {str(e)[:150]}'}, ensure_ascii=False)}\n\n".encode()
                    yield b"data: [DONE]\n\n"

            # ── 心跳泵：推理模型首字可能 >60s，Nginx proxy_read_timeout 默认 60s 会掐断空闲连接。
            #    后台任务驱动 _relay，主循环每 15s 无数据就发 SSE 注释行保活（客户端解析器自动跳过）。──
            queue: asyncio.Queue = asyncio.Queue()
            _END = object()

            async def _pump():
                try:
                    async for ev in _relay():
                        await queue.put(ev)
                finally:
                    await queue.put(_END)

            task = asyncio.create_task(_pump())
            try:
                while True:
                    try:
                        item = await asyncio.wait_for(queue.get(), timeout=15.0)
                    except asyncio.TimeoutError:
                        yield b": keepalive\n\n"
                        continue
                    if item is _END:
                        break
                    yield item
            finally:
                task.cancel()
                # 配额结转：优先服务商 usage；无 usage 用字符估算；上游报错（settled_actual=0）全额退还。
                # finally 覆盖所有出口：正常结束、异常、客户端中途断开。
                actual = settled_actual
                if actual is None:
                    actual = actual_usage if actual_usage is not None else est_input + (output_chars + 1) // 2
                quota.reconcile_tokens(user_id, day, reserved, actual)
                quota.reconcile_source_tokens(user_id, day, source, reserved, actual)

        return StreamingResponse(
            _stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",  # 禁用 Nginx 响应缓冲
            },
        )

    # ── 非流式 ──
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
            resp = await client.post(url, json=payload, headers={
                "Authorization": f"Bearer {t.api_key}",
                "Content-Type": "application/json",
            })
    except httpx.HTTPError as e:
        # 连接失败不扣配额
        quota.reconcile_tokens(user.id, day, reserved, 0)
        quota.reconcile_source_tokens(user.id, day, source, reserved, 0)
        raise HTTPException(status_code=502, detail=f"上游模型连接失败：{str(e)[:200]}")

    if resp.status_code != 200:
        # 上游报错不扣配额
        quota.reconcile_tokens(user.id, day, reserved, 0)
        quota.reconcile_source_tokens(user.id, day, source, reserved, 0)
        raise HTTPException(status_code=resp.status_code, detail=resp.text[:500])

    data = resp.json()
    usage = data.get("usage") if isinstance(data, dict) else None
    if isinstance(usage, dict) and usage.get("total_tokens"):
        actual = int(usage["total_tokens"])
    else:
        actual = quota.fallback_actual_tokens(data, est_input)
    quota.reconcile_tokens(user.id, day, reserved, actual)
    quota.reconcile_source_tokens(user.id, day, source, reserved, actual)
    return data


@client_router.post("/chat/stream")
async def cloud_chat_stream(body: CloudChatRequest, user=Depends(get_current_user), db: Session = Depends(get_db)):
    """云端代理流式版本：SSE 转发。"""
    body.stream = True
    return await cloud_chat(body, user, db)
