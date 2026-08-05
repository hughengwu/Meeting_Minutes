"""字幕生成：把 utterances 转成 SRT / WebVTT。

lang 三种取值：
- original  仅原文（识别结果）
- zh        仅译文（没有译文的片段回退原文，保证字幕不断行）
- bilingual 双语，中文在上、原文在下（中文字幕组常见排布）
"""

import math
import re
from typing import Iterable

# 单语字幕的可读性约束：过长/过久的一条会糊满屏幕，按标点和词边界切成多条。
# 双语字幕两行本来就长，切分后两种语言容易错位，故不做切分。
_MAX_WIDTH = 42       # 显示宽度：中日韩字符算 2，ASCII 算 1（≈21 个汉字 / 42 个字母）
_MIN_WIDTH = 12       # 再挤也不切得比这更碎
_MAX_DURATION = 8.0   # 秒，超过就按比例拆成多条
_MIN_CUE = 0.4        # 秒，切分后每条最短时长

_END_PUNCT = "。！？!?；;…"
_SOFT_PUNCT = "，,、：:）)】》」"
_WIDE_RE = re.compile(r"[一-鿿㐀-䶿぀-ヿ가-힯！-～、-〿]")
# 不可再切的最小单元：CJK 单字 / 连续的非 CJK 非空白（英文单词及其粘连标点）/ 空白
_TOKEN_RE = re.compile(r"[一-鿿㐀-䶿぀-ヿ가-힯、-〿！-～]|[^\s一-鿿㐀-䶿぀-ヿ가-힯、-〿！-～]+|\s+")


def _fmt_ts(seconds: float, sep: str) -> str:
    ms = max(0, int(round(seconds * 1000)))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def _width(text: str) -> int:
    return sum(2 if _WIDE_RE.match(c) else 1 for c in text)


def _hard_slice(token: str, limit: int) -> list[str]:
    """单个 token 就超长（超长英文单词、URL）时按宽度硬切。"""
    out, buf = [], ""
    for ch in token:
        if _width(buf) + _width(ch) > limit and buf:
            out.append(buf)
            buf = ""
        buf += ch
    if buf:
        out.append(buf)
    return out


def _split_text(text: str, limit: int) -> list[str]:
    """按 token 贪心装行：英文断在词边界，中文断在字/标点边界，句末标点优先断行。"""
    if _width(text) <= limit:
        return [text]

    lines: list[str] = []
    cur = ""
    breakpoint_at = 0   # cur 中最近一个逗号/顿号之后的位置，超宽时回退到这里断行更自然

    for token in _TOKEN_RE.findall(text):
        if _width(token) > limit and not token.isspace():
            if cur.strip():
                lines.append(cur.strip())
            pieces = _hard_slice(token, limit)
            lines.extend(pieces[:-1])
            cur, breakpoint_at = pieces[-1], 0
            continue

        if cur and not token.isspace() and _width(cur) + _width(token) > limit:
            if breakpoint_at and _width(cur[:breakpoint_at]) >= limit * 0.5:
                lines.append(cur[:breakpoint_at].strip())
                cur = cur[breakpoint_at:].lstrip() + token
            else:
                lines.append(cur.strip())
                cur = token
            breakpoint_at = 0
        else:
            cur += token

        stripped = cur.rstrip()
        # 一句说完且这行已经够长，就在这里断，避免一行横跨两句
        if stripped.endswith(tuple(_END_PUNCT)) and _width(cur) >= limit * 0.6:
            lines.append(stripped)
            cur, breakpoint_at = "", 0
        elif stripped.endswith(tuple(_SOFT_PUNCT)):
            breakpoint_at = len(cur)

    if cur.strip():
        lines.append(cur.strip())
    return [l for l in lines if l] or [text]


def _plan_split(text: str, duration: float) -> list[str]:
    """同时受宽度和时长约束：时长超标时把行宽压到刚好能拆出足够多的条数。"""
    limit = _MAX_WIDTH
    if duration > _MAX_DURATION:
        needed = math.ceil(duration / _MAX_DURATION)
        limit = min(limit, max(_MIN_WIDTH, math.ceil(_width(text) / needed)))
    if _width(text) <= limit:
        return [text]
    return _split_text(text, limit)


def _cue_text(u, lang: str) -> str | None:
    text = (u.text or "").strip()
    zh = (getattr(u, "text_zh", None) or "").strip()

    if lang == "original":
        return text or None
    if lang == "zh":
        return zh or text or None
    if lang == "bilingual":
        if zh and zh != text:
            return f"{zh}\n{text}"
        return text or zh or None
    raise ValueError(f"未知字幕语言: {lang}")


def build_cues(
    utterances: Iterable,
    lang: str = "original",
    speaker_names: dict | None = None,
    show_speaker: bool = False,
    split_long: bool = True,
) -> list[dict]:
    speaker_names = speaker_names or {}
    raw: list[dict] = []

    for u in utterances:
        text = _cue_text(u, lang)
        if not text:
            continue
        start = float(u.start or 0)
        end = float(u.end or 0)
        if end <= start:
            end = start + 1.0

        pieces = [text]
        if split_long and lang != "bilingual":
            pieces = _plan_split(text, end - start)

        if len(pieces) > 1:
            total = sum(_width(p) for p in pieces) or 1
            duration = end - start
            cursor = start
            for i, p in enumerate(pieces):
                if i == len(pieces) - 1:
                    piece_end = end          # 最后一条对齐原片段结束时间
                else:
                    span = max(_MIN_CUE, duration * _width(p) / total)
                    piece_end = min(end, cursor + span)
                if piece_end <= cursor:
                    piece_end = cursor + _MIN_CUE
                raw.append({"start": cursor, "end": piece_end, "text": p,
                            "speaker": u.speaker})
                cursor = piece_end
        else:
            raw.append({"start": start, "end": end, "text": text, "speaker": u.speaker})

    # 相邻重叠会让播放器闪烁，按时间排序后夹紧
    raw.sort(key=lambda c: c["start"])
    for i in range(len(raw) - 1):
        if raw[i]["end"] > raw[i + 1]["start"]:
            raw[i]["end"] = max(raw[i]["start"] + 0.1, raw[i + 1]["start"] - 0.001)

    if show_speaker:
        for c in raw:
            if not c["speaker"]:      # 字幕模式没有说话人，跳过前缀
                continue
            name = speaker_names.get(c["speaker"], c["speaker"])
            c["text"] = f"{name}：{c['text']}"

    return raw


def to_srt(cues: list[dict]) -> str:
    blocks = []
    for i, c in enumerate(cues, 1):
        blocks.append(
            f"{i}\n{_fmt_ts(c['start'], ',')} --> {_fmt_ts(c['end'], ',')}\n{c['text']}\n"
        )
    return "\n".join(blocks)


def to_vtt(cues: list[dict]) -> str:
    blocks = ["WEBVTT\n"]
    for i, c in enumerate(cues, 1):
        blocks.append(
            f"{i}\n{_fmt_ts(c['start'], '.')} --> {_fmt_ts(c['end'], '.')}\n{c['text']}\n"
        )
    return "\n".join(blocks)
