import json
import logging
import time

from PySide6.QtCore import QThread, Signal
from twelvelabs.errors import TooManyRequestsError
from twelvelabs.types import ResponseFormat

from app.services.api_client import get_client
from app.services.search_worker import _cosine_similarity, _merge_adjacent_clips
from app.config import get_index_id

logger = logging.getLogger(__name__)


ANALYZE_PROMPT = (
    "Analyze this video and identify the most interesting, visually striking, "
    "or emotionally engaging highlights. For each highlight, provide the start "
    "and end timestamps in seconds, a short descriptive title, a category label, "
    "and a confidence score from 0 to 100. Return between 3 and 10 highlights, "
    "ordered by quality."
)

ANALYZE_SCHEMA = {
    "type": "object",
    "required": ["highlights"],
    "properties": {
        "highlights": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["title", "category", "start", "end", "score"],
                "properties": {
                    "title": {"type": "string"},
                    "category": {
                        "type": "string",
                        "enum": [
                            "scenery", "food", "action", "people", "wildlife",
                            "funny", "emotional", "music", "travel", "other",
                        ],
                    },
                    "start": {"type": "number"},
                    "end": {"type": "number"},
                    "score": {"type": "number"},
                },
            },
        },
    },
}

CATEGORY_QUERIES = {
    "scenery": "Beautiful scenery, landscapes, nature views, sunsets",
    "food": "Food, cooking, dining, restaurants, street food",
    "action": "Action, sports, adventure, exciting moments",
    "people": "People, conversations, social gatherings, portraits",
    "wildlife": "Animals, wildlife, pets, nature",
    "funny": "Funny moments, humor, laughter, comedy",
    "emotional": "Emotional moments, heartfelt, moving, touching",
    "music": "Music, singing, dancing, performances",
    "travel": "Travel, landmarks, cities, exploration",
}


class HighlightsAnalyzeWorker(QThread):
    """Iterates video IDs and calls analyze with structured JSON schema."""
    video_progress = Signal(int, int)  # current, total
    video_result = Signal(str, list)   # video_id, list of highlight dicts
    all_done = Signal(list)            # all highlights combined
    error = Signal(str)
    retrying = Signal(int)             # seconds remaining until retry

    def __init__(self, video_ids: list[str], parent=None):
        super().__init__(parent)
        self.video_ids = video_ids
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def _analyze_video(self, client, vid: str) -> list[dict]:
        """Call analyze API for a single video and return highlight dicts."""
        res = client.analyze(
            video_id=vid,
            prompt=ANALYZE_PROMPT,
            response_format=ResponseFormat(
                type="json_schema",
                json_schema=ANALYZE_SCHEMA,
            ),
        )
        data = json.loads(res.data)
        results = []
        for h in data.get("highlights", []):
            results.append({
                "video_id": vid,
                "title": h.get("title", ""),
                "category": h.get("category", "other"),
                "start": float(h.get("start", 0)),
                "end": float(h.get("end", 0)),
                "score": float(h.get("score", 0)),
                "source": "auto",
            })
        return results

    def run(self):
        client = get_client()
        all_highlights = []
        total = len(self.video_ids)

        for i, vid in enumerate(self.video_ids):
            if self._cancelled:
                break

            self.video_progress.emit(i + 1, total)

            try:
                results = self._analyze_video(client, vid)
                all_highlights.extend(results)
                self.video_result.emit(vid, results)

            except TooManyRequestsError:
                # Rate limited — wait 5 minutes, checking cancel every second
                for remaining in range(300, 0, -1):
                    if self._cancelled:
                        break
                    self.retrying.emit(remaining)
                    time.sleep(1)
                if self._cancelled:
                    break
                try:
                    results = self._analyze_video(client, vid)
                    all_highlights.extend(results)
                    self.video_result.emit(vid, results)
                except Exception as retry_e:
                    logger.warning("Video %s failed on retry: %s", vid, retry_e)
            except Exception as e:
                logger.warning("Skipping video %s: %s", vid, e)

        if not self._cancelled:
            all_highlights.sort(key=lambda h: h["score"], reverse=True)
            self.all_done.emit(all_highlights)


class HighlightsSearchWorker(QThread):
    """Search-based highlights using cosine similarity scoring."""
    results = Signal(list, dict)   # highlights, timing_info
    error = Signal(str)

    def __init__(self, query: str, category: str = "",
                 video_ids: list[str] | None = None, parent=None):
        super().__init__(parent)
        self.query = query
        self.category = category
        self.video_ids = video_ids

    def run(self):
        try:
            client = get_client()
            index_id = get_index_id()
            timing = {}

            # 1. Get search results
            t0 = time.monotonic()
            search_results = client.search.query(
                index_id=index_id,
                query_text=self.query,
                search_options=["visual", "audio"],
                group_by="clip",
            )
            raw_clips = []
            for clip in search_results:
                vid = clip.video_id or ""
                # Filter to scoped videos if specified
                if self.video_ids and vid not in self.video_ids:
                    continue
                raw_clips.append({
                    "video_id": vid,
                    "start": clip.start if clip.start is not None else 0.0,
                    "end": clip.end if clip.end is not None else 0.0,
                    "score": 0.0,
                })
            timing["search"] = time.monotonic() - t0

            if not raw_clips:
                timing["embedding"] = 0.0
                timing["scoring"] = 0.0
                self.results.emit([], timing)
                return

            # 2. Embed query text + retrieve video embeddings (cached + parallel)
            t1 = time.monotonic()
            text_emb_resp = client.embed.create(
                model_name="marengo3.0",
                text=self.query,
            )
            query_vec = text_emb_resp.text_embedding.segments[0].float_

            unique_video_ids = list({c["video_id"] for c in raw_clips})

            from app.services.embedding_cache import fetch_many
            video_segments = fetch_many(client, index_id, unique_video_ids)
            timing["embedding"] = time.monotonic() - t1

            # 3. Compute cosine similarity
            t2 = time.monotonic()
            for clip in raw_clips:
                vid = clip["video_id"]
                segments = video_segments.get(vid, [])
                best_sim = 0.0
                for seg_start, seg_end, seg_vec in segments:
                    if seg_start < clip["end"] and seg_end > clip["start"]:
                        sim = _cosine_similarity(query_vec, seg_vec)
                        best_sim = max(best_sim, sim)
                clip["score"] = best_sim

            # 4. Normalize to 0-100 before merge (so _score_to_level works)
            max_score = max((c["score"] for c in raw_clips), default=0.0)
            if max_score > 0:
                for clip in raw_clips:
                    clip["score"] = round((clip["score"] / max_score) * 100, 1)

            # 5. Merge adjacent clips, then re-normalize
            merged = _merge_adjacent_clips(raw_clips)
            max_merged = max((c["score"] for c in merged), default=0.0)
            if max_merged > 0:
                for clip in merged:
                    clip["score"] = round((clip["score"] / max_merged) * 100, 1)
            timing["scoring"] = time.monotonic() - t2

            # Add source and category info
            source = "category" if self.category else "search"
            for clip in merged:
                clip["source"] = source
                clip["category"] = self.category or ""
                clip["title"] = ""  # Search results don't have titles

            self.results.emit(merged, timing)

        except Exception as e:
            self.error.emit(str(e))
