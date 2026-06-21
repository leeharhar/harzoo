"""Shell command tool implementation."""


from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from harzoo.agent.kernel.tool import Tool, ToolResult

TOOL_VERSION = "2026-05-30"

MAX_OUTPUT_CHARS = 200_000
ENCODING_POLICY = "utf8_only"


def _resolve_path(path: str) -> Path:
    """统一把调用方传入的 cwd 解析成绝对路径，保证不同命令行为一致。"""

    p = Path(path).expanduser()
    if p.is_absolute():
        return p.resolve()
    return (Path.cwd() / p).resolve()


def _decode_shell_bytes(raw: bytes | None) -> tuple[str, str, bool]:
    """采用 UTF-8 单一路径：优先 utf-8-sig（兼容 BOM），失败后 replace 兜底。"""

    if not raw:
        return "", "utf-8", False
    try:
        return raw.decode("utf-8-sig"), "utf-8", False
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace"), "utf-8 (replace)", True


def _truncate_text(value: str, *, limit: int = MAX_OUTPUT_CHARS) -> tuple[str, bool]:
    """单次 stdout/stderr 截断到固定上限，避免大输出撑爆上下文。"""

    if len(value) <= limit:
        return value, False
    return value[:limit], True


def _wrap_powershell_command(command: str) -> str:
    """执行前固定错误策略与 UTF-8 编码，减少 PowerShell 平台差异。"""

    return (
        "& { "
        "$ErrorActionPreference='Stop'; "
        "$ProgressPreference='SilentlyContinue'; "
        "[Console]::InputEncoding = [System.Text.UTF8Encoding]::UTF8; "
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::UTF8; "
        "$OutputEncoding = [System.Text.UTF8Encoding]::UTF8; "
        + command
        + " }"
    )


def _resolve_shell_command(command: str) -> tuple[list[str], str, dict[str, str]]:
    """固定主 shell：Windows 使用 PowerShell，macOS/Linux 使用 Bash。"""

    if os.name == "nt":
        shell_bin = "powershell.exe"
        if not shutil.which(shell_bin):
            raise ValueError(
                "Current agent requires powershell on Windows, but it was not found. "
                "Please install/enable PowerShell and retry."
            )
        ps_command = _wrap_powershell_command(command)
        return [
            shell_bin,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            ps_command,
        ], "powershell", {}

    shell_bin = shutil.which("bash")
    if not shell_bin:
        raise ValueError(
            "Current agent requires bash on Unix, but it was not found. "
            "Please install/enable bash and retry."
        )
    return [
        shell_bin,
        "--noprofile",
        "--norc",
        "-c",
        command,
    ], "bash", {"LC_ALL": "C.UTF-8", "LANG": "C.UTF-8", "PYTHONIOENCODING": "UTF-8"}

class ShellTool(Tool):
    """命令执行工具：Windows 固定 PowerShell，macOS/Linux 固定 Bash。"""

    name = "Shell"
    description = (
        "Run shell commands with fixed shell syntax."
        " Windows only accepts PowerShell syntax; macOS/Linux only accepts Bash syntax."
    )
    parameters = {
        "properties": {
            "command": {"type": "string", "description": "Shell command to run"},
            "description": {"type": "string", "description": "Short description (optional)"},
            "timeout": {"type": "integer", "description": "Timeout in ms (default 120000, max 600000)"},
            "cwd": {"type": "string", "description": "Working directory", "default": "."},
        },
        "required": ["command"],
    }

    def execute(
        self,
        command: str,
        description: str = "",
        timeout: int | None = None,
        cwd: str = ".",
        **kwargs: Any,
    ) -> ToolResult:
        """执行命令并返回标准化结果；不做多 shell 自动切换。"""

        if not str(command).strip():
            return ToolResult.failure("command must not be empty", code="INVALID_ARGUMENTS")
        if not str(cwd).strip():
            return ToolResult.failure("cwd must not be empty", code="INVALID_ARGUMENTS")
        timeout_ms = max(1, min(600_000, timeout or 120000))
        cwd_path = str(_resolve_path(cwd))
        shell_label = "unknown"
        try:
            shell_command, shell_label, shell_env_overrides = _resolve_shell_command(command)
            env = os.environ.copy()
            env.update(shell_env_overrides)
            result = subprocess.run(
                shell_command,
                shell=False,
                cwd=cwd_path,
                capture_output=True,
                text=False,
                timeout=timeout_ms / 1000.0,
                env=env,
            )
            out, out_enc, out_replaced = _decode_shell_bytes(result.stdout)
            err, err_enc, err_replaced = _decode_shell_bytes(result.stderr)
            out, out_truncated = _truncate_text(out)
            err, err_truncated = _truncate_text(err)
            payload_base = {
                "exit_code": result.returncode,
                "stdout": out,
                "stderr": err,
                "stdout_truncated": out_truncated,
                "stderr_truncated": err_truncated,
                "stdout_encoding": out_enc,
                "stderr_encoding": err_enc,
                "stdout_had_replacements": out_replaced,
                "stderr_had_replacements": err_replaced,
                "cwd": cwd_path,
                "requested_cwd": cwd,
                "resolved_cwd": cwd_path,
                "command": command,
                "shell_used": shell_label,
                "encoding_policy": ENCODING_POLICY,
                "description": description,
            }
            if result.returncode != 0:
                return ToolResult.failure(
                    f"Shell command failed with exit code {result.returncode} (shell: {shell_label})",
                    code="SHELL_EXIT_NONZERO",
                    data=payload_base,
                )
            return ToolResult.success(payload_base)
        except subprocess.TimeoutExpired as e:
            out, out_enc, out_replaced = _decode_shell_bytes(
                e.stdout if isinstance(e.stdout, (bytes, bytearray)) else None
            )
            err, err_enc, err_replaced = _decode_shell_bytes(
                e.stderr if isinstance(e.stderr, (bytes, bytearray)) else None
            )
            out, out_truncated = _truncate_text(out)
            err, err_truncated = _truncate_text(err)
            return ToolResult.failure(
                f"Timeout ({timeout_ms}ms) on {shell_label}",
                code="TIMEOUT",
                data={
                    "command": command,
                    "cwd": cwd_path,
                    "requested_cwd": cwd,
                    "resolved_cwd": cwd_path,
                    "shell_used": shell_label,
                    "stdout": out,
                    "stderr": err,
                    "stdout_truncated": out_truncated,
                    "stderr_truncated": err_truncated,
                    "stdout_encoding": out_enc,
                    "stderr_encoding": err_enc,
                    "stdout_had_replacements": out_replaced,
                    "stderr_had_replacements": err_replaced,
                    "encoding_policy": ENCODING_POLICY,
                },
            )
        except FileNotFoundError:
            return ToolResult.failure(
                f"Working directory does not exist: {cwd_path}",
                code="PATH_NOT_FOUND",
                data={
                    "command": command,
                    "cwd": cwd_path,
                    "requested_cwd": cwd,
                    "resolved_cwd": cwd_path,
                    "shell_used": shell_label,
                },
            )
        except PermissionError:
            return ToolResult.failure(
                f"Working directory is not accessible: {cwd_path}",
                code="PATH_NOT_ACCESSIBLE",
                data={
                    "command": command,
                    "cwd": cwd_path,
                    "requested_cwd": cwd,
                    "resolved_cwd": cwd_path,
                    "shell_used": shell_label,
                },
            )
        except ValueError as e:
            return ToolResult.failure(
                f"{e}",
                code="SHELL_UNAVAILABLE",
                data={
                    "command": command,
                    "cwd": cwd_path,
                    "requested_cwd": cwd,
                    "resolved_cwd": cwd_path,
                    "shell_used": shell_label,
                },
            )
        except Exception as e:
            return ToolResult.failure(
                f"{e}",
                code="TOOL_EXCEPTION",
                data={
                    "command": command,
                    "cwd": cwd_path,
                    "requested_cwd": cwd,
                    "resolved_cwd": cwd_path,
                    "shell_used": shell_label,
                },
            )


TOOL = ShellTool
