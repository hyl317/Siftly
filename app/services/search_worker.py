import math

from PySide6.QtCore import QThread, Signal

from app.services.api_client import get_client
from app.config import get_index_id


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _score_to_level(score: float) -> str:
    if score >= 70:
        return "high"
    elif score >= 40:
        return "medium"
    else:
        return "low"


def _merge_adjacent_clips(clips: list[dict], gap_tolerance: float = 1.0) -> list[dict]:
    """Merge adjacent clips from the same video with the same confidence level.

    Clips are considered adjacent if the gap between the end of one and
    the start of the next is within gap_tolerance seconds.
    Only clips with the same derived confidence level (high/medium/low)
    are merged. Best (highest) score is kept for the merged clip.
    """
    if not clips:
        return clips

    sorted_clips = sorted(clips, key=lambda c: (c["video_id"], c["start"]))

    first = sorted_clips[0].copy()
    first["_total_weighted"] = first["score"] * (first["end"] - first["start"])
    first["_total_duration"] = first["end"] - first["start"]
    merged = [first]
    for clip in sorted_clips[1:]:
        prev = merged[-1]
        clip_dur = clip["end"] - clip["start"]
        if (clip["video_id"] == prev["video_id"]
                and _score_to_level(clip["score"]) == _score_to_level(prev["score"])
                and clip["start"] <= prev["end"] + gap_tolerance):
            prev["end"] = max(prev["end"], clip["end"])
            prev["_total_weighted"] += clip["score"] * clip_dur
            prev["_total_duration"] += clip_dur
        else:
            new_clip = clip.copy()
            new_clip["_total_weighted"] = clip["score"] * clip_dur
            new_clip["_total_duration"] = clip_dur
            merged.append(new_clip)

    # Compute weighted average scores and clean up temp fields
    for clip in merged:
        if clip["_total_duration"] > 0:
            clip["score"] = round(clip["_total_weighted"] / clip["_total_duration"], 1)
        del clip["_total_weighted"]
        del clip["_total_duration"]

    # Re-sort by score descending
    merged.sort(key=lambda c: c["score"], reverse=True)
    return merged


class SearchWorker(QThread):
    results = Signal(list)
    error = Signal(str)

    def __init__(self, query: str, parent=None):
        super().__init__(parent)
        self.query = query

    def run(self):
        try:
            client = get_client()
            index_id = get_index_id()

            # 1. Get search results
            search_results = client.search.query(
                index_id=index_id,
                query_text=self.query,
                search_options=["visual", "audio"],
                group_by="clip",
            )
            raw_clips = []
            for clip in search_results:
                raw_clips.append({
                    "video_id": clip.video_id or "",
                    "start": clip.start if clip.start is not None else 0.0,
                    "end": clip.end if clip.end is not None else 0.0,
                    "score": 0.0,
                })

            if not raw_clips:
                self.results.emit([])
                return

            # 2. Embed the query text
            text_emb_resp = client.embed.create(
                model_name="marengo3.0",
                text=self.query,
            )
            query_vec = text_emb_resp.text_embedding.segments[0].float_

            # 3. Retrieve video embeddings (cached + parallel)
            unique_video_ids = list({c["video_id"] for c in raw_clips})

            from app.services.embedding_cache import fetch_many
            video_segments = fetch_many(client, index_id, unique_video_ids)

            # 4. Compute raw cosine similarity for each search result clip
            for clip in raw_clips:
                vid = clip["video_id"]
                segments = video_segments.get(vid, [])
                best_sim = 0.0
                clip_start = clip["start"]
                clip_end = clip["end"]
                for seg_start, seg_end, seg_vec in segments:
                    if seg_start < clip_end and seg_end > clip_start:
                        sim = _cosine_similarity(query_vec, seg_vec)
                        best_sim = max(best_sim, sim)
                clip["score"] = best_sim  # raw cosine similarity

            # 5. Normalize scores relative to the top score
            max_score = max((c["score"] for c in raw_clips), default=0.0)
            if max_score > 0:
                for clip in raw_clips:
                    clip["score"] = round((clip["score"] / max_score) * 100, 1)
            else:
                for clip in raw_clips:
                    clip["score"] = 0.0

            merged = _merge_adjacent_clips(raw_clips)
            self.results.emit(merged)

        except Exception as e:
            self.error.emit(str(e))
