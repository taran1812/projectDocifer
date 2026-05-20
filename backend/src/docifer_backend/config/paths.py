from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[4]


def resolve_project_path(path: str | Path) -> Path:
    """Resolve a project-relative path against the repository root."""

    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return PROJECT_ROOT / candidate


def display_path(path: str | Path) -> str:
    """Return a stable project-relative path when possible."""

    candidate = Path(path).resolve()
    try:
        return candidate.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(candidate)
