"""
文本匹配模块：str_replace 的"找到要替换的片段"这一核心环节。

匹配策略（按优先级降级）：
1. 精确匹配：old_str 在完整文件内容中恰好出现 1 次  -> 直接命中。
   - 出现 0 次：进入降级策略。
   - 出现 >=2 次：ambiguity，拒绝修改（绝不猜测改哪一处）。
2. 降级策略（精确匹配失败时启用）：
   a. 空白符标准化：对 old_str 与文件内容做逐行 dedent + 统一换行为 \n 的规范化，
      再尝试精确匹配（容忍 Agent 使用了不同缩进/换行）。
   b. 若仍失败，使用 difflib 滑动窗口相似度匹配：遍历正则化后的文本，基于
      SequenceMatcher 计算每个候选窗口与 old_str 的相似度，取相似度最高的候选。
      - 最高相似度 < MIN_SIMILARITY 阈值 -> 视为找不到，报错并附当前文件片段。
      - 存在多个候选并列最高（含 top-1 与 top-2 差距小于 epsilon）-> 拒绝，避免改错位置。

任何匹配到"恰好一处"的结果，才能返回实际替换位置；多于一处的直接拒绝。
"""
from __future__ import annotations

from difflib import SequenceMatcher
from typing import List, Optional, Tuple

# 模糊匹配允许的最低相似度（0.0~1.0）
MIN_SIMILARITY = 0.70


class MatchResult:
    """一次成功的匹配结果，携带锚定信息用于后续生成 diff。"""

    __slots__ = ("start", "end", "matched_exact", "similarity")

    def __init__(self, start: int, end: int, matched_exact: bool, similarity: float = 1.0):
        self.start = start          # 在"原始文件字节/unicdoe字符"中的起始下标
        self.end = end              # 结束下标（不含）
        self.matched_exact = matched_exact  # 是否走精确匹配
        self.similarity = similarity  # 匹配相似度


def _normalize(text: str) -> str:
    """空白符标准化：保留单词/符号，仅折叠空白差异，便于模糊匹配。"""
    return " ".join(text.split())


def _find_exact(content: str, needle: str) -> Tuple[Optional[int], List[int]]:
    """在 content 中查找 needle 精确出现的位置。返回 (单次命中位置, 全部命中位置列表)。"""
    hits: List[int] = []
    start = 0
    while True:
        idx = content.find(needle, start)
        if idx == -1:
            break
        hits.append(idx)
        start = idx + len(needle)
    if len(hits) == 1:
        return hits[0], hits
    return None, hits


def _identity_replacement_map(content: str) -> List[int]:
    """给 content 的每个字符下标建立映射到（正则化前的行内）索引，用于从命中行还原字节范围。

    实现上：我们使用 "按行 index -> 字符偏移" 的更简单方案：
    返回一个 list，长度等于 content 的行数，每项是该行首字符在全文件中的下标。
    """
    # 记录每行首字符下标
    boundaries = [0]
    for i, ch in enumerate(content):
        if ch == "\n":
            boundaries.append(i + 1)
    return boundaries


def _fuzzy_match(content: str, needle: str) -> Optional[MatchResult]:
    """降级匹配：滑动窗口 + difflib 相似度。

    返回唯一命中的 MatchResult；无法唯一命中时返回 None（调用方据此拒绝/报错）。
    """
    lines = content.splitlines(keepends=False)
    needle_norm = _normalize(needle)
    needle_line_count = needle.count("\n") + 1

    best_scores: List[Tuple[float, int, int]] = []  # (score, start_line, end_line)

    # 以行滑动窗口，保证窗口跨行但仍保持行边界，避免把行劈开
    for start_line in range(len(lines)):
        for end_line in range(start_line, min(start_line + needle_line_count, len(lines))):
            window = "\n".join(lines[start_line : end_line + 1])
            window_norm = _normalize(window)
            score = SequenceMatcher(None, window_norm, needle_norm).ratio()
            if len(best_scores) < 5:  # 只保留 top-K 用于消歧
                best_scores.append((score, start_line, end_line))
                best_scores.sort(key=lambda x: x[0], reverse=True)
                best_scores = best_scores[:5]
            elif score > best_scores[-1][0]:
                best_scores[-1] = (score, start_line, end_line)
                best_scores.sort(key=lambda x: x[0], reverse=True)

    if not best_scores or best_scores[0][0] < MIN_SIMILARITY:
        return None

    top = best_scores[0]
    # 消歧：若第二名得分与第一名差距过小，则不确定改哪处
    if len(best_scores) >= 2 and (top[0] - best_scores[1][0]) < TOP_AMBIGUITY_EPS:
        return None

    start_line, end_line = top[1], top[2]
    # 还原到全局字符下标（基于行边界映射）
    boundaries = _identity_replacement_map(content)
    start = boundaries[start_line]
    # end_line 的"行首"，加上该行长度与可能的换行
    if end_line + 1 < len(boundaries):
        end = boundaries[end_line + 1] - (1 if content[boundaries[end_line + 1] - 1] == "\n" else 0)
    else:
        end = len(content)
    return MatchResult(start, end, matched_exact=False, similarity=top[0])


# 消歧用的常量阈值
TOP_AMBIGUITY_EPS = 0.005


def match_once(content: str, needle: str) -> MatchResult:
    """按策略尝试把 needle 在 content 中定位到唯一一处。

    Returns:
        MatchResult: 唯一命中的匹配范围。

    Raises:
        MatchError: 匹配失败或歧义（多处命中/相似候选不唯一），
            异常信息中携带候选片段供 Agent 修正 old_str 后重试。
    """
    # 1) 精确匹配
    pos, hits = _find_exact(content, needle)
    if hits:
        if len(hits) == 1:
            return MatchResult(pos, pos + len(needle), matched_exact=True)
        # 精确匹配出现多处 -> 拒绝，绝不猜测
        raise MatchError(
            f"old_str 在文件中出现 {len(hits)} 处（歧义），拒绝修改。"
            f"请为 old_str 附加更多锚定上下文使其唯一。",
            hits=hits,
            candidates=[],
        )

    # 2) 空白符标准化后重试精确匹配
    norm_needle = _normalize(needle)
    norm_content = _normalize(content)
    if norm_needle != needle:
        pos, hits = _find_exact(norm_content, norm_needle)
        if hits and len(hits) == 1:
            # 归一化命中无法精确定位到原始下标，退回到 fuzzy 完成定位更稳妥；
            # 这里直接改用 fuzzy 定位（保证位置正确）。
            result = _fuzzy_match(content, needle)
            if result is not None:
                result.matched_exact = False
                return result
    # 3) 模糊匹配（difflib 滑动窗口）
    result = _fuzzy_match(content, needle)
    if result is None:
        snippet = content[:400] + ("…" if len(content) > 400 else "")
        raise MatchError(
            f"未找到匹配片段 (similarity < {MIN_SIMILARITY})。\n"
            f"文件开头预览(前400字符):\n{snippet}\n"
            f"请基于 view 输出的真实内容重新构造 old_str。",
            hits=[],
            candidates=[],
        )
    return result


class MatchError(Exception):
    """匹配失败或歧义。可能附带给 Agent 参考的候选片段。"""

    def __init__(self, message: str, hits: Optional[List] = None, candidates: Optional[List[str]] = None):
        super().__init__(message)
        self.hits = hits or []
        self.candidates = candidates or []