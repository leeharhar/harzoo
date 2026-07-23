"""智能体配置目录布局与路径发现。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from harzoo.agent.components.util import load_yaml_front_matter_markdown

HARZOO_USER_DIR_NAME = "harzoo_user"


@dataclass(frozen=True, slots=True)
class ConfigPaths:
    workspace_root: Path
    user_root: Path
    config_root: Path
    profiles_root: Path
    tools_root: Path
    skills_root: Path
    data_root: Path
    startup_profile_path: Path
    placeholder_values: dict[str, str]


def default_user_root() -> Path:
    """仓库/安装旁默认的 harzoo_user 目录。"""

    return Path(__file__).resolve().parents[3] / HARZOO_USER_DIR_NAME


def _resolve_user_layout(entry: Path) -> tuple[Path, Path, Path]:
    """解析 (user_root, config_root, data_root)。entry 可为 harzoo_user 或旧版扁平 config 目录。"""

    entry = entry.expanduser().resolve()
    nested_config = entry / "config"
    if nested_config.is_dir() and (nested_config / "config.json").is_file():
        return entry, nested_config, entry / "data"

    if (entry / "config.json").is_file():
        return entry.parent, entry, entry / "data"

    return entry, entry / "config", entry / "data"


def _parse_placeholder_values(payload: dict[str, object], config_file_path: Path) -> dict[str, str]:
    raw = payload.get("placeholder_values")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"{config_file_path} 'placeholder_values' must be a JSON object")

    result: dict[str, str] = {}
    for key, value in raw.items():
        name = str(key).strip()
        if not name:
            continue
        if value is None:
            raise ValueError(f"{config_file_path} placeholder_values[{key!r}] must not be null")
        result[name] = str(value).strip()
    return result


def _load_runtime_config(config_file_path: Path) -> tuple[str, dict[str, str]]:
    config_template = (
        '{\n'
        '  "startup_profile": "xxxx.md",\n'
        '  "placeholder_values": {}\n'
        '}\n'
    )
    if not config_file_path.is_file():
        config_file_path.parent.mkdir(parents=True, exist_ok=True)
        config_file_path.write_text(config_template, encoding="utf-8")
        return "xxxx.md", {}

    try:
        payload = json.loads(config_file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {config_file_path}: {exc.msg}") from exc

    if not isinstance(payload, dict):
        raise ValueError(f"{config_file_path} must be a JSON object")

    raw_startup_profile = payload.get("startup_profile")
    startup_profile = str(raw_startup_profile or "").strip()
    if not startup_profile:
        startup_profile = "xxxx.md"

    placeholder_values = _parse_placeholder_values(payload, config_file_path)
    return startup_profile, placeholder_values


def list_profile_markdown_files(profiles_root: Path) -> list[Path]:
    root = profiles_root.resolve()
    if not root.is_dir():
        return []
    return sorted(p.resolve() for p in root.rglob("*.md") if p.is_file())


def _resolve_profile_markdown(
    raw: str,
    *,
    profiles_root: Path,
    default: Path | None,
) -> Path:
    text = str(raw).strip()
    if not text:
        if default is None:
            raise FileNotFoundError("Profile name is required")
        return default.resolve()

    root = profiles_root.resolve()
    expanded = Path(text).expanduser()

    if expanded.is_absolute():
        resolved = expanded.resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"Profile not found: {resolved}")
        if resolved.suffix.lower() != ".md":
            raise ValueError(f"Profile must be a markdown file: {resolved}")
        return resolved

    if any(part in ("..", ".") for part in expanded.parts):
        raise ValueError("Profile path must not contain '.' or '..'")

    candidate = (root / expanded).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Profile path must stay under {root}") from exc

    if candidate.suffix.lower() != ".md":
        with_md = candidate.with_suffix(".md")
        if with_md.is_file():
            return with_md
    if candidate.is_file():
        return candidate

    stem = expanded.stem if expanded.suffix else text
    direct = root / f"{stem}.md"
    if direct.is_file():
        return direct

    catalog = list_profile_markdown_files(root)
    matches = [p for p in catalog if p.stem == Path(stem).stem]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        refs = ", ".join(p.relative_to(root).as_posix() for p in matches)
        raise FileNotFoundError(f"Profile {text!r} is ambiguous ({refs})")

    normalized = text.lower()
    for path in catalog:
        try:
            meta, _ = load_yaml_front_matter_markdown(path)
        except (OSError, ValueError):
            continue
        if str(meta.get("name") or "").strip().lower() == normalized:
            return path

    raise FileNotFoundError(f"Profile {text!r} not found under {root}")


def resolve_profile_path(raw: str, paths: ConfigPaths) -> Path:
    return _resolve_profile_markdown(
        raw,
        profiles_root=paths.profiles_root,
        default=paths.startup_profile_path,
    )


def _resolve_startup_profile(profiles_root: Path, startup_profile: str) -> Path:
    text = startup_profile.strip() or "xxxx.md"
    if Path(text).is_absolute():
        raise ValueError("config.json 'startup_profile' must be relative under profiles/")

    try:
        return _resolve_profile_markdown(text, profiles_root=profiles_root, default=None)
    except FileNotFoundError as exc:
        if "ambiguous" in str(exc):
            raise ValueError(str(exc)) from exc
        requested = Path(text)
        candidate = (profiles_root / requested).resolve()
        if candidate.suffix.lower() != ".md":
            candidate = candidate.with_suffix(".md")
        return candidate


def prepare_config_paths(
    user_root: Path | str,
    *,
    workspace_root: Path | str | None = None,
) -> ConfigPaths:
    user_root_path, config_root_path, data_root_path = _resolve_user_layout(Path(user_root))
    resolved_workspace = (
        Path(workspace_root).expanduser().resolve()
        if workspace_root is not None
        else Path.cwd().resolve()
    )

    user_root_path.mkdir(parents=True, exist_ok=True)
    config_root_path.mkdir(parents=True, exist_ok=True)
    data_root_path.mkdir(parents=True, exist_ok=True)

    config_file_path = config_root_path / "config.json"
    profiles_root = config_root_path / "profiles"
    tools_root = config_root_path / "tools"
    skills_root = config_root_path / "skills"
    profiles_root.mkdir(parents=True, exist_ok=True)
    tools_root.mkdir(parents=True, exist_ok=True)
    skills_root.mkdir(parents=True, exist_ok=True)

    startup_profile, placeholder_values = _load_runtime_config(config_file_path)
    startup_profile_path = _resolve_startup_profile(profiles_root, startup_profile)

    return ConfigPaths(
        workspace_root=resolved_workspace,
        user_root=user_root_path,
        config_root=config_root_path,
        profiles_root=profiles_root,
        tools_root=tools_root,
        skills_root=skills_root,
        data_root=data_root_path,
        startup_profile_path=startup_profile_path,
        placeholder_values=placeholder_values,
    )


def list_skill_manifests(paths: ConfigPaths) -> list[Path]:
    return sorted({p.resolve() for p in paths.skills_root.glob("*.md") if p.is_file()})
