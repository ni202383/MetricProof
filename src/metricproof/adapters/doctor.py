"""Read-only local environment adapter used by ``metricproof doctor``."""

import os
import subprocess
import sys
from pathlib import Path, PurePath

from metricproof.application.doctor import GitInspection, GitState, LatexDiscovery

GIT_TIMEOUT_SECONDS = 3.0
MAX_SCAN_DEPTH = 6
MAX_SCAN_FILES = 1000
IGNORED_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".svn",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "htmlcov",
        "node_modules",
        "venv",
    }
)
_IGNORED_DIRECTORY_NAMES_CASEFOLDED = frozenset(name.casefold() for name in IGNORED_DIRECTORY_NAMES)


def is_ignored_relative_path(path: PurePath) -> bool:
    """Return whether any path component belongs to a pruned directory."""

    return any(part.casefold() in _IGNORED_DIRECTORY_NAMES_CASEFOLDED for part in path.parts)


class LocalDoctorProbe:
    """Inspect the local interpreter, filesystem, and Git without writing."""

    def python_version(self) -> tuple[int, int, int]:
        return sys.version_info.major, sys.version_info.minor, sys.version_info.micro

    def inspect_git(self, current_directory: Path) -> GitInspection:
        command = ["git", "-C", str(current_directory), "rev-parse", "--show-toplevel"]
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=GIT_TIMEOUT_SECONDS,
            )
        except FileNotFoundError:
            return GitInspection(GitState.UNAVAILABLE, detail="git executable was not found")
        except subprocess.TimeoutExpired:
            return GitInspection(
                GitState.TIMEOUT,
                detail=f"git command exceeded {GIT_TIMEOUT_SECONDS:g} seconds",
            )
        except OSError as error:
            return GitInspection(GitState.ERROR, detail=f"git could not start: {error}")

        output = completed.stdout.strip()
        detail = completed.stderr.strip()
        if completed.returncode == 0 and output:
            return GitInspection(GitState.REPOSITORY, root=Path(output).resolve())
        if "not a git repository" in detail.casefold():
            return GitInspection(GitState.NOT_REPOSITORY, detail=detail)
        return GitInspection(
            GitState.ERROR,
            detail=detail or f"git exited with status {completed.returncode}",
        )

    def find_project_root(self, current_directory: Path, git_root: Path | None) -> Path | None:
        current_directory = current_directory.resolve()
        if git_root is not None:
            resolved_git_root = git_root.resolve()
            if _is_within(current_directory, resolved_git_root):
                return resolved_git_root

        for candidate in (current_directory, *current_directory.parents):
            if (candidate / ".metricproof").is_dir():
                return candidate
            if (candidate / "pyproject.toml").is_file() and (
                candidate / "src" / "metricproof"
            ).is_dir():
                return candidate
        return None

    def has_metricproof_directory(self, project_root: Path) -> bool:
        return (project_root / ".metricproof").is_dir()

    def find_latex_files(self, project_root: Path) -> LatexDiscovery:
        project_root = project_root.resolve()
        files: list[Path] = []
        errors: list[str] = []
        truncated = False

        if not project_root.is_dir():
            return LatexDiscovery((), errors=(f"not a directory: {project_root}",))

        def record_error(error: OSError) -> None:
            errors.append(str(error))

        for current, directory_names, file_names in os.walk(
            project_root,
            topdown=True,
            onerror=record_error,
            followlinks=False,
        ):
            current_path = Path(current)
            relative_directory = current_path.relative_to(project_root)
            depth = len(relative_directory.parts)

            directory_names[:] = sorted(
                name
                for name in directory_names
                if name.casefold() not in _IGNORED_DIRECTORY_NAMES_CASEFOLDED
                and depth < MAX_SCAN_DEPTH
            )

            for file_name in sorted(file_names):
                if Path(file_name).suffix.casefold() != ".tex":
                    continue
                files.append(current_path / file_name)
                if len(files) >= MAX_SCAN_FILES:
                    truncated = True
                    directory_names.clear()
                    break
            if truncated:
                break

        return LatexDiscovery(tuple(files), truncated=truncated, errors=tuple(errors))


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
