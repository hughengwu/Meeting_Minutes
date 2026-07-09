from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from model_manager import (
    MODELS,
    get_active_model,
    get_download_status,
    is_model_downloaded,
    set_active_model,
)

router = APIRouter()


class SetActiveBody(BaseModel):
    model_id: str


@router.get("/")
def list_models():
    active = get_active_model()
    return [
        {
            "id": mid,
            "name": m["name"],
            "tag": m["tag"],
            "description": m["description"],
            "vram_gb": m["vram_gb"],
            "downloaded": is_model_downloaded(mid),
            "active": mid == active,
            "download_status": get_download_status(mid),
        }
        for mid, m in MODELS.items()
    ]


@router.get("/{model_id}/status")
def get_model_status(model_id: str):
    if model_id not in MODELS:
        raise HTTPException(status_code=404, detail="模型不存在")
    return {
        "downloaded": is_model_downloaded(model_id),
        "active": model_id == get_active_model(),
        "download_status": get_download_status(model_id),
    }


@router.post("/{model_id}/download")
def start_download(model_id: str):
    if model_id not in MODELS:
        raise HTTPException(status_code=404, detail="模型不存在")
    if is_model_downloaded(model_id):
        return {"ok": True, "message": "already_downloaded"}
    ds = get_download_status(model_id)
    if ds.get("status") == "downloading":
        return {"ok": True, "message": "already_downloading"}
    from worker import download_model_task
    download_model_task.delay(model_id)
    return {"ok": True}


@router.post("/active")
def set_active(body: SetActiveBody):
    if body.model_id not in MODELS:
        raise HTTPException(status_code=400, detail="模型不存在")
    if not is_model_downloaded(body.model_id):
        raise HTTPException(status_code=400, detail="模型尚未下载，请先下载")
    set_active_model(body.model_id)
    return {"ok": True, "active_model": body.model_id}
