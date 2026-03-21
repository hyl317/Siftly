"""Magic Mask automation task.

With Computer Use, the task is just a prompt — Claude handles the rest.
"""

TASK_PROMPT = (
    "I need you to apply Magic Mask to the current clip in DaVinci Resolve. "
    "Please do the following:\n\n"
    "1. First take a screenshot to see the current state\n"
    "2. Switch to the Color page (Shift+6)\n"
    "3. Add a new serial node (Alt+S)\n"
    "4. Find and click the Magic Mask icon in the Color page toolbar\n"
    "5. Once the Magic Mask panel opens, click the person/people tracking button\n"
    "6. Take a final screenshot to confirm tracking has started\n\n"
    "Use keyboard shortcuts whenever possible. Take a screenshot after each "
    "major action to verify it worked before moving on."
)
