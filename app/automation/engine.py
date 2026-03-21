"""Automation engine — Claude Computer Use agentic loop.

Claude drives the interaction: it requests screenshots, decides what to
click/type/press, and we execute the actions and feed back results.
"""
from __future__ import annotations

import logging
import time
from typing import Callable

from PIL import Image

from app.automation.screen_capture import (
    capture_window,
    get_display_scale_factor,
    get_resolve_window_id,
    pixels_to_points,
)
from app.automation.input_control import (
    ensure_resolve_frontmost,
    click_point,
    press_key,
)
from app.automation.vision import (
    AgentTurn,
    ComputerAction,
    build_tool_result,
    send_task,
)

logger = logging.getLogger(__name__)

# Max iterations to prevent runaway loops
MAX_ITERATIONS = 30


class AutomationEngine:
    """Runs a Claude Computer Use loop to accomplish a task in DaVinci Resolve.

    Usage:
        engine = AutomationEngine(on_progress=my_callback)
        result = engine.run("Open Magic Mask on the current clip")
    """

    def __init__(
        self,
        on_progress: Callable[[str, str], None] | None = None,
        settle_time: float = 0.5,
    ):
        """
        Args:
            on_progress: Callback(status, detail) for UI updates.
            settle_time: Seconds to wait after actions for UI to settle.
        """
        self._on_progress = on_progress
        self._settle_time = settle_time
        self._cancelled = False
        self._scale_factor = 1.0
        self._window_id: int | None = None
        self._display_w = 0
        self._display_h = 0

    def cancel(self):
        self._cancelled = True

    def _report(self, status: str, detail: str):
        if self._on_progress:
            self._on_progress(status, detail)
        logger.info("[%s] %s", status, detail)

    def _setup(self):
        """Verify Resolve is running and get display dimensions."""
        self._scale_factor = get_display_scale_factor()

        self._window_id = get_resolve_window_id()
        if self._window_id is None:
            raise RuntimeError(
                "Cannot find DaVinci Resolve window. "
                "Make sure Resolve is open and visible."
            )

        # Capture once to get the display dimensions Claude should use.
        # Computer Use coordinates are in the screenshot's pixel space.
        screenshot = capture_window(self._window_id)
        self._display_w = screenshot.width
        self._display_h = screenshot.height
        self._report("ready", f"Resolve found ({self._display_w}x{self._display_h})")

    def _capture(self) -> Image.Image:
        """Capture the Resolve window."""
        if self._window_id is None:
            self._window_id = get_resolve_window_id()
        if self._window_id is None:
            raise RuntimeError("Lost DaVinci Resolve window")
        return capture_window(self._window_id)

    def _execute_action(self, action: ComputerAction) -> dict:
        """Execute a single action from Claude and return a tool_result."""
        try:
            if action.action == "screenshot":
                screenshot = self._capture()
                self._report("screenshot", "Captured Resolve window")
                return build_tool_result(action.tool_use_id, screenshot=screenshot)

            elif action.action == "left_click":
                if action.coordinate is None:
                    return build_tool_result(
                        action.tool_use_id, text="No coordinate provided", is_error=True
                    )
                px, py = action.coordinate
                self._report("click", f"Clicking at ({px}, {py})")
                click_point(px, py, self._scale_factor)
                time.sleep(self._settle_time)
                return build_tool_result(action.tool_use_id, text="Clicked")

            elif action.action == "right_click":
                if action.coordinate is None:
                    return build_tool_result(
                        action.tool_use_id, text="No coordinate provided", is_error=True
                    )
                import pyautogui
                px, py = action.coordinate
                pt_x, pt_y = pixels_to_points(px, py, self._scale_factor)
                ensure_resolve_frontmost()
                pyautogui.rightClick(pt_x, pt_y)
                time.sleep(self._settle_time)
                return build_tool_result(action.tool_use_id, text="Right-clicked")

            elif action.action == "double_click":
                if action.coordinate is None:
                    return build_tool_result(
                        action.tool_use_id, text="No coordinate provided", is_error=True
                    )
                import pyautogui
                px, py = action.coordinate
                pt_x, pt_y = pixels_to_points(px, py, self._scale_factor)
                ensure_resolve_frontmost()
                pyautogui.doubleClick(pt_x, pt_y)
                time.sleep(self._settle_time)
                return build_tool_result(action.tool_use_id, text="Double-clicked")

            elif action.action == "key":
                if not action.text:
                    return build_tool_result(
                        action.tool_use_id, text="No key specified", is_error=True
                    )
                self._report("key", f"Pressing {action.text}")
                self._press_computer_use_key(action.text)
                time.sleep(self._settle_time)
                return build_tool_result(action.tool_use_id, text=f"Pressed {action.text}")

            elif action.action == "type":
                if not action.text:
                    return build_tool_result(
                        action.tool_use_id, text="No text specified", is_error=True
                    )
                import pyautogui
                self._report("type", f"Typing: {action.text[:50]}")
                ensure_resolve_frontmost()
                pyautogui.typewrite(action.text, interval=0.02)
                time.sleep(self._settle_time)
                return build_tool_result(action.tool_use_id, text="Typed")

            elif action.action == "scroll":
                if action.coordinate is None:
                    return build_tool_result(
                        action.tool_use_id, text="No coordinate provided", is_error=True
                    )
                import pyautogui
                px, py = action.coordinate
                pt_x, pt_y = pixels_to_points(px, py, self._scale_factor)
                amount = action.scroll_amount or 3
                direction = action.scroll_direction or "down"
                ensure_resolve_frontmost()
                pyautogui.moveTo(pt_x, pt_y)
                clicks = amount if direction == "down" else -amount
                pyautogui.scroll(clicks)
                time.sleep(self._settle_time)
                return build_tool_result(action.tool_use_id, text="Scrolled")

            elif action.action == "mouse_move":
                if action.coordinate is None:
                    return build_tool_result(
                        action.tool_use_id, text="No coordinate provided", is_error=True
                    )
                import pyautogui
                px, py = action.coordinate
                pt_x, pt_y = pixels_to_points(px, py, self._scale_factor)
                ensure_resolve_frontmost()
                pyautogui.moveTo(pt_x, pt_y)
                return build_tool_result(action.tool_use_id, text="Moved mouse")

            else:
                return build_tool_result(
                    action.tool_use_id,
                    text=f"Unknown action: {action.action}",
                    is_error=True,
                )

        except Exception as e:
            logger.error("Action %s failed: %s", action.action, e)
            return build_tool_result(
                action.tool_use_id, text=f"Error: {e}", is_error=True
            )

    def _press_computer_use_key(self, key_text: str):
        """Parse Computer Use key format and press via pyautogui.

        Claude sends keys like "shift+6", "alt+s", "Return", "space", etc.
        """
        parts = key_text.lower().split("+")
        if len(parts) == 1:
            # Single key
            key_map = {
                "return": "return", "enter": "return",
                "space": "space", "tab": "tab",
                "escape": "escape", "esc": "escape",
                "backspace": "backspace", "delete": "delete",
                "up": "up", "down": "down", "left": "left", "right": "right",
                "super": "command", "cmd": "command", "command": "command",
            }
            key = key_map.get(parts[0], parts[0])
            press_key(key)
        else:
            # Key combo like "shift+6", "alt+s"
            *modifiers, key = parts
            mod_map = {
                "alt": "option", "opt": "option", "option": "option",
                "shift": "shift",
                "ctrl": "ctrl", "control": "ctrl",
                "cmd": "command", "command": "command", "super": "command",
                "meta": "command",
            }
            mapped_mods = [mod_map.get(m, m) for m in modifiers]
            press_key(key, mapped_mods)

    def run(self, task: str) -> str:
        """Run an automation task using Claude Computer Use.

        Args:
            task: Natural language description of what to do.
                  e.g. "Switch to the Color page and apply Magic Mask"

        Returns:
            Claude's final text response summarizing what was done.
        """
        self._setup()
        self._report("starting", task)

        messages = [{"role": "user", "content": task}]
        final_text = ""

        for iteration in range(MAX_ITERATIONS):
            if self._cancelled:
                self._report("cancelled", "Automation cancelled by user")
                return "Cancelled"

            self._report("thinking", f"Iteration {iteration + 1}")

            turn = send_task(
                task="",  # Not used when messages is provided
                display_width=self._display_w,
                display_height=self._display_h,
                messages=messages,
            )

            # Collect any text Claude said
            if turn.text:
                final_text = turn.text
                self._report("message", turn.text)

            # If Claude didn't request any tool use, it's done
            if not turn.actions:
                self._report("done", final_text or "Task complete")
                return final_text or "Task complete"

            # Add Claude's response to the conversation
            # Rebuild the content blocks from the turn
            assistant_content = []
            if turn.text:
                assistant_content.append({"type": "text", "text": turn.text})
            for action in turn.actions:
                tool_input = {"action": action.action}
                if action.coordinate is not None:
                    tool_input["coordinate"] = list(action.coordinate)
                if action.text is not None:
                    tool_input["text"] = action.text
                if action.scroll_direction is not None:
                    tool_input["scroll_direction"] = action.scroll_direction
                if action.scroll_amount is not None:
                    tool_input["scroll_amount"] = action.scroll_amount
                assistant_content.append({
                    "type": "tool_use",
                    "id": action.tool_use_id,
                    "name": "computer",
                    "input": tool_input,
                })
            messages.append({"role": "assistant", "content": assistant_content})

            # Execute each action and collect results
            tool_results = []
            for action in turn.actions:
                if self._cancelled:
                    break
                result = self._execute_action(action)
                tool_results.append(result)

            messages.append({"role": "user", "content": tool_results})

        self._report("done", "Reached max iterations")
        return final_text or "Reached max iterations"
