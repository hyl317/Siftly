"""RAG knowledge base for the DaVinci Resolve manual.

Pre-computed FAISS embeddings ship with the repo (app/data/manual_index/).
The user provides their own PDF to extract text and images at runtime.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
from pathlib import Path

import faiss
import numpy as np

from app.config import MANUAL_INDEX_DIR, get_voyage_api_key

logger = logging.getLogger(__name__)

SHIPPED_INDEX_DIR = Path(__file__).resolve().parent.parent / "data" / "manual_index"
LOCAL_CACHE_DIR = MANUAL_INDEX_DIR
TEXTS_CACHE = LOCAL_CACHE_DIR / "texts.json"
FIGURES_DIR = LOCAL_CACHE_DIR / "figures"

# Cached at module level after first load
_faiss_index = None
_chunks_meta = None
_texts_cache = None


def _load_manifest() -> dict | None:
    path = SHIPPED_INDEX_DIR / "manifest.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text())


def _load_faiss_index():
    global _faiss_index
    if _faiss_index is None:
        path = SHIPPED_INDEX_DIR / "index.faiss"
        if path.is_file():
            _faiss_index = faiss.read_index(str(path))
    return _faiss_index


def _load_chunks_meta() -> list[dict]:
    global _chunks_meta
    if _chunks_meta is None:
        path = SHIPPED_INDEX_DIR / "chunks_meta.json"
        if path.is_file():
            _chunks_meta = json.loads(path.read_text())
        else:
            _chunks_meta = []
    return _chunks_meta


def _load_texts_cache() -> list[str]:
    global _texts_cache
    if _texts_cache is None:
        if TEXTS_CACHE.is_file():
            _texts_cache = json.loads(TEXTS_CACHE.read_text())
        else:
            _texts_cache = []
    return _texts_cache


def _invalidate_caches():
    global _faiss_index, _chunks_meta, _texts_cache
    _faiss_index = None
    _chunks_meta = None
    _texts_cache = None


# ── PDF validation ───────────────────────────────────────────────────

def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(8192), b""):
            h.update(block)
    return h.hexdigest()


def validate_pdf(pdf_path: str) -> tuple[bool, str]:
    """Check if a PDF matches one of the expected manuals.

    Returns (valid, matched_filename_or_error_message).
    """
    manifest = _load_manifest()
    if not manifest:
        return False, "No manifest.json found — shipped index may be missing"

    file_hash = sha256_file(pdf_path)
    for manual in manifest.get("manuals", []):
        if manual["sha256"] == file_hash:
            return True, manual["filename"]

    expected = ", ".join(m["filename"] for m in manifest.get("manuals", []))
    return False, f"PDF doesn't match any expected manual. Expected: {expected}"


# ── Text + image extraction ──────────────────────────────────────────

def extract_and_cache(pdf_paths: list[str], progress_fn=None) -> int:
    """Extract text and images from user-provided PDFs and cache locally.

    Aligns extracted text with chunks_meta.json page/char offsets.
    Returns number of chunks successfully aligned.
    """
    from pypdf import PdfReader

    meta = _load_chunks_meta()
    if not meta:
        raise RuntimeError("No chunks_meta.json found")

    LOCAL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    # Build page text + extract images for each PDF
    page_texts: dict[str, dict[int, str]] = {}  # {filename: {page_num: text}}

    total_pages = 0
    for pdf_path in pdf_paths:
        reader = PdfReader(pdf_path)
        total_pages += len(reader.pages)

    current_page = 0
    for pdf_path in pdf_paths:
        reader = PdfReader(pdf_path)
        filename = Path(pdf_path).name
        page_texts[filename] = {}

        # Create figures dir for this PDF
        pdf_figures_dir = FIGURES_DIR / filename.replace(".pdf", "")
        pdf_figures_dir.mkdir(parents=True, exist_ok=True)

        for page_idx, page in enumerate(reader.pages):
            current_page += 1
            if progress_fn:
                progress_fn(current_page, total_pages)

            page_num = page_idx + 1

            # Extract text
            text = page.extract_text() or ""
            page_texts[filename][page_num] = text

            # Extract images
            for img_idx, img in enumerate(page.images):
                img_path = pdf_figures_dir / f"page_{page_num}_img_{img_idx}.jpg"
                if not img_path.exists():
                    img_path.write_bytes(img.data)

    # Align chunks with extracted text using page + char offsets
    texts = []
    aligned = 0
    for chunk in meta:
        source = chunk["source_pdf"]
        page = chunk["page"]
        char_start = chunk.get("char_start", 0)
        char_end = chunk.get("char_end", 0)

        page_text = page_texts.get(source, {}).get(page, "")
        if page_text and char_end > 0:
            # Try exact offset alignment
            chunk_text = page_text[char_start:char_end]
            if len(chunk_text.strip()) > 20:
                texts.append(chunk_text)
                aligned += 1
                continue

        # Fallback: use the section name + full page text
        section = chunk.get("section", "")
        if page_text:
            texts.append(f"{section}\n{page_text}" if section else page_text)
            aligned += 1
        else:
            texts.append(section or f"[page {page} text not available]")

    # Save texts cache
    TEXTS_CACHE.write_text(json.dumps(texts))
    _invalidate_caches()

    logger.info("Aligned %d/%d chunks with extracted text", aligned, len(meta))
    return aligned


# ── Query-time search ────────────────────────────────────────────────

def embed_query(query: str) -> np.ndarray:
    """Embed a query using Voyage AI. Returns (1, dim) float32 array."""
    import voyageai
    api_key = get_voyage_api_key()
    if not api_key:
        raise ValueError("Voyage AI API key not set")
    client = voyageai.Client(api_key=api_key)
    result = client.embed([query], model="voyage-3", input_type="query")
    vec = np.array([result.embeddings[0]], dtype=np.float32)
    faiss.normalize_L2(vec)
    return vec


def search(query: str, top_k: int = 5) -> list[dict]:
    """Search the manual index.

    Returns list of {text, source_pdf, page, section, score, images: [path, ...]}.
    """
    index = _load_faiss_index()
    meta = _load_chunks_meta()
    texts = _load_texts_cache()

    if index is None or not meta or not texts:
        return []

    query_vec = embed_query(query)
    scores, indices = index.search(query_vec, min(top_k, index.ntotal))

    results = []
    for score, idx in zip(scores[0], indices[0]):
        if idx < 0 or idx >= len(meta):
            continue

        chunk = meta[idx]
        text = texts[idx] if idx < len(texts) else ""

        # Find associated images
        images = _get_chunk_images(chunk)

        results.append({
            "text": text,
            "source_pdf": chunk.get("source_pdf", ""),
            "page": chunk.get("page", 0),
            "section": chunk.get("section", ""),
            "score": float(score),
            "images": images,
        })

    return results


def _get_chunk_images(chunk: dict) -> list[str]:
    """Get image paths for a chunk's page(s)."""
    if chunk.get("num_images", 0) == 0:
        return []

    source = chunk["source_pdf"].replace(".pdf", "")
    pages = chunk.get("pages") or [chunk["page"]]
    images = []

    for page in pages:
        page_dir = FIGURES_DIR / source
        if page_dir.is_dir():
            for img_path in sorted(page_dir.glob(f"page_{page}_img_*.jpg")):
                images.append(str(img_path))

    return images


def image_to_base64(path: str) -> str | None:
    """Load an image file as base64 for the Claude API."""
    p = Path(path)
    if not p.is_file():
        return None
    data = p.read_bytes()
    return base64.standard_b64encode(data).decode("ascii")


# ── Status ───────────────────────────────────────────────────────────

def is_ready() -> bool:
    """True if shipped index exists AND local text cache exists."""
    return (
        (SHIPPED_INDEX_DIR / "index.faiss").is_file()
        and TEXTS_CACHE.is_file()
    )


def get_status() -> dict:
    """Get current knowledge base status."""
    manifest = _load_manifest()
    meta = _load_chunks_meta()
    texts_loaded = TEXTS_CACHE.is_file()

    status = {
        "has_index": (SHIPPED_INDEX_DIR / "index.faiss").is_file(),
        "texts_loaded": texts_loaded,
        "num_chunks": len(meta),
        "num_texts": len(_load_texts_cache()) if texts_loaded else 0,
    }

    if manifest:
        status["embedding_model"] = manifest.get("embedding_model", "")
        status["manuals"] = [m["filename"] for m in manifest.get("manuals", [])]
    else:
        status["manuals"] = []

    return status
