"""Git — structured version control operations."""


from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from harzoo.agent.kernel.tool import Tool, ToolResult, resolve_workspace_path, workspace_root_from

TOOL_VERSION = "2026-06-29"

MAX_OUTPUT_CHARS = 100_000
_ALLOWED_ACTIONS = frozenset({"status", "diff", "log", "branch", "checkout", "add", "commit", "show", "rev_parse"})


def _truncate(text: str) -> tuple[str, bool]:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text, False
    return text[:MAX_OUTPUT_CHARS], True


def _run_git(args: list[str], *, cwd: Path, timeout: int = 60) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, proc.stdout, proc.stderr


class GitTool(Tool):
    """Run common git commands with structured output."""

    name = "Git"
    description = (
        "Git operations: status, diff, log, branch, checkout, add, commit, show, rev_parse. "
        "Provide action and optional args (paths, message, ref, etc.)."
    )
    parameters = {
        "properties": {
            "action": {
                "type": "string",
                "enum": sorted(_ALLOWED_ACTIONS),
                "description": "Git subcommand to run",
            },
            "cwd": {"type": "string", "description": "Repository working directory", "default": "."},
            "paths": {"type": "array", "items": {"type": "string"}, "description": "Paths for add/diff/status"},
            "message": {"type": "string", "description": "Commit message (commit action)"},
            "ref": {"type": "string", "description": "Branch/ref for checkout/log/show"},
            "staged": {"type": "boolean", "description": "Diff staged changes only", "default": False},
            "max_count": {"type": "integer", "description": "Max log entries (default 20)", "default": 20},
        },
        "required": ["action"],
    }

    def execute(
        self,
        action: str,
        cwd: str = ".",
        paths: list[str] | None = None,
        message: str | None = None,
        ref: str | None = None,
        staged: bool = False,
        max_count: int = 20,
        **kwargs: Any,
    ) -> ToolResult:
        act = str(action or "").strip().lower()
        if act not in _ALLOWED_ACTIONS:
            return ToolResult.failure(f"Unsupported action: {action}", code="INVALID_ARGUMENTS")
        repo = resolve_workspace_path(str(cwd or ".").strip() or ".", workspace_root_from(kwargs.get("ctx")))
        if not repo.is_dir():
            return ToolResult.failure(f"Not a directory: {cwd}", code="PATH_NOT_FOUND")
        git_dir = repo / ".git"
        if not git_dir.exists():
            return ToolResult.failure(f"Not a git repository: {repo}", code="NOT_GIT_REPO")

        path_args = [str(p) for p in (paths or []) if str(p).strip()]
        cmd: list[str] = []

        if act == "status":
            cmd = ["status", "--short", "--branch", *path_args]
        elif act == "diff":
            cmd = ["diff"]
            if staged:
                cmd.append("--cached")
            cmd.extend(path_args)
        elif act == "log":
            try:
                n = max(1, min(100, int(max_count)))
            except (TypeError, ValueError):
                return ToolResult.failure("max_count must be an integer", code="INVALID_ARGUMENTS")
            cmd = ["log", f"-{n}", "--oneline", "--decorate"]
            if ref:
                cmd.append(str(ref))
        elif act == "branch":
            cmd = ["branch", "-a"]
        elif act == "checkout":
            if not ref:
                return ToolResult.failure("ref is required for checkout", code="INVALID_ARGUMENTS")
            cmd = ["checkout", str(ref), *path_args]
        elif act == "add":
            cmd = ["add", *(path_args or ["."])]
        elif act == "commit":
            msg = str(message or "").strip()
            if not msg:
                return ToolResult.failure("message is required for commit", code="INVALID_ARGUMENTS")
            cmd = ["commit", "-m", msg]
        elif act == "show":
            cmd = ["show", "--stat"]
            if ref:
                cmd.append(str(ref))
        elif act == "rev_parse":
            cmd = ["rev-parse", str(ref or "HEAD")]

        try:
            code, stdout, stderr = _run_git(cmd, cwd=repo)
        except FileNotFoundError:
            return ToolResult.failure("git executable not found in PATH", code="CAPABILITY_UNAVAILABLE")
        except subprocess.TimeoutExpired:
            return ToolResult.failure("git command timed out", code="TIMEOUT")

        out, out_trunc = _truncate(stdout)
        err, err_trunc = _truncate(stderr)
        ok = code == 0
        data = {
            "action": act,
            "cwd": str(repo),
            "command": ["git", *cmd],
            "exit_code": code,
            "stdout": out,
            "stderr": err,
            "stdout_truncated": out_trunc,
            "stderr_truncated": err_trunc,
        }
        if ok:
            return ToolResult.success(data)
        return ToolResult.failure(stderr.strip() or f"git exited with code {code}", code="GIT_ERROR", data=data)


TOOL = GitTool
