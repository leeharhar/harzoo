"""智能体配置目录布局与路径发现。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ConfigPaths:
    profiles_root: Path
    tools_root: Path
    skills_root: Path
    startup_profile_path: Path


def _load_runtime_config(config_file_path: Path) -> str:
    config_template = '{\n  "startup_profile": "xxxx.md"\n}\n'
    if not config_file_path.is_file():
        config_file_path.write_text(config_template, encoding="utf-8")
        return "xxxx.md"

    try:
        payload = json.loads(config_file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {config_file_path}: {exc.msg}") from exc

    if not isinstance(payload, dict):
        raise ValueError(f"{config_file_path} must be a JSON object")

    raw_startup_profile = payload.get("startup_profile")
    startup_profile = str(raw_startup_profile or "").strip()
    if not startup_profile:
        return "xxxx.md"

    return startup_profile


def _resolve_startup_profile(profiles_root: Path, startup_profile: str) -> Path:
    requested = Path(startup_profile.strip())
    if requested.is_absolute() or any(part in ("..", ".") for part in requested.parts):
        raise ValueError("config.json 'startup_profile' must be a file name under profiles/")
    if len(requested.parts) != 1:
        raise ValueError("config.json 'startup_profile' must not include directory separators")

    candidate = profiles_root / requested.name
    if candidate.suffix.lower() != ".md":
        candidate = candidate.with_suffix(".md")
    return candidate.resolve()


def prepare_config_paths(config_root: Path | str) -> ConfigPaths:
    config_root_path = Path(config_root).expanduser().resolve()

    config_file_path = config_root_path / "config.json"
    profiles_root = config_root_path / "profiles"
    tools_root = config_root_path / "tools"
    skills_root = config_root_path / "skills"
    config_root_path.mkdir(parents=True, exist_ok=True)
    profiles_root.mkdir(parents=True, exist_ok=True)
    tools_root.mkdir(parents=True, exist_ok=True)
    skills_root.mkdir(parents=True, exist_ok=True)

    startup_profile = _load_runtime_config(config_file_path)
    startup_profile_path = _resolve_startup_profile(profiles_root, startup_profile)

    return ConfigPaths(
        profiles_root=profiles_root,
        tools_root=tools_root,
        skills_root=skills_root,
        startup_profile_path=startup_profile_path,
    )


def list_subagent_paths(paths: ConfigPaths) -> list[Path]:
    return sorted({p.resolve() for p in paths.profiles_root.glob("*.md") if p.is_file()})


def list_skill_manifests(paths: ConfigPaths) -> list[Path]:
    return sorted({p.resolve() for p in paths.skills_root.glob("*.md") if p.is_file()})
