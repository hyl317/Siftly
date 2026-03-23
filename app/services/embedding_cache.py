"""Local cache for video embedding segments.

Embeddings are immutable after indexing, so we cache them on first fetch.
Each video's segments are stored as a JSON file under
.embeddings_cache/{index_id}/{video_id}.json.
"""
from __future__ import annotations

import json
import logging
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from app.config import EMBEDDINGS_CACHE_DIR

logger = logging.getLogger(__name__)


def _cache_dir(index_id: str) -> Path:
    return EMBEDDINGS_CACHE_DIR / index_id


def _cache_path(index_id: str, video_id: str) -> Path:
    return _cache_dir(index_id) / f"{video_id}.json"


def get_cached_segments(index_id: str, video_id: str) -> list[tuple] | None:
    """Read cached segments for a video.

    Returns [(start, end, float_vec), ...] or None if not cached.
    """
    path = _cache_path(index_id, video_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
        return [(s["start"], s["end"], s["vec"]) for s in data]
    except (json.JSONDecodeError, KeyError, OSError) as e:
        logger.warning("Corrupt cache for %s/%s, removing: %s", index_id, video_id, e)
        path.unlink(missing_ok=True)
        return None


def save_segments(index_id: str, video_id: str, segments: list[tuple]):
    """Write segments to cache. segments: [(start, end, float_vec), ...]"""
    cache_dir = _cache_dir(index_id)
    cache_dir.mkdir(parents=True, exist_ok=True)
    data = [{"start": s, "end": e, "vec": v} for s, e, v in segments]
    _cache_path(index_id, video_id).write_text(json.dumps(data))


def _fetch_segments_from_api(client, index_id: str, video_id: str) -> list[tuple]:
    """Retrieve embedding segments from the Twelve Labs API."""
    detail = client.indexes.videos.retrieve(
        index_id=index_id,
        video_id=video_id,
        embedding_option=["visual"],
    )
    if detail.embedding and detail.embedding.video_embedding:
        return [
            (seg.start_offset_sec, seg.end_offset_sec, seg.float_)
            for seg in detail.embedding.video_embedding.segments
            if seg.float_
        ]
    return []


def fetch_and_cache(client, index_id: str, video_id: str) -> list[tuple]:
    """Fetch segments from API and write to cache. Returns the segments."""
    segments = _fetch_segments_from_api(client, index_id, video_id)
    if segments:
        save_segments(index_id, video_id, segments)
    return segments


def fetch_many(
    client,
    index_id: str,
    video_ids: list[str],
    max_workers: int = 8,
) -> dict[str, list[tuple]]:
    """Fetch segments for multiple videos, using cache where available.

    Cache hits are returned immediately. Cache misses are fetched in parallel
    from the API and written to cache.

    Returns {video_id: [(start, end, float_vec), ...]}.
    """
    result: dict[str, list[tuple]] = {}
    to_fetch: list[str] = []

    # Check cache first
    for vid in video_ids:
        cached = get_cached_segments(index_id, vid)
        if cached is not None:
            result[vid] = cached
        else:
            to_fetch.append(vid)

    if not to_fetch:
        return result

    cache_hits = len(video_ids) - len(to_fetch)
    logger.info(
        "Embedding cache: %d hits, %d misses — fetching in parallel",
        cache_hits, len(to_fetch),
    )

    # Parallel fetch for misses
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(fetch_and_cache, client, index_id, vid): vid
            for vid in to_fetch
        }
        for future in as_completed(futures):
            vid = futures[future]
            try:
                segments = future.result()
                result[vid] = segments
            except Exception as e:
                logger.warning("Failed to fetch embeddings for %s: %s", vid, e)
                result[vid] = []

    return result


def build_full_cache(
    client,
    index_id: str,
    video_ids: list[str],
    progress_callback: Callable[[int, int], None] | None = None,
    max_workers: int = 8,
):
    """Fetch and cache embeddings for all videos in an index.

    Args:
        progress_callback: Called with (current, total) after each video.
    """
    total = len(video_ids)
    done = 0

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(fetch_and_cache, client, index_id, vid): vid
            for vid in video_ids
        }
        for future in as_completed(futures):
            done += 1
            if progress_callback:
                progress_callback(done, total)
            vid = futures[future]
            try:
                future.result()
            except Exception as e:
                logger.warning("Failed to cache embeddings for %s: %s", vid, e)


def clear_cache(index_id: str):
    """Delete all cached embeddings for an index."""
    cache_dir = _cache_dir(index_id)
    if cache_dir.exists():
        shutil.rmtree(cache_dir, ignore_errors=True)


def get_cache_size(index_id: str) -> int:
    """Return total bytes of cached data for an index."""
    cache_dir = _cache_dir(index_id)
    if not cache_dir.exists():
        return 0
    return sum(f.stat().st_size for f in cache_dir.glob("*.json"))
