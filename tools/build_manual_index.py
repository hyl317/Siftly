#!/usr/bin/env python3
"""Build the shipped manual index (FAISS embeddings + chunk metadata).

Run this once as a developer to generate app/data/manual_index/.
The output is committed to the repo. Users provide their own PDFs at runtime
to extract the actual text and images.

Usage:
    python tools/build_manual_index.py \
        --pdfs path/to/Beginners-Guide.pdf path/to/Reference-Manual.pdf \
        --voyage-key pa-...
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

import faiss
import numpy as np
from pypdf import PdfReader

# ── Section-aware chunking ───────────────────────────────────────────

MAX_CHUNK_CHARS = 4000   # ~1024 tokens — larger since sections are coherent
OVERLAP_CHARS = 200      # ~50 tokens overlap

# Font names that indicate section headings
HEADING_FONTS = {"semibold", "semi-bold"}


def _is_heading_font(font_name: str) -> bool:
    """Check if a font name indicates a section heading."""
    return any(h in font_name.lower() for h in HEADING_FONTS)


def _normalize_text(text: str) -> str:
    text = text.replace("\r", "\n")
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n+', '\n\n', text)
    return text.strip()


def _extract_structured_page(page) -> list[dict]:
    """Extract text with font info from a page using visitor pattern.

    Returns list of {"text": str, "is_heading": bool}.
    """
    segments = []

    def visitor(text, cm, tm, font_dict, font_size):
        if not text.strip():
            return
        font_name = ""
        if font_dict:
            font_name = font_dict.get("/BaseFont", "")
        segments.append({
            "text": text.strip(),
            "is_heading": _is_heading_font(font_name),
        })

    page.extract_text(visitor_text=visitor)
    return segments


def chunk_pdf(pdf_path: str, progress_fn=None) -> list[dict]:
    """Parse a PDF with section-aware chunking.

    Returns list of chunk dicts with metadata (no text in shipped output).
    """
    reader = PdfReader(pdf_path)
    filename = Path(pdf_path).name
    total_pages = len(reader.pages)
    all_chunks = []

    current_section = ""
    current_text = ""
    current_pages = set()
    current_start_page = 1
    current_char_start = 0
    chunk_index = 0

    def flush_chunk():
        nonlocal current_text, current_pages, current_start_page
        nonlocal current_char_start, chunk_index

        text = _normalize_text(current_text)
        if not text or len(text) < 50:
            # Too short to be a useful chunk — will be prepended to next chunk
            return

        # If chunk is too large, split at paragraph boundaries
        if len(text) > MAX_CHUNK_CHARS:
            sub_chunks = _split_large_chunk(text, MAX_CHUNK_CHARS, OVERLAP_CHARS)
        else:
            sub_chunks = [text]

        for sub in sub_chunks:
            # Count images across all pages in this chunk
            num_images = 0
            for pg in current_pages:
                try:
                    num_images += len(reader.pages[pg - 1].images)
                except Exception:
                    pass

            all_chunks.append({
                "source_pdf": filename,
                "page": min(current_pages) if current_pages else current_start_page,
                "pages": sorted(current_pages) if len(current_pages) > 1 else None,
                "section": current_section,
                "chunk_index": chunk_index,
                "char_start": current_char_start,
                "char_end": current_char_start + len(sub),
                "num_images": num_images,
                "text": sub,  # used for embedding only, NOT shipped
            })
            chunk_index += 1
            current_char_start += len(sub)

        current_text = ""
        current_pages = set()

    for page_idx in range(total_pages):
        if progress_fn:
            progress_fn(page_idx + 1, total_pages)

        page = reader.pages[page_idx]
        page_num = page_idx + 1

        segments = _extract_structured_page(page)

        for seg in segments:
            if seg["is_heading"]:
                # New section heading — flush current chunk
                flush_chunk()
                current_section = seg["text"]
                current_start_page = page_num
                current_pages = {page_num}
                current_text = seg["text"] + "\n"
            else:
                current_text += seg["text"] + "\n"
                current_pages.add(page_num)

        # Check if current chunk is getting large
        if len(current_text) > MAX_CHUNK_CHARS:
            flush_chunk()
            current_start_page = page_num

    # Final flush
    flush_chunk()

    return all_chunks


def _split_large_chunk(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    """Split a large text at paragraph boundaries."""
    paragraphs = [p.strip() for p in re.split(r'\n{1,2}', text) if p.strip()]
    chunks = []
    current = ""

    for para in paragraphs:
        if not current:
            current = para
        elif len(current) + len(para) + 1 <= max_chars:
            current += "\n" + para
        else:
            chunks.append(current)
            # Overlap from tail of previous
            tail = current[-overlap_chars:] if len(current) > overlap_chars else current
            current = tail + "\n" + para

    if current.strip():
        chunks.append(current)

    return chunks


# ── Embedding via Voyage AI ──────────────────────────────────────────

def embed_texts(texts: list[str], voyage_key: str, batch_size: int = 128) -> np.ndarray:
    """Embed texts using Voyage AI. Returns (N, dim) float32 array."""
    import voyageai
    client = voyageai.Client(api_key=voyage_key)

    all_embeddings = []
    total_batches = (len(texts) + batch_size - 1) // batch_size
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        batch_num = i // batch_size + 1
        print(f"  Batch {batch_num}/{total_batches} "
              f"({i + 1}-{min(i + len(batch), len(texts))} of {len(texts)})")
        result = client.embed(batch, model="voyage-3", input_type="document")
        all_embeddings.extend(result.embeddings)

    return np.array(all_embeddings, dtype=np.float32)


# ── Main ─────────────────────────────────────────────────────────────

def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(8192), b""):
            h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description="Build shipped manual index")
    parser.add_argument("--pdfs", nargs="+", required=True, help="PDF files to index")
    parser.add_argument("--voyage-key", required=True, help="Voyage AI API key")
    parser.add_argument("--output", default="app/data/manual_index",
                        help="Output directory")
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Chunk all PDFs with section-aware chunking
    print("Chunking PDFs (section-aware)...")
    all_chunks = []
    for pdf_path in args.pdfs:
        print(f"  {Path(pdf_path).name}")

        def progress(current, total):
            if current % 100 == 0 or current == total:
                print(f"    Page {current}/{total}")

        chunks = chunk_pdf(pdf_path, progress_fn=progress)
        sections = len({c["section"] for c in chunks if c["section"]})
        print(f"    → {len(chunks)} chunks, {sections} sections")
        all_chunks.extend(chunks)

    print(f"\nTotal: {len(all_chunks)} chunks")

    # 2. Embed
    print("\nEmbedding with Voyage AI (voyage-3)...")
    texts = [c["text"] for c in all_chunks]
    embeddings = embed_texts(texts, args.voyage_key)
    print(f"Embeddings shape: {embeddings.shape}")

    # 3. Normalize for cosine similarity
    faiss.normalize_L2(embeddings)

    # 4. Build FAISS index
    dim = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(embeddings)
    faiss.write_index(index, str(output_dir / "index.faiss"))
    print(f"FAISS index written: {dim}-dim, {index.ntotal} vectors")

    # 5. Write chunk metadata (WITHOUT text)
    meta = []
    for c in all_chunks:
        entry = {
            "source_pdf": c["source_pdf"],
            "page": c["page"],
            "section": c["section"],
            "chunk_index": c["chunk_index"],
            "char_start": c["char_start"],
            "char_end": c["char_end"],
            "num_images": c["num_images"],
        }
        if c.get("pages"):
            entry["pages"] = c["pages"]
        meta.append(entry)

    (output_dir / "chunks_meta.json").write_text(json.dumps(meta))
    print(f"Chunk metadata written: {len(meta)} entries")

    # 6. Write manifest
    manuals = []
    for pdf_path in args.pdfs:
        manuals.append({
            "filename": Path(pdf_path).name,
            "sha256": sha256_file(pdf_path),
        })
    manifest = {
        "manuals": manuals,
        "embedding_model": "voyage-3",
        "embedding_dim": dim,
        "num_chunks": len(all_chunks),
        "created": str(date.today()),
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print("Manifest written")

    # Stats
    total_images = sum(c["num_images"] for c in all_chunks)
    print(f"\nStats:")
    print(f"  Total chunks: {len(all_chunks)}")
    print(f"  Chunks with images: {sum(1 for c in all_chunks if c['num_images'] > 0)}")
    print(f"  Total image references: {total_images}")
    print(f"\nDone! Output in: {output_dir}")


if __name__ == "__main__":
    main()
