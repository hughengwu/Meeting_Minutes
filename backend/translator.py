"""字幕翻译后端：在线 Google + 本地 LM Studio（OpenAI 兼容接口）。

设计要点：
- 只用标准库 urllib 发请求，不引入新依赖；未显式配置代理时 urllib 会自动读取
  HTTP_PROXY/HTTPS_PROXY 环境变量，配置了 proxy 就以配置为准。
- 访问 localhost 的 LM Studio 时强制绕过代理，否则系统代理会把本地请求也劫持走。
- 配置写在 data/config.json 的 "translation" 键下，与 model_manager 的 active_model
  共用同一个文件（双方都是「读出整个 dict → 改自己那部分 → 写回」，互不覆盖）。
"""

import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from database import DATA_DIR

CONFIG_FILE = DATA_DIR / "config.json"

GOOGLE_FREE_ENDPOINT = "https://translate.googleapis.com/translate_a/single"
GOOGLE_V2_ENDPOINT = "https://translation.googleapis.com/language/translate/v2"

PROVIDERS = [
    {
        "id": "google_free",
        "name": "Google 翻译（免费接口）",
        "description": "translate.googleapis.com 公开接口，无需 API Key；国内网络通常需要配置代理",
        "needs": ["proxy"],
    },
    {
        "id": "google_v2",
        "name": "Google Cloud Translation v2",
        "description": "官方接口，需要 API Key，配额稳定不易被限流",
        "needs": ["google_api_key", "proxy"],
    },
    {
        "id": "lmstudio",
        "name": "LM Studio 本地模型",
        "description": "调用本机 LM Studio 的 OpenAI 兼容接口翻译，完全离线，速度取决于本地模型",
        "needs": ["lmstudio_base_url", "lmstudio_model"],
    },
]

DEFAULT_SETTINGS: dict = {
    "provider": "google_free",
    "target_lang": "zh-CN",
    "google_api_key": "",
    "proxy": "",
    "lmstudio_base_url": "http://localhost:1234/v1",
    "lmstudio_model": "",
    "lmstudio_api_key": "lm-studio",
}

# 各 provider 的批量/并发参数：Google 免费接口按单条请求并发，官方接口支持一次多条，
# 本地模型跑在同一张 GPU 上，串行小批量最稳妥。
_GOOGLE_FREE_WORKERS = 4
_GOOGLE_V2_BATCH = 64
# 本地小模型一次处理的条数越多越容易漏翻/串位（7B~14B 尤其明显），
# 宁可多发几次请求：本地推理没有额度成本，准确率优先。
_LMSTUDIO_BATCH = 4

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

_CJK_RE = re.compile(r"[一-鿿㐀-䶿]")

# 日文汉字与中文汉字码位相同，无法靠汉字本身区分；但假名/谚文一旦出现就说明不是中文。
# 平假名、片假名、半角片假名、谚文字母与音节。
_NON_ZH_SCRIPT_RE = re.compile(
    r"[぀-ゟ゠-ヿｦ-ﾝᄀ-ᇿ㄰-㆏가-힯]"
)


class TranslationError(RuntimeError):
    """翻译服务不可用（配置缺失、网络不通、鉴权失败等）。"""


# ── 配置读写 ──────────────────────────────────────────────────────────────────

def get_settings() -> dict:
    """默认值 → 环境变量 → config.json，后者覆盖前者。"""
    s = dict(DEFAULT_SETTINGS)

    env_map = {
        "provider": "TRANSLATE_PROVIDER",
        "target_lang": "TRANSLATE_TARGET_LANG",
        "google_api_key": "GOOGLE_TRANSLATE_API_KEY",
        "proxy": "TRANSLATE_PROXY",
        "lmstudio_base_url": "LMSTUDIO_BASE_URL",
        "lmstudio_model": "LMSTUDIO_MODEL",
        "lmstudio_api_key": "LMSTUDIO_API_KEY",
    }
    for key, env in env_map.items():
        v = os.getenv(env)
        if v:
            s[key] = v

    try:
        if CONFIG_FILE.exists():
            saved = json.loads(CONFIG_FILE.read_text(encoding="utf-8")).get("translation") or {}
            for k, v in saved.items():
                if k in s and v is not None:
                    s[k] = v
    except Exception:
        pass

    if s["provider"] not in {p["id"] for p in PROVIDERS}:
        s["provider"] = DEFAULT_SETTINGS["provider"]
    return s


def save_settings(patch: dict) -> dict:
    data: dict = {}
    try:
        if CONFIG_FILE.exists():
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass

    current = data.get("translation") or {}
    for k, v in patch.items():
        if k in DEFAULT_SETTINGS and v is not None:
            current[k] = v.strip() if isinstance(v, str) else v
    data["translation"] = current
    CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return get_settings()


# ── HTTP 工具 ─────────────────────────────────────────────────────────────────

def _build_opener(proxy: str, bypass_proxy: bool = False):
    if bypass_proxy:
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    if proxy:
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        )
    return urllib.request.build_opener()  # 走系统/环境变量代理


def _request_json(opener, url: str, *, data: bytes | None = None,
                  headers: dict | None = None, timeout: int = 30):
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    req.add_header("User-Agent", _UA)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        raise TranslationError(f"HTTP {e.code} {e.reason} {detail}".strip()) from e
    except urllib.error.URLError as e:
        raise TranslationError(f"网络不可达: {e.reason}") from e
    except TimeoutError as e:
        raise TranslationError("请求超时") from e

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise TranslationError(f"返回内容不是合法 JSON: {raw[:200]}") from e


def _is_local_url(url: str) -> bool:
    host = urllib.parse.urlparse(url).hostname or ""
    return host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def _needs_no_translation(text: str, target_lang: str) -> bool:
    """目标语是中文且原文已基本是中文（或纯数字符号）时，直接沿用原文，省掉一次请求。"""
    if not target_lang.lower().startswith("zh"):
        return False
    # 含假名/谚文 → 是日文或韩文，汉字占比再高也必须翻译
    # （如「誤って川に転落した七歳。」汉字占 6/11，只数汉字会被误判成中文）
    if _NON_ZH_SCRIPT_RE.search(text):
        return False
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return True
    cjk = sum(1 for c in letters if _CJK_RE.match(c))
    return cjk / len(letters) > 0.5


# ── Google 免费接口 ───────────────────────────────────────────────────────────

def _google_free_chunks(text: str, limit: int = 1200) -> list[str]:
    """免费接口靠 URL 传参，过长会 414；按句子切块后分别翻译再拼回。"""
    if len(text) <= limit:
        return [text]
    parts, buf = [], ""
    for piece in re.split(r"(?<=[。！？.!?；;])", text):
        if len(buf) + len(piece) > limit and buf:
            parts.append(buf)
            buf = piece
        else:
            buf += piece
    if buf:
        parts.append(buf)
    # 单句就超长（没有标点）时硬切
    out = []
    for p in parts:
        while len(p) > limit:
            out.append(p[:limit])
            p = p[limit:]
        if p:
            out.append(p)
    return out


def _google_free_once(opener, text: str, target: str, timeout: int) -> str:
    params = urllib.parse.urlencode({
        "client": "gtx", "sl": "auto", "tl": target, "dt": "t", "q": text,
    })
    data = _request_json(opener, f"{GOOGLE_FREE_ENDPOINT}?{params}", timeout=timeout)
    if not isinstance(data, list) or not data or not isinstance(data[0], list):
        raise TranslationError("Google 免费接口返回结构异常")
    return "".join(seg[0] for seg in data[0] if seg and seg[0])


def _google_free_translate(text: str, target: str, opener, timeout: int = 20,
                           retries: int = 3) -> str:
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            return "".join(
                _google_free_once(opener, chunk, target, timeout)
                for chunk in _google_free_chunks(text)
            )
        except TranslationError as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    raise last_err  # type: ignore[misc]


# ── Google 官方 v2 ────────────────────────────────────────────────────────────

def _google_v2_translate(texts: list[str], target: str, key: str, opener,
                         timeout: int = 30) -> list[str]:
    body = json.dumps({"q": texts, "target": target, "format": "text"}).encode("utf-8")
    data = _request_json(
        opener, f"{GOOGLE_V2_ENDPOINT}?key={urllib.parse.quote(key)}",
        data=body, headers={"Content-Type": "application/json"}, timeout=timeout,
    )
    try:
        items = data["data"]["translations"]
    except (KeyError, TypeError) as e:
        raise TranslationError(f"Google v2 返回结构异常: {str(data)[:200]}") from e
    return [html.unescape(it.get("translatedText", "")) for it in items]


# ── LM Studio（OpenAI 兼容） ──────────────────────────────────────────────────

def _lmstudio_base(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    if not url:
        raise TranslationError("未配置 LM Studio 接口地址")
    if not url.endswith("/v1"):
        url += "/v1"
    return url


def lmstudio_list_models(settings: dict | None = None) -> list[str]:
    s = settings or get_settings()
    base = _lmstudio_base(s["lmstudio_base_url"])
    opener = _build_opener(s["proxy"], bypass_proxy=_is_local_url(base))
    data = _request_json(opener, f"{base}/models", timeout=15,
                         headers={"Authorization": f"Bearer {s['lmstudio_api_key'] or 'lm-studio'}"})
    items = data.get("data") if isinstance(data, dict) else None
    return [it.get("id", "") for it in (items or []) if it.get("id")]


# 刻意不写「原文已是目标语言就原样返回」——那是给小模型的照抄许可证，它会拿来
# 给漏翻的片段开脱。已经是目标语言的片段在 translate_texts 里就被挑掉了，
# 真正发给模型的每一条都必须产出译文。
_LMSTUDIO_SYSTEM = (
    "你是专业的字幕翻译引擎。把用户给出的每一条字幕翻译成{lang}。\n"
    "规则：\n"
    "1. 逐条翻译，输出条数与输入条数完全一致，顺序不变；\n"
    "2. 不合并、不拆分、不补充解释或注释，不输出原文；\n"
    "3. 字幕是口语片段，可能不完整，照直翻译即可，不要脑补上下文；\n"
    "4. 无论原文是什么语言，每一条的输出都必须是{lang}，禁止原样照抄原文；\n"
    "5. 人名、产品名、缩写等专有名词可保留原样，其余一律翻译；\n"
    "6. 只输出 JSON，形如 {{\"translations\": [\"译文1\", \"译文2\"]}}，不要输出任何其他内容。"
)

_LANG_NAMES = {"zh-cn": "简体中文", "zh": "简体中文", "zh-tw": "繁体中文", "en": "英文", "ja": "日文", "ko": "韩文"}

# 混合推理模型（qwen3 系列等）会把思维链塞进 content，里面的方括号会让 JSON 提取错位
_THINK_RE = re.compile(r"<(think|thinking|reasoning)>.*?</\1>", re.S | re.I)
_UNCLOSED_THINK_RE = re.compile(r"^\s*<(?:think|thinking|reasoning)>.*", re.S | re.I)
_NUM_PREFIX_RE = re.compile(r"^\s*\d+\s*[.、):：]\s*")


def _strip_reasoning(content: str) -> str:
    content = _THINK_RE.sub("", content or "")
    # 输出被截断导致 </think> 没出现时，整段都是思维链，没有可用译文
    if _UNCLOSED_THINK_RE.match(content):
        return ""
    return content.strip()


def _clean_item(x) -> str:
    s = str(x).strip()
    s = _NUM_PREFIX_RE.sub("", s)
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'“”":
        s = s[1:-1].strip()
    return s


def _extract_json_arrays(text: str):
    """扫描出所有括号配对完整的 JSON 数组（思维链里可能混着别的方括号）。"""
    depth, start = 0, -1
    in_str = escaped = False
    for i, ch in enumerate(text):
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "[":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "]" and depth:
            depth -= 1
            if depth == 0:
                yield text[start:i + 1]


def _parse_lmstudio_reply(content: str, expected: int) -> list[str] | None:
    content = _strip_reasoning(content)
    if not content:
        return None
    # 去掉可能的 ```json 包裹
    fence = re.search(r"```(?:json)?\s*(.+?)```", content, re.S)
    if fence:
        content = fence.group(1).strip()

    # 首选：{"translations": [...]}（结构化输出约定的形状）
    obj_start, obj_end = content.find("{"), content.rfind("}")
    if obj_start != -1 and obj_end > obj_start:
        try:
            obj = json.loads(content[obj_start:obj_end + 1])
            arr = obj.get("translations") if isinstance(obj, dict) else None
            if isinstance(arr, list) and len(arr) == expected:
                return [_clean_item(x) for x in arr]
        except (json.JSONDecodeError, AttributeError):
            pass

    # 次选：裸数组，取条数对得上的那一个
    for chunk in _extract_json_arrays(content):
        try:
            arr = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        if isinstance(arr, list) and len(arr) == expected:
            return [_clean_item(x) for x in arr]

    # 退化处理：按 "1. 译文" 或纯行解析
    numbered = re.findall(r"^\s*\d+\s*[.、):：]\s*(.+)$", content, re.M)
    if len(numbered) == expected:
        return [_clean_item(x) for x in numbered]
    lines = [l.strip() for l in content.splitlines() if l.strip()]
    if len(lines) == expected:
        return [_clean_item(l) for l in lines]
    return None


def _looks_untranslated(src: str, out: str | None, target: str) -> bool:
    """判断模型是不是没真翻——空、原样回抄，或目标是中文却一个汉字都没有。"""
    if not out or not out.strip():
        return True
    src, out = src.strip(), out.strip()
    # 整条就是一个 ASCII 单词（产品名、缩写）时原样返回是正确译法，不算漏翻。
    # 限定 ASCII 是为了不把「こんにちは」这类回抄也放过去。
    if out == src and " " not in src and len(src) <= 24 and src.isascii():
        return False
    if out == src:
        return True
    if target.lower().startswith("zh"):
        # 没有汉字，或残留假名/谚文（日韩原文没翻干净），都算漏翻
        if not _CJK_RE.search(out) or _NON_ZH_SCRIPT_RE.search(out):
            return True
    return False


def _lmstudio_schema(n: int) -> dict:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "subtitle_translations",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "translations": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": n,
                        "maxItems": n,
                    },
                },
                "required": ["translations"],
                "additionalProperties": False,
            },
        },
    }


def _lmstudio_once(texts: list[str], target: str, model: str, base: str,
                   opener, settings: dict, timeout: int) -> list[str] | None:
    """发一次请求并解析；解析不出对应条数时返回 None（由调用方决定怎么兜底）。"""
    lang_name = _LANG_NAMES.get(target.lower(), target)
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts))

    payload = {
        "model": model,
        "temperature": 0.2,
        "stream": False,
        # 不设上限时部分 OpenAI 兼容服务会用很小的默认值，长字幕批次会被截断
        "max_tokens": max(512, 200 * len(texts)),
        "messages": [
            {"role": "system", "content": _LMSTUDIO_SYSTEM.format(lang=lang_name)},
            {"role": "user", "content": f"共 {len(texts)} 条字幕，请翻译：\n{numbered}"},
        ],
    }
    # 可选增强：JSON Schema 强约束输出形状 + 关掉混合推理模型的思维链。
    # 老版本 LM Studio 或其它兼容服务不认这两个字段，报 4xx 时自动去掉重试。
    extras = {
        "response_format": _lmstudio_schema(len(texts)),
        "chat_template_kwargs": {"enable_thinking": False},
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.get('lmstudio_api_key') or 'lm-studio'}",
    }
    url = f"{base}/chat/completions"

    def post(extra: dict):
        return _request_json(opener, url, data=json.dumps({**payload, **extra}).encode("utf-8"),
                             headers=headers, timeout=timeout)

    try:
        data = post(extras)
    except TranslationError as e:
        if not re.search(r"HTTP 4\d\d", str(e)):
            raise
        data = post({})

    try:
        msg = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as e:
        raise TranslationError(f"LM Studio 返回结构异常: {str(data)[:200]}") from e

    return _parse_lmstudio_reply(msg.get("content") or "", len(texts))


def _lmstudio_translate(texts: list[str], target: str, settings: dict,
                        timeout: int = 300) -> list[str | None]:
    """批量翻译。没真正翻出来的位置返回 None，让调用方把它当失败留空、下次补翻。"""
    base = _lmstudio_base(settings["lmstudio_base_url"])
    model = (settings.get("lmstudio_model") or "").strip()
    if not model:
        models = lmstudio_list_models(settings)
        if not models:
            raise TranslationError("LM Studio 未加载任何模型，请先在 LM Studio 中加载模型")
        model = models[0]

    opener = _build_opener(settings["proxy"], bypass_proxy=_is_local_url(base))

    parsed = _lmstudio_once(texts, target, model, base, opener, settings, timeout)
    out: list[str | None] = list(parsed) if parsed is not None else [None] * len(texts)

    # 逐条兜底：批量里漏翻的（回抄原文/空/整条没有目标语言字符）单独重发一次。
    # 小参数量模型一次处理多条时最容易漏，单条重试的命中率明显更高。
    if len(texts) > 1:
        for i, src in enumerate(texts):
            if not _looks_untranslated(src, out[i], target):
                continue
            try:
                single = _lmstudio_once([src], target, model, base, opener, settings, timeout)
            except TranslationError:
                single = None
            out[i] = single[0] if single else None

    # 重试后仍是原样回抄的，宁可留空：留空才会在下次点「翻译」时被补翻，
    # 写回原文则会被当成"已翻译"永久固化下来。
    for i, src in enumerate(texts):
        if _looks_untranslated(src, out[i], target):
            out[i] = None
    return out


# ── 对外入口 ──────────────────────────────────────────────────────────────────

def translate_one(text: str, settings: dict | None = None) -> str:
    """翻译单条文本，失败直接抛 TranslationError（用于「测试连接」）。"""
    s = settings or get_settings()
    target = s["target_lang"]
    provider = s["provider"]

    if provider == "google_free":
        return _google_free_translate(text, target, _build_opener(s["proxy"]))
    if provider == "google_v2":
        key = (s.get("google_api_key") or "").strip()
        if not key:
            raise TranslationError("未配置 Google Cloud Translation API Key")
        return _google_v2_translate([text], target, key, _build_opener(s["proxy"]))[0]
    if provider == "lmstudio":
        zh = _lmstudio_translate([text], target, s)[0]
        if not zh:
            raise TranslationError(
                "模型没有返回有效译文（多半是把原文原样抄回来了）。"
                "请确认 LM Studio 里加载的是指令/对话模型而非补全模型，或换一个更大的模型试试"
            )
        return zh
    raise TranslationError(f"未知的翻译服务: {provider}")


def translate_texts(
    texts: list[str],
    settings: dict | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    log: Callable[[str], None] | None = None,
) -> list[str | None]:
    """批量翻译。返回与输入等长的列表，翻译失败的位置为 None（不中断其余片段）。

    已是目标语言的片段不发请求，直接原样返回。
    """
    s = settings or get_settings()
    target = s["target_lang"]
    provider = s["provider"]
    total = len(texts)
    results: list[str | None] = [None] * total

    todo: list[int] = []
    for i, t in enumerate(texts):
        if not (t or "").strip():
            results[i] = t
        elif _needs_no_translation(t, target):
            results[i] = t  # 已是中文，保留原文
        else:
            todo.append(i)

    done = total - len(todo)
    if on_progress:
        on_progress(done, total)
    if not todo:
        if log:
            log("所有片段已是目标语言，无需调用翻译服务")
        return results

    if log:
        log(f"翻译服务: {provider} → {target}，待翻译 {len(todo)}/{total} 条")

    failures = 0

    def bump(n: int = 1):
        nonlocal done
        done += n
        if on_progress:
            on_progress(done, total)

    if provider == "google_free":
        opener = _build_opener(s["proxy"])

        def work(idx: int):
            return idx, _google_free_translate(texts[idx], target, opener)

        with ThreadPoolExecutor(max_workers=_GOOGLE_FREE_WORKERS) as pool:
            for idx, fut in [(i, pool.submit(work, i)) for i in todo]:
                try:
                    _, zh = fut.result()
                    results[idx] = zh
                except Exception as e:  # noqa: BLE001 — 单条失败不影响整体
                    failures += 1
                    if failures <= 3 and log:
                        log(f"[警告] 第 {idx + 1} 条翻译失败: {e}")
                bump()

    elif provider == "google_v2":
        key = (s.get("google_api_key") or "").strip()
        if not key:
            raise TranslationError("未配置 Google Cloud Translation API Key")
        opener = _build_opener(s["proxy"])
        for b in range(0, len(todo), _GOOGLE_V2_BATCH):
            batch = todo[b:b + _GOOGLE_V2_BATCH]
            try:
                out = _google_v2_translate([texts[i] for i in batch], target, key, opener)
                for i, zh in zip(batch, out):
                    results[i] = zh
            except Exception as e:  # noqa: BLE001
                failures += len(batch)
                if log:
                    log(f"[警告] 批次翻译失败（{len(batch)} 条）: {e}")
            bump(len(batch))

    elif provider == "lmstudio":
        skipped = 0
        for b in range(0, len(todo), _LMSTUDIO_BATCH):
            batch = todo[b:b + _LMSTUDIO_BATCH]
            try:
                out = _lmstudio_translate([texts[i] for i in batch], target, s)
                miss = 0
                for i, zh in zip(batch, out):
                    if zh and zh.strip():
                        results[i] = zh
                    else:
                        miss += 1
                failures += miss
                skipped += miss
            except Exception as e:  # noqa: BLE001
                failures += len(batch)
                if log:
                    log(f"[警告] 批次翻译失败（{len(batch)} 条）: {e}")
            bump(len(batch))
        if skipped and log:
            log(f"[警告] {skipped} 条模型未翻出（重试后仍回抄原文或为空），已留空，"
                f"再点一次「翻译成中文」只会补翻这部分")

    else:
        raise TranslationError(f"未知的翻译服务: {provider}")

    if failures and log:
        log(f"翻译完成，失败 {failures} 条（可稍后重试，仅会补翻失败部分）")
    if failures == len(todo):
        raise TranslationError("所有片段翻译失败，请检查翻译服务配置或网络（可在设置中「测试连接」）")

    return results
