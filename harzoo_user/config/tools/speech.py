"""Speech — speech-to-text and text-to-speech."""


from __future__ import annotations

import base64
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from harzoo.agent.kernel.tool import Tool, ToolResult, resolve_workspace_path, workspace_root_from

TOOL_VERSION = "2026-06-29"


class SpeechTool(Tool):
    """Transcribe audio (STT) or synthesize speech (TTS)."""

    name = "Speech"
    description = (
        "Speech tools. Actions: transcribe (whisper/openai), speak (edge-tts). "
        "Transcribe: pip install openai + OPENAI_API_KEY, or whisper CLI. "
        "Speak: pip install edge-tts."
    )
    parameters = {
        "properties": {
            "action": {"type": "string", "enum": ["transcribe", "speak"]},
            "file_path": {"type": "string", "description": "Audio file for transcribe"},
            "text": {"type": "string", "description": "Text for speak action"},
            "output_path": {"type": "string", "description": "Output audio path for speak"},
            "voice": {"type": "string", "description": "TTS voice name", "default": "en-US-AriaNeural"},
            "language": {"type": "string", "description": "Language hint for transcribe", "default": "auto"},
        },
        "required": ["action"],
    }

    def _transcribe_openai(self, path: Path) -> str:
        import json
        import urllib.request

        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            raise ValueError("OPENAI_API_KEY required for OpenAI transcription")
        base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        boundary = "----HarzooBoundary"
        audio_bytes = path.read_bytes()
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode() + audio_bytes + (
            f"\r\n--{boundary}\r\n"
            f'Content-Disposition: form-data; name="model"\r\n\r\n'
            f"whisper-1\r\n"
            f"--{boundary}--\r\n"
        ).encode()
        req = urllib.request.Request(
            f"{base_url}/audio/transcriptions",
            data=body,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return str(data.get("text") or "")

    def execute(
        self,
        action: str,
        file_path: str | None = None,
        text: str | None = None,
        output_path: str | None = None,
        voice: str = "en-US-AriaNeural",
        language: str = "auto",
        **kwargs: Any,
    ) -> ToolResult:
        root = workspace_root_from(kwargs.get("ctx"))
        act = str(action or "").strip().lower()

        if act == "transcribe":
            if not file_path:
                return ToolResult.failure("file_path required for transcribe", code="INVALID_ARGUMENTS")
            path = resolve_workspace_path(file_path, root)
            if not path.is_file():
                return ToolResult.failure(f"File not found: {file_path}", code="PATH_NOT_FOUND")
            try:
                transcript = self._transcribe_openai(path)
            except ValueError as e:
                return ToolResult.failure(str(e), code="MISSING_API_KEY")
            except Exception:
                try:
                    proc = subprocess.run(
                        ["whisper", str(path), "--model", "base", "--output_format", "txt"],
                        capture_output=True,
                        text=True,
                        timeout=300,
                    )
                    if proc.returncode != 0:
                        return ToolResult.failure(
                            "Transcription failed. Install openai API key or whisper CLI.",
                            code="CAPABILITY_UNAVAILABLE",
                            data={"stderr": proc.stderr[:2000]},
                        )
                    txt_path = path.with_suffix(".txt")
                    transcript = txt_path.read_text(encoding="utf-8") if txt_path.is_file() else proc.stdout
                except FileNotFoundError:
                    return ToolResult.failure("No transcription backend available", code="CAPABILITY_UNAVAILABLE")
            return ToolResult.success({"file_path": str(path), "transcript": transcript.strip()})

        if act == "speak":
            content = str(text or "").strip()
            if not content:
                return ToolResult.failure("text required for speak", code="INVALID_ARGUMENTS")
            out = resolve_workspace_path(output_path, root) if output_path else Path(tempfile.gettempdir()) / "harzoo_tts.mp3"
            try:
                import asyncio

                import edge_tts  # type: ignore

                async def _run() -> None:
                    communicate = edge_tts.Communicate(content, str(voice or "en-US-AriaNeural"))
                    await communicate.save(str(out))

                asyncio.run(_run())
            except ImportError:
                return ToolResult.failure("edge-tts required: pip install edge-tts", code="CAPABILITY_UNAVAILABLE")
            except Exception as e:
                return ToolResult.failure(f"{type(e).__name__}: {e}", code="TTS_ERROR")
            return ToolResult.success({"output_path": str(out.resolve()), "voice": voice, "chars": len(content), "saved": True})

        return ToolResult.failure(f"Unknown action: {action}", code="INVALID_ARGUMENTS")


TOOL = SpeechTool
