from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from app.services.api_client import get_client
from app.config import get_index_id
from app.utils.video_prep import VideoPrepCancelled, prepare_video, resolve_lut_path

MAX_PARALLEL_TRANSCODES = 2
MAX_PARALLEL_UPLOADS = 3


class PrepWorker(QThread):
    """Preprocesses videos (transcode/split) before upload."""
    prep_progress = Signal(str, str, int)  # original_path, status, percent
    prep_done = Signal(str, list)  # original_path, list of prepared paths
    error = Signal(str, str)  # original_path, error message

    def __init__(self, video_paths: list[str],
                 color_profiles: list[str] | None = None, parent=None):
        super().__init__(parent)
        self.video_paths = video_paths
        self._profile_map = dict(zip(video_paths,
                                     color_profiles or [""] * len(video_paths)))
        self._cancelled = False
        self._cancel_events: dict[str, threading.Event] = {}

    def cancel(self):
        self._cancelled = True
        for ev in self._cancel_events.values():
            ev.set()

    def cancel_file(self, path: str):
        """Cancel preprocessing for a specific file."""
        ev = self._cancel_events.get(path)
        if ev:
            ev.set()

    def _prep_one(self, path_str: str):
        path = Path(path_str)
        cancel_event = self._cancel_events[path_str]
        self.prep_progress.emit(path_str, "Preprocessing...", 0)

        lut_path = resolve_lut_path(self._profile_map.get(path_str, ""), path)

        def cb(status):
            self.prep_progress.emit(path_str, status, 50)

        prepared = prepare_video(path, lut_path=lut_path,
                                 cancel_event=cancel_event, progress_callback=cb)
        return path_str, [str(p) for p in prepared]

    def run(self):
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_TRANSCODES) as pool:
            futures = {}
            for path_str in self.video_paths:
                if self._cancelled:
                    break
                self._cancel_events[path_str] = threading.Event()
                futures[pool.submit(self._prep_one, path_str)] = path_str

            for future in as_completed(futures):
                if self._cancelled:
                    break
                path_str = futures[future]
                try:
                    _, prepared = future.result()
                    self.prep_progress.emit(path_str, "Waiting to upload...", 100)
                    self.prep_done.emit(path_str, prepared)
                except VideoPrepCancelled:
                    pass  # UploadPanel already marked the card
                except Exception as e:
                    self.error.emit(path_str, str(e))


class UploadWorker(QThread):
    """Uploads videos in parallel with retry on rate limits."""
    progress = Signal(str, str, int)  # path, status, percent
    finished = Signal(str, str)  # path, video_id
    error = Signal(str, str)  # path, error message
    all_done = Signal()

    def __init__(self, file_paths: list[str], parent=None):
        super().__init__(parent)
        self.file_paths = file_paths
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def _upload_one(self, path_str: str, client, index_id: str):
        self.progress.emit(path_str, "Uploading...", 10)

        retries = 0
        max_retries = 3
        while retries <= max_retries:
            if self._cancelled:
                return
            try:
                filename = Path(path_str).name
                with open(path_str, "rb") as f:
                    task = client.tasks.create(
                        index_id=index_id,
                        video_file=(filename, f, "video/mp4"),
                    )
                self.progress.emit(path_str, "Indexing...", 50)

                def on_status(t, _p=path_str):
                    if t.status == "indexing":
                        self.progress.emit(_p, "Indexing...", 70)

                result = client.tasks.wait_for_done(
                    task.id,
                    sleep_interval=5,
                    callback=on_status,
                )
                # Cache embeddings immediately after indexing
                if result.video_id:
                    self.progress.emit(path_str, "Caching embeddings...", 90)
                    try:
                        from app.services.embedding_cache import fetch_and_cache
                        fetch_and_cache(client, index_id, result.video_id)
                    except Exception:
                        pass  # Non-critical — will be fetched on first search

                self.progress.emit(path_str, "Ready", 100)
                self.finished.emit(path_str, result.video_id or "")
                return
            except Exception as e:
                err_str = str(e)
                if "429" in err_str and retries < max_retries:
                    retries += 1
                    wait = 300  # 5 minutes
                    self.progress.emit(path_str, f"Rate limited, retrying in {wait // 60}min...", -1)
                    time.sleep(wait)
                else:
                    self.error.emit(path_str, err_str)
                    return

    def run(self):
        client = get_client()
        index_id = get_index_id()

        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_UPLOADS) as pool:
            futures = {}
            for path_str in self.file_paths:
                if self._cancelled:
                    break
                futures[pool.submit(self._upload_one, path_str, client, index_id)] = path_str

            for future in as_completed(futures):
                if self._cancelled:
                    break
                try:
                    future.result()
                except Exception as e:
                    self.error.emit(futures[future], str(e))

        self.all_done.emit()
