"""Claude Computer Use integration for DaVinci Resolve automation.

Uses Anthropic's Computer Use API — Claude sees screenshots, decides what
to do (click, type, press keys), and we execute the actions. Claude drives
the loop; we're just the hands.
"""
from __future__ import annotations

import base64
import io
import logging
from dataclasses import dataclass, field

from PIL import Image

from pathlib import Path

from app.config import get_anthropic_api_key, get_vision_model

logger = logging.getLogger(__name__)

# Load shortcuts reference once at import time
_SHORTCUTS_PATH = Path(__file__).parent / "shortcuts.md"


def _load_shortcuts() -> str:
    """Load the shortcuts.md file for inclusion in the system prompt."""
    if _SHORTCUTS_PATH.is_file():
        return _SHORTCUTS_PATH.read_text()
    return ""

# Computer Use tool version and beta header for current Claude models
_TOOL_VERSION = "computer_20251124"
_BETA_HEADER = "computer-use-2025-11-24"


@dataclass
class ComputerAction:
    """A single action requested by Claude."""
    tool_use_id: str
    action: str         # "screenshot", "left_click", "key", "type", etc.
    coordinate: tuple[int, int] | None = None
    text: str | None = None
    scroll_direction: str | None = None
    scroll_amount: int | None = None


@dataclass
class AgentTurn:
    """One turn of Claude's response — may contain text and/or actions."""
    text: str = ""
    actions: list[ComputerAction] = field(default_factory=list)
    stop_reason: str = ""


def _get_client():
    """Create an Anthropic client using the stored API key."""
    import anthropic

    api_key = get_anthropic_api_key()
    if not api_key:
        raise ValueError(
            "Anthropic API key not set. Add it in Settings → Anthropic API Key."
        )
    return anthropic.Anthropic(api_key=api_key)


def _image_to_base64(image: Image.Image) -> str:
    """Encode a PIL image as base64 PNG."""
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return base64.standard_b64encode(buf.getvalue()).decode("ascii")


def create_computer_tool(display_width: int, display_height: int) -> dict:
    """Build the computer tool definition for the API call."""
    return {
        "type": _TOOL_VERSION,
        "name": "computer",
        "display_width_px": display_width,
        "display_height_px": display_height,
    }


def send_task(
    task: str,
    display_width: int,
    display_height: int,
    messages: list[dict] | None = None,
) -> AgentTurn:
    """Send a task (or continue a conversation) to Claude with computer use.

    Args:
        task: The instruction for Claude (only used if messages is None).
        display_width: Screen width in the coordinate space Claude should use.
        display_height: Screen height in the coordinate space Claude should use.
        messages: Existing conversation messages (for continuing the loop).

    Returns:
        AgentTurn with any text response and requested actions.
    """
    client = _get_client()

    if messages is None:
        messages = [{"role": "user", "content": task}]

    tool = create_computer_tool(display_width, display_height)

    response = client.beta.messages.create(
        model=get_vision_model(),
        max_tokens=4096,
        tools=[tool],
        messages=messages,
        betas=[_BETA_HEADER],
        system=(
            "You are automating DaVinci Resolve on macOS. "
            "Use keyboard shortcuts whenever possible — they are faster, "
            "more reliable, and cheaper than clicking. Only use mouse clicks "
            "for UI elements that have no keyboard shortcut.\n\n"
            "IMPORTANT: In the shortcut reference below, on macOS:\n"
            "- Cmd = Command key\n"
            "- Opt = Option/Alt key\n"
            "When sending keys via the computer tool, use these mappings:\n"
            "- Cmd = super\n"
            "- Opt = alt\n"
            "- Shift = shift\n\n"
            "Always take a screenshot first to see the current state before acting. "
            "After clicking or pressing keys, take another screenshot to verify "
            "the result before proceeding.\n\n"
            "--- KEYBOARD SHORTCUTS REFERENCE ---\n\n"
            + _load_shortcuts()
        ),
    )

    return _parse_response(response)


def build_tool_result(
    tool_use_id: str,
    screenshot: Image.Image | None = None,
    text: str | None = None,
    is_error: bool = False,
) -> dict:
    """Build a tool_result message to send back to Claude.

    Args:
        tool_use_id: The ID from the ComputerAction.
        screenshot: Screenshot to send back (for screenshot actions).
        text: Text result (for non-screenshot actions).
        is_error: Whether this result represents an error.
    """
    content: list[dict] = []

    if screenshot is not None:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": _image_to_base64(screenshot),
            },
        })

    if text:
        content.append({"type": "text", "text": text})

    if not content:
        content.append({"type": "text", "text": "OK"})

    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": content,
        "is_error": is_error,
    }


def _parse_response(response) -> AgentTurn:
    """Parse Claude's response into an AgentTurn."""
    turn = AgentTurn(stop_reason=response.stop_reason)

    for block in response.content:
        if hasattr(block, "text"):
            turn.text += block.text
        elif block.type == "tool_use":
            inp = block.input
            action = ComputerAction(
                tool_use_id=block.id,
                action=inp.get("action", ""),
                coordinate=tuple(inp["coordinate"]) if "coordinate" in inp else None,
                text=inp.get("text"),
                scroll_direction=inp.get("scroll_direction"),
                scroll_amount=inp.get("scroll_amount"),
            )
            turn.actions.append(action)

    return turn
