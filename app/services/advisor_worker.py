"""QThread worker for the DaVinci Resolve Assistant.

Calls the Anthropic Messages API with streaming and vision support.
Each call receives the full conversation history and an optional screenshot.
Retrieves relevant manual sections via RAG when available.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QThread, Signal

from app.config import get_anthropic_api_key, get_vision_model
from app.services.advisor_prompts import ADVISOR_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


def _extract_user_text(conversation: list[dict]) -> str:
    """Extract the latest user text from the conversation for RAG retrieval."""
    for msg in reversed(conversation):
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    return block.get("text", "")
    return ""


def _build_rag_context(user_text: str) -> tuple[str, list[dict]]:
    """Retrieve relevant manual sections and build context.

    Returns (text_context, image_blocks) where image_blocks are
    base64-encoded images from the manual figures.
    """
    try:
        from app.services.knowledge_base import search, is_ready, image_to_base64

        if not is_ready() or not user_text:
            return "", []

        results = search(user_text, top_k=5)
        if not results:
            return "", []

        text_parts = []
        image_blocks = []

        for i, r in enumerate(results):
            source = r.get("source_pdf", "")
            page = r.get("page", "?")
            section = r.get("section", "")
            text = r.get("text", "")

            header = f"[{source}, p.{page}]"
            if section:
                header += f" {section}"
            text_parts.append(f"{header}\n{text}")

            # Include images only for top 2 results, max 2 images each
            if i < 2:
                for img_path in r.get("images", [])[:2]:
                    b64 = image_to_base64(img_path)
                    if b64:
                        image_blocks.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": b64,
                            },
                        })

        text_context = "\n\n---\n\n".join(text_parts)
        return text_context, image_blocks

    except Exception as e:
        logger.warning("RAG retrieval failed: %s", e)
        return "", []


class AdvisorWorker(QThread):
    """Streams a response from Claude given conversation history + screenshot."""
    token = Signal(str)
    stream_done = Signal(str)   # full response text
    error = Signal(str)

    def __init__(self, conversation: list[dict], parent=None):
        super().__init__(parent)
        self.conversation = conversation

    def run(self):
        try:
            import anthropic
            api_key = get_anthropic_api_key()
            if not api_key:
                self.error.emit("Anthropic API key not set. Add it in Settings.")
                return

            client = anthropic.Anthropic(api_key=api_key)

            # Build system prompt with RAG context if available
            user_text = _extract_user_text(self.conversation)
            rag_text, rag_images = _build_rag_context(user_text)

            system = ADVISOR_SYSTEM_PROMPT
            if rag_text:
                system += (
                    "\n\n## Reference from DaVinci Resolve Manual\n\n"
                    + rag_text
                )

            # If we have manual images, prepend them to the conversation
            # as a system-injected context message
            messages = list(self.conversation)
            if rag_images:
                # Insert manual figure context before the last user message
                fig_content = [
                    {"type": "text", "text": "Here are relevant figures from the DaVinci Resolve manual:"},
                ] + rag_images
                # Add as part of the system context via a cache-friendly approach:
                # inject into the last user message's content
                if messages and messages[-1].get("role") == "user":
                    last_msg = messages[-1]
                    content = last_msg.get("content", "")
                    if isinstance(content, list):
                        messages[-1] = {
                            "role": "user",
                            "content": fig_content + content,
                        }
                    else:
                        messages[-1] = {
                            "role": "user",
                            "content": fig_content + [{"type": "text", "text": content}],
                        }

            full_text = ""
            with client.messages.stream(
                model=get_vision_model(),
                max_tokens=1024,
                system=system,
                messages=messages,
            ) as stream:
                for text in stream.text_stream:
                    full_text += text
                    self.token.emit(text)

            self.stream_done.emit(full_text)

        except Exception as e:
            logger.error("Advisor error: %s", e)
            self.error.emit(str(e))
