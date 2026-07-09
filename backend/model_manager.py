import json
from pathlib import Path

from database import DATA_DIR

CONFIG_FILE = DATA_DIR / "config.json"
_STATUS_DIR = DATA_DIR / "download_status"
_STATUS_DIR.mkdir(parents=True, exist_ok=True)

MODELS: dict[str, dict] = {
    "firered-aed": {
        "id": "firered-aed",
        "name": "FireRedASR-AED",
        "tag": "推荐",
        "description": "小红书 FireRed 团队，中文 CER 3.18%，精度高于 Paraformer",
        "vram_gb": 8,
        "hf_repo": "FireRedTeam/FireRedASR-AED-L",
        "local_dir": DATA_DIR / "models" / "firered-aed",
        "check_file": "model.pth.tar",
    },
    "paraformer": {
        "id": "paraformer",
        "name": "Paraformer-zh",
        "tag": "备选",
        "description": "阿里达摩院 FunASR，CER 较高，显存约 4GB",
        "vram_gb": 4,
        "modelscope_ids": [
            "damo/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
            "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
            "iic/punc_ct-transformer_cn-en-common-vocab471067-large",
            "iic/speech_campplus_sv_zh-cn_16k-common",
        ],
        "local_dir": DATA_DIR / "models" / "hub",
        "check_file": "models/damo/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch/model.pt",
    },
    "sensevoice-multilingual": {
        "id": "sensevoice-multilingual",
        "name": "SenseVoice 多语言",
        "tag": "多语言",
        "description": "阿里 FunASR SenseVoice Small，支持中/英/日/韩/粤，非中文自动翻译，约 550MB",
        "vram_gb": 4,
        "local_dir": DATA_DIR / "models" / "hub",
        "check_file": "models/iic/SenseVoiceSmall/model.pt",
        "translation_dir": DATA_DIR / "models" / "opus-mt-en-zh",
    },
}


def get_active_model() -> str:
    try:
        if CONFIG_FILE.exists():
            return json.loads(CONFIG_FILE.read_text()).get("active_model", "firered-aed")
    except Exception:
        pass
    return "firered-aed"


def set_active_model(model_id: str) -> None:
    data: dict = {}
    try:
        if CONFIG_FILE.exists():
            data = json.loads(CONFIG_FILE.read_text())
    except Exception:
        pass
    data["active_model"] = model_id
    CONFIG_FILE.write_text(json.dumps(data))


def is_model_downloaded(model_id: str) -> bool:
    m = MODELS.get(model_id)
    if not m:
        return False
    base = (Path(m["local_dir"]) / m["check_file"]).exists()
    if model_id == "sensevoice-multilingual":
        td = Path(m["translation_dir"])
        return base and td.exists() and (td / "config.json").exists()
    return base


def get_download_status(model_id: str) -> dict:
    try:
        f = _STATUS_DIR / f"{model_id}.json"
        if f.exists():
            return json.loads(f.read_text())
    except Exception:
        pass
    return {}


def set_download_status(model_id: str, status: dict) -> None:
    (_STATUS_DIR / f"{model_id}.json").write_text(json.dumps(status))
