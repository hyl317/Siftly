from __future__ import annotations

from twelvelabs import TwelveLabs
from app.config import get_api_key

_client: TwelveLabs | None = None


def get_client() -> TwelveLabs:
    global _client
    key = get_api_key()
    if _client is None or key != getattr(_client, "_api_key_cache", ""):
        _client = TwelveLabs(api_key=key)
        _client._api_key_cache = key  # type: ignore[attr-defined]
    return _client


def reset_client():
    global _client
    _client = None


def test_connection() -> bool:
    """Returns True if the API key is valid."""
    try:
        client = get_client()
        client.indexes.list(page=1, page_limit=1)
        return True
    except Exception:
        return False
