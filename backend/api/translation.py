from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from translator import (
    PROVIDERS,
    TranslationError,
    get_settings,
    lmstudio_list_models,
    save_settings,
    translate_one,
)

router = APIRouter()


class SettingsBody(BaseModel):
    provider: str | None = None
    target_lang: str | None = None
    google_api_key: str | None = None
    proxy: str | None = None
    lmstudio_base_url: str | None = None
    lmstudio_model: str | None = None
    lmstudio_api_key: str | None = None


class TestBody(BaseModel):
    text: str = "Good morning everyone, let's start today's meeting."


@router.get("/settings")
def read_settings():
    return {"settings": get_settings(), "providers": PROVIDERS}


@router.post("/settings")
def write_settings(body: SettingsBody):
    patch = body.model_dump(exclude_none=True)
    if "provider" in patch and patch["provider"] not in {p["id"] for p in PROVIDERS}:
        raise HTTPException(status_code=400, detail="未知的翻译服务")
    return {"settings": save_settings(patch)}


@router.post("/test")
def test_translation(body: TestBody):
    """用当前配置翻一句样例文本，把失败原因原样返回给前端，方便排查代理/Key 问题。"""
    s = get_settings()
    try:
        return {"ok": True, "provider": s["provider"],
                "source": body.text, "translated": translate_one(body.text, s)}
    except TranslationError as e:
        return {"ok": False, "provider": s["provider"], "error": str(e)}
    except Exception as e:  # noqa: BLE001 — 兜底，避免 500 让前端只看到"未知错误"
        return {"ok": False, "provider": s["provider"], "error": f"{type(e).__name__}: {e}"}


@router.get("/lmstudio/models")
def list_lmstudio_models():
    try:
        return {"ok": True, "models": lmstudio_list_models()}
    except TranslationError as e:
        return {"ok": False, "models": [], "error": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "models": [], "error": f"{type(e).__name__}: {e}"}
