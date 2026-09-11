"""
文本匹配模块：str_replace 的"找到要替换的片段"这一核心环节。

匹配策略（按优先级降级）：
1. 精确匹配：old_str 在完整文件内容中恰好出现 1 次 → 直接命中。
   - 出现 0 次：进入降级策略。
   - 出现 >=2 次：ambiguity，拒绝修改（绝不猜测改哪一处）。
2. 降级策略（精确匹配失败时启用）：
   a. 空白符标准化：对 old_str 与文件内容做折叠空白规范化，再尝试精确匹配。
   b. difflib 滑动窗口相似度匹配：遍历文本，基于 SequenceMatcher 计算候选窗口
      与 old_str 的相似度，取最高且唯一候选。

任何匹配到"恰好一处"的结果，才能返回实际替换位置；多于一处的直接拒绝。
"""
from __future__ import annotations

from difflib import SequenceMatcher
from typing import List, Optional, Tuple

MIN_SIMILARITY = 0.70


class MatchResult:
    __slots__ = ("start", "end", "matched_exact", "similarity")

    def __init__(self, start: int, end: int, matched_exact: bool, similarity: float = 1.0):
        self.start = start
        self.end = end
        self.matched_exact = matched_exact
        self.similarity = similarity


def _normalize(text: str) -> str:
    return " ".join(text.split())


def _find_exact(content: str, needle: str) -> Tuple[Optional[int], List[int]]:
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
    boundaries = [0]
    for i, ch in enumerate(content):
        if ch == "\n":
            boundaries.append(i + 1)
    return boundaries


TOP_AMBIGUITY_EPS = 0.005


def _fuzzy_match(content: str, needle: str) -> Optional[MatchResult]:
    lines = content.splitlines(keepends=False)
    needle_norm = _normalize(needle)
    needle_line_count = needle.count("\n") + 1

    best_scores: List[Tuple[float, int, int]] = []

    for start_line in range(len(lines)):
        for end_line in range(start_line, min(start_line + needle_line_count, len(lines))):
            window = "\n".join(lines[start_line : end_line + 1])
            window_norm = _normalize(window)
            score = SequenceMatcher(None, window_norm, needle_norm).ratio()
            if len(best_scores) < 5:
                best_scores.append((score, start_line, end_line))
                best_scores.sort(key=lambda x: x[0], reverse=True)
                best_scores = best_scores[:5]
            elif score > best_scores[-1][0]:
                best_scores[-1] = (score, start_line, end_line)
                best_scores.sort(key=lambda x: x[0], reverse=True)

    if not best_scores or best_scores[0][0] < MIN_SIMILARITY:
        return None

    top = best_scores[0]
    if len(best_scores) >= 2 and (top[0] - best_scores[1][0]) < TOP_AMBIGUITY_EPS:
        return None

    start_line, end_line = top[1], top[2]
    boundaries = _identity_replacement_map(content)
    start = boundaries[start_line]
    if end_line + 1 < len(boundaries):
        end = boundaries[end_line + 1] - (1 if content[boundaries[end_line + 1] - 1] == "\n" else 0)
    else:
        end = len(content)
    return MatchResult(start, end, matched_exact=False, similarity=top[0])


def match_once(content: str, needle: str) -> MatchResult:
    pos, hits = _find_exact(content, needle)
    if hits:
        if len(hits) == 1:
            return MatchResult(pos, pos + len(needle), matched_exact=True)
        raise MatchError(
            f"old_str 在文件中出现 {len(hits)} 处（歧义），拒绝修改。"
            f"请为 old_str 附加更多锚定上下文使其唯一。",
            hits=hits,
            candidates=[],
        )

    norm_needle = _normalize(needle)
    norm_content = _normalize(content)
    if norm_needle != needle:
        pos2, hits2 = _find_exact(norm_content, norm_needle)
        if hits2 and len(hits2) == 1:
            result = _fuzzy_match(content, needle)
            if result is not None:
                result.matched_exact = False
                return result

    result = _fuzzy_match(content, needle)
    if result is None:
        snippet = content[:400] + ("\u2026" if len(content) > 400 else "")
        raise MatchError(
            f"未找到匹配片段 (similarity < {MIN_SIMILARITY})。\n"
            f"文件开头预览(前400字符):\n{snippet}\n"
            f"请基于 read_file 输出的真实内容重新构造 old_str。",
            hits=[],
            candidates=[],
        )
    return result


class MatchError(Exception):
    def __init__(self, message: str, hits: Optional[List] = None, candidates: Optional[List[str]] = None):
        super().__init__(message)
        self.hits = hits or []
        self.candidates = candidates or []
