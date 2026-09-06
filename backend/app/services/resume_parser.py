"""简历 PDF 解析 — 统一使用模型管理中当前配置的模型，文本路径和 VL 路径都走同一模型。VL 路径要求当前模型支持多模态。"""
from __future__ import annotations

import base64
import io
from typing import AsyncGenerator, List, Optional, Tuple

from fastapi import HTTPException

from .resume_provider import (
    load_settings, is_current_model_multimodal,
    complete_response_sync, stream_response,
)

MAX_PDF_BYTES = 10 * 1024 * 1024
MIN_TEXT_CHARS_FOR_LLM = 200
MAX_VL_PAGES = 5

BACKGROUND_FORMAT_SPEC = """输出格式要求（必须严格遵守）：
1）使用纯文本，不要用 # 号标题；用大节标题行分段，格式为：emoji + 空格 + 标题（单独一行）。
2）推荐大节（无内容可整节省略）：📋 基本信息、🎓 学历、💼 实习经历、🚀 项目经历、🎨 个人作品集、⚡ 核心技能、💬 自我评价。
3）节与节之间空一行；节内字段用「字段名：」后接内容，可在一行内用「|」分隔多项（如联系方式）。
4）列表项以「•」开头，独占一行；经历块可先写「公司 | 岗位  时间段」再换行列点。
5）保留量化数据、时间、产品名等事实，不要编造。"""

SYSTEM_STRUCTURE = f"""你是简历整理助手。用户将提供从 PDF 抽取的原始文本，可能顺序混乱或有缺行。
请将内容整理为「候选人背景信息」正文，便于在对话区以纯文本分段展示。

{BACKGROUND_FORMAT_SPEC}

只输出整理后的正文，不要前言、后记或代码块包裹。"""

USER_TEXT_TEMPLATE = """以下是从简历 PDF 抽取的原始文本，请按上述格式整理：\n\n---\n\n{raw}\n\n---"""

SYSTEM_VL = f"""你是简历识别助手。用户会提供简历页面截图，请识别全部可见文字与结构，输出「候选人背景信息」正文。

{BACKGROUND_FORMAT_SPEC}

信息不足处如实简略，不要编造。只输出正文。"""


def _pypdf_extract(pdf_bytes: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(pdf_bytes))
    parts = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n".join(parts).strip()


def _pdf_pages_png_base64(pdf_bytes: bytes, max_pages: int) -> list:
    import fitz  # PyMuPDF
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        n = min(len(doc), max_pages)
        out = []
        for i in range(n):
            page = doc.load_page(i)
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            png_bytes = pix.tobytes("png")
            out.append(base64.b64encode(png_bytes).decode("ascii"))
        return out
    finally:
        doc.close()


def _messages_vl_path(images_b64: list) -> list:
    parts = []
    for b64 in images_b64:
        parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}"},
        })
    parts.append({
        "type": "text",
        "text": "请根据以上简历页面图片，按系统说明中的「纯文本 + emoji 大节」格式输出候选人背景信息正文。",
    })
    return [{"role": "system", "content": SYSTEM_VL}, {"role": "user", "content": parts}]


def parse_resume_pdf_to_background(pdf_bytes: bytes) -> Tuple[str, str, Optional[str]]:
    """返回 (整理后的 Markdown 正文, parser 标记, 可选 warning)。

    文本路径：使用当前模型管理配置的模型。
    VL 路径：使用当前模型管理配置的多模态模型，非多模态则报错提示。
    """
    if len(pdf_bytes) > MAX_PDF_BYTES:
        raise HTTPException(status_code=400, detail=f"PDF 文件过大，请小于 {MAX_PDF_BYTES // (1024 * 1024)}MB")

    settings = load_settings()
    raw = _pypdf_extract(pdf_bytes)
    warning: Optional[str] = None

    if len(raw) >= MIN_TEXT_CHARS_FOR_LLM:
        try:
            out = complete_response_sync(
                SYSTEM_STRUCTURE,
                [{"role": "user", "content": USER_TEXT_TEMPLATE.format(raw=raw[:120000])}],
                max_tokens=8192,
                timeout=600.0,
            )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"模型整理简历失败: {str(e)[:300]}") from e
        if not out.strip():
            raise HTTPException(status_code=502, detail="模型返回空内容，请重试或更换模型")
        return out, "pypdf+current_model", warning

    # VL 路径：扫描件 PDF
    if not is_current_model_multimodal(settings):
        raise HTTPException(
            status_code=400,
            detail="扫描件 PDF 需要多模态模型识别。请在「模型管理」中选择支持多模态的模型（如添加 glm-4-flash 并开启多模态标记），或改用文本型 PDF。",
        )

    try:
        images_b64 = _pdf_pages_png_base64(pdf_bytes, MAX_VL_PAGES)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"PDF 转图失败: {str(e)[:200]}") from e

    if not images_b64:
        raise HTTPException(status_code=400, detail="PDF 无可用页面")

    messages = _messages_vl_path(images_b64)
    try:
        out = complete_response_sync(SYSTEM_VL, messages, max_tokens=8192, timeout=600.0)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"多模态模型识别简历失败: {str(e)[:300]}") from e

    if not out.strip():
        raise HTTPException(status_code=502, detail="模型返回空内容，请检查 PDF 是否清晰")

    if raw.strip():
        warning = "已从扫描类 PDF 中识别内容；若与预期不符，可改用文本型简历 PDF 重试。"

    return out, "pymupdf+current_model_vl", warning


async def stream_resume_pdf_to_background(pdf_bytes: bytes) -> AsyncGenerator[str, None]:
    """流式解析简历 PDF，逐块 yield 文本。格式为 SSE data 行，包含 type 和 content。

    事件类型：
    - progress: 解析进度提示（如"正在提取文本..."）
    - text: 模型输出文本块
    - done: 解析完成，附带 parser 和 warning 元信息
    - error: 出错
    """
    import json

    if len(pdf_bytes) > MAX_PDF_BYTES:
        msg = f"PDF 文件过大，请小于 {MAX_PDF_BYTES // (1024 * 1024)}MB"
        yield f"data: {json.dumps({'type': 'error', 'content': msg})}\n\n"
        return

    settings = load_settings()
    raw = _pypdf_extract(pdf_bytes)
    warning: Optional[str] = None
    parser_tag = "pypdf+current_model"

    if len(raw) >= MIN_TEXT_CHARS_FOR_LLM:
        yield f"data: {json.dumps({'type': 'progress', 'content': '正在整理简历文本...'})}\n\n"
        system = SYSTEM_STRUCTURE
        messages = [{"role": "user", "content": USER_TEXT_TEMPLATE.format(raw=raw[:120000])}]
        try:
            async for text in stream_response(system, messages):
                yield f"data: {json.dumps({'type': 'text', 'content': text})}\n\n"
        except Exception as e:
            msg = f"模型整理简历失败: {str(e)[:300]}"
            yield f"data: {json.dumps({'type': 'error', 'content': msg})}\n\n"
            return
    else:
        if not is_current_model_multimodal(settings):
            yield f"data: {json.dumps({'type': 'error', 'content': '扫描件 PDF 需要多模态模型识别。请在「模型管理」中选择支持多模态的模型，或改用文本型 PDF。'})}\n\n"
            return

        try:
            images_b64 = _pdf_pages_png_base64(pdf_bytes, MAX_VL_PAGES)
        except Exception as e:
            msg = f"PDF 转图失败: {str(e)[:200]}"
            yield f"data: {json.dumps({'type': 'error', 'content': msg})}\n\n"
            return

        if not images_b64:
            yield f"data: {json.dumps({'type': 'error', 'content': 'PDF 无可用页面'})}\n\n"
            return

        parser_tag = "pymupdf+current_model_vl"
        yield f"data: {json.dumps({'type': 'progress', 'content': '正在识别扫描件 PDF...'})}\n\n"
        messages = _messages_vl_path(images_b64)
        try:
            async for text in stream_response(SYSTEM_VL, messages):
                yield f"data: {json.dumps({'type': 'text', 'content': text})}\n\n"
        except Exception as e:
            msg = f"多模态模型识别简历失败: {str(e)[:300]}"
            yield f"data: {json.dumps({'type': 'error', 'content': msg})}\n\n"
            return

        if raw.strip():
            warning = "已从扫描类 PDF 中识别内容；若与预期不符，可改用文本型简历 PDF 重试。"

    yield f"data: {json.dumps({'type': 'done', 'parser': parser_tag, 'warning': warning})}\n\n"
