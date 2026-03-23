import os
from pathlib import Path
from dotenv import load_dotenv, set_key

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"

load_dotenv(ENV_PATH)

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
PREP_DIR = PROJECT_ROOT / ".prep"
EMBEDDINGS_CACHE_DIR = PROJECT_ROOT / ".embeddings_cache"
MAX_FILE_SIZE_BYTES = int(1.8 * 1024 * 1024 * 1024)  # 1.8 GB
MAX_RESOLUTION_HEIGHT = 720


def get_api_key() -> str:
    return os.getenv("TWELVE_LABS_API_KEY", "")


def set_api_key(key: str):
    if not ENV_PATH.exists():
        ENV_PATH.touch()
    set_key(str(ENV_PATH), "TWELVE_LABS_API_KEY", key)
    os.environ["TWELVE_LABS_API_KEY"] = key


def get_anthropic_api_key() -> str:
    return os.getenv("ANTHROPIC_API_KEY", "")


def set_anthropic_api_key(key: str):
    if not ENV_PATH.exists():
        ENV_PATH.touch()
    set_key(str(ENV_PATH), "ANTHROPIC_API_KEY", key)
    os.environ["ANTHROPIC_API_KEY"] = key


VISION_MODELS = {
    "claude-opus-4-6": "Opus 4.6 — most accurate, ~$0.15/run",
    "claude-sonnet-4-6": "Sonnet 4.6 — balanced, ~$0.03/run",
    "claude-haiku-4-5-20251001": "Haiku 4.5 — fastest & cheapest, ~$0.01/run",
}

DEFAULT_VISION_MODEL = "claude-sonnet-4-6"


def get_vision_model() -> str:
    return os.getenv("ANTHROPIC_VISION_MODEL", DEFAULT_VISION_MODEL)


def set_vision_model(model_id: str):
    if not ENV_PATH.exists():
        ENV_PATH.touch()
    set_key(str(ENV_PATH), "ANTHROPIC_VISION_MODEL", model_id)
    os.environ["ANTHROPIC_VISION_MODEL"] = model_id


def get_index_id() -> str:
    return os.getenv("TWELVE_LABS_INDEX_ID", "")


def set_index_id(index_id: str):
    if not ENV_PATH.exists():
        ENV_PATH.touch()
    set_key(str(ENV_PATH), "TWELVE_LABS_INDEX_ID", index_id)
    os.environ["TWELVE_LABS_INDEX_ID"] = index_id
