"""AskUser — request clarification from the user."""


from __future__ import annotations

from typing import Any

from harzoo.agent.kernel.tool import Context, Tool, ToolResult

TOOL_VERSION = "2026-06-29"


class AskUserTool(Tool):
    """Ask the user a question and wait for their response in the next turn."""

    name = "AskUser"
    description = (
        "Ask the user a clarifying question before proceeding. "
        "Present the question in your assistant message; the user will reply in the next turn."
    )
    parameters = {
        "properties": {
            "question": {"type": "string", "description": "Question to ask the user"},
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional multiple-choice options",
            },
            "context": {"type": "string", "description": "Optional background context for the question"},
        },
        "required": ["question"],
    }

    def execute(
        self,
        question: str,
        options: list[str] | None = None,
        context: str | None = None,
        *,
        ctx: Context | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        del kwargs, ctx
        q = str(question or "").strip()
        if not q:
            return ToolResult.failure("question must not be empty", code="INVALID_ARGUMENTS")
        opts = [str(o).strip() for o in (options or []) if str(o).strip()]
        ctx_text = str(context or "").strip()
        prompt_lines = ["[QUESTION FOR USER]", q]
        if ctx_text:
            prompt_lines.extend(["", "Context:", ctx_text])
        if opts:
            prompt_lines.append("")
            prompt_lines.append("Options:")
            for i, opt in enumerate(opts, 1):
                prompt_lines.append(f"  {i}. {opt}")
        prompt_lines.append("")
        prompt_lines.append("Please reply with your answer.")
        prompt_text = "\n".join(prompt_lines)
        return ToolResult.success(
            {
                "question": q,
                "options": opts,
                "awaiting_user_response": True,
                "instruction": "Relay this question to the user in your assistant message and stop until they respond.",
            },
            code="USER_INPUT_REQUIRED",
            injected_user_input_segments=[{"type": "text", "text": prompt_text}],
        )


TOOL = AskUserTool
