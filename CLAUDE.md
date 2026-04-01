# Siftly

AI-powered video highlight discovery + DaVinci Resolve integration, built on the Twelve Labs video understanding platform.

## Stack
- GUI: PySide6 (Qt6)
- AI: Twelve Labs API (search/embeddings), Anthropic API (assistant/vision), Voyage AI (manual RAG)
- Video: ffmpeg/ffprobe, OpenTimelineIO
- NLE: DaVinci Resolve Studio scripting API (free version lacks scripting)
- Python: 3.11, conda env `twelvelabs`

## Run
```
conda activate twelvelabs
python run.py
```

## Python Version
Use `from __future__ import annotations` in every file. Do NOT use `X | None` type syntax without it — the project must run on Python 3.9+. This has caused bugs twice.

## Code Style
- No `from __future__ import annotations` = no `X | None` syntax. Use `Optional[X]` or add the import.
- All QComboBox must call `.setView(QListView())` after creation — macOS native dropdowns ignore Qt styling.
- QThread workers stored in `self._workers` list to prevent garbage collection.
- Lazy imports inside worker `run()` methods to avoid import-time side effects.
- Config values via `python-dotenv` in `.env`. Getter/setter pattern in `app/config.py`.

## UI Conventions
- Dark theme in `app/style.qss`. All styling through QSS, not inline where possible.
- Buttons: use `setMinimumWidth()`, never `setFixedWidth()` — text truncation has been a recurring issue. Fixed widths are only for non-button widgets (combos, sliders, etc.).
- Dialogs: use generous `setMinimumWidth()` (600+). When a dialog has many buttons in a row, test that the minimum width accommodates all of them without truncation.
- Context menus and dropdowns must have hover highlighting (QMenu + QComboBox QAbstractItemView styled in QSS).
- Settings dialog opens as modal, sidebar button deselects after dialog closes.
- Popup dialogs: use `QMessageBox.Icon.NoIcon` for success messages (no exclamation mark).

## DaVinci Integration
- Resolve scripting API accessed via `app/services/davinci_resolve.py` using dynamic import of `DaVinciResolveScript`.
- OTIO used as intermediary format. Must include both V1 (video) and A1 (audio) tracks.
- DaVinci Assistant targets beginners.

## LUT System
- Bundled LUTs in `app/luts/`. Sony/Canon/Nikon LUTs are gitignored (license restrictions).
- User-installed LUTs saved via `install_lut()` in `video_prep.py`, tracked in `custom_profiles.json`.
- Canon cameras default to C-Log2 (not C-Log3) for auto-detection.
- Detection uses: make tags → container brand (XFVC=Canon, XAVC=Sony) → filename heuristic.

## Embedding Cache
- Video embeddings cached in `.embeddings_cache/{index_id}/{video_id}.json`.
- Cached after upload; parallel-fetched on cache miss during search.
- `fetch_many()` in `embedding_cache.py` is the main entry point.

## Manual RAG Knowledge Base
- Pre-computed FAISS index shipped in `app/data/manual_index/` (no copyrighted text).
- User provides PDF → text + images extracted at runtime → cached in `.davinci_manual/`.
- Voyage AI for query embedding. Retrieved chunks injected into assistant system prompt.

## Don't Do
- Don't commit without being asked.
- Don't add features beyond what's requested.
- Don't push to remote without being asked.
- Don't create README or documentation files unless asked.
- Don't use `subprocess.run` for screen capture — use Quartz `CGWindowListCreateImage`.

## Common Pitfalls
- `from __future__ import annotations` missing → `TypeError: unsupported operand type(s) for |`.
- QComboBox without `setView(QListView())` → native macOS dropdown ignoring dark theme.
- `page_limit=1000` on Twelve Labs API → error. Use iterator with `page_limit=50`.
- Embedding cache `fetch_many()` not used → sequential API calls, slow search.
- OTIO export with only video track → no audio in DaVinci timeline.
