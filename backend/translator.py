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
_LMSTUDIO_BATCH = 8

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

_CJK_RE = re.compile(r"[一-鿿㐀-䶿]")


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


_LMSTUDIO_SYSTEM = (
    "你是专业的字幕翻译。把用户给出的每一条字幕翻译成{lang}，"
    "只翻译、不解释、不合并、不拆分、不添加任何说明文字。"
    "保持每条一一对应，输出严格的 JSON 数组，元素个数必须与输入条数完全一致，"
    "形如 [\"译文1\", \"译文2\"]。原文若已经是目标语言，原样返回。"
)

_LANG_NAMES = {"zh-cn": "简体中文", "zh": "简体中文", "zh-tw": "繁体中文", "en": "英文", "ja": "日文", "ko": "韩文"}


def _parse_lmstudio_reply(content: str, expected: int) -> list[str] | None:
    content = content.strip()
    # 去掉可能的 ```json 包裹
    fence = re.search(r"```(?:json)?\s*(.+?)```", content, re.S)
    if fence:
        content = fence.group(1).strip()

    start, end = content.find("["), content.rfind("]")
    if start != -1 and end > start:
        try:
            arr = json.loads(content[start:end + 1])
            if isinstance(arr, list) and len(arr) == expected:
                return [str(x).strip() for x in arr]
        except json.JSONDecodeError:
            pass

    # 退化处理：按 "1. 译文" 或纯行解析
    numbered = re.findall(r"^\s*\d+[.、)]\s*(.+)$", content, re.M)
    if len(numbered) == expected:
        return [x.strip() for x in numbered]
    lines = [l.strip() for l in content.splitlines() if l.strip()]
    if len(lines) == expected:
        return lines
    return None


def _lmstudio_translate(texts: list[str], target: str, settings: dict,
                        timeout: int = 300) -> list[str]:
    base = _lmstudio_base(settings["lmstudio_base_url"])
    model = (settings.get("lmstudio_model") or "").strip()
    if not model:
        models = lmstudio_list_models(settings)
        if not models:
            raise TranslationError("LM Studio 未加载任何模型，请先在 LM Studio 中加载模型")
        model = models[0]

    opener = _build_opener(settings["proxy"], bypass_proxy=_is_local_url(base))
    lang_name = _LANG_NAMES.get(target.lower(), target)
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts))

    body = json.dumps({
        "model": model,
        "temperature": 0.2,
        "stream": False,
        "messages": [
            {"role": "system", "content": _LMSTUDIO_SYSTEM.format(lang=lang_name)},
            {"role": "user", "content": f"共 {len(texts)} 条字幕，请翻译：\n{numbered}"},
        ],
    }).encode("utf-8")

    data = _request_json(
        opener, f"{base}/chat/completions", data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.get('lmstudio_api_key') or 'lm-studio'}",
        },
        timeout=timeout,
    )
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise TranslationError(f"LM Studio 返回结构异常: {str(data)[:200]}") from e

    parsed = _parse_lmstudio_reply(content, len(texts))
    if parsed is not None:
        return parsed

    # 条数对不上就退回逐条翻译，宁可慢也不能错位
    if len(texts) == 1:
        return [content.strip()]
    return [_lmstudio_translate([t], target, settings, timeout)[0] for t in texts]


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
        return _lmstudio_translate([text], target, s)[0]
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
        for b in range(0, len(todo), _LMSTUDIO_BATCH):
            batch = todo[b:b + _LMSTUDIO_BATCH]
            try:
                out = _lmstudio_translate([texts[i] for i in batch], target, s)
                for i, zh in zip(batch, out):
                    results[i] = zh
            except Exception as e:  # noqa: BLE001
                failures += len(batch)
                if log:
                    log(f"[警告] 批次翻译失败（{len(batch)} 条）: {e}")
            bump(len(batch))

    else:
        raise TranslationError(f"未知的翻译服务: {provider}")

    if failures and log:
        log(f"翻译完成，失败 {failures} 条（可稍后重试，仅会补翻失败部分）")
    if failures == len(todo):
        raise TranslationError("所有片段翻译失败，请检查翻译服务配置或网络（可在设置中「测试连接」）")

    return results
