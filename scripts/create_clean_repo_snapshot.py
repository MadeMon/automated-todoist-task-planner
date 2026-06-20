#!/usr/bin/env python3
"""Create a pruned copy of this repository and package it as a zip archive."""

from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path


EXCLUDED_PATHS: tuple[str, ...] = (
    ".venv",
    ".github",
    ".vscode",
    "other",
    "scripts/query-todoist-tasks-by-due-date.py",
    "scripts/reset_pa026_playground_tasks.py",
    "test_schedules*",
    ".env",
    "AGENTS.md",
    "CONTINUE.md",
    "IDEAS.md",
    "mlflow.db",
    "mlruns.db",
    "mydb.sqlite",
    "PLAN.md",
    "scripts/query-todoist-tasks-by-due-date.sh",
    ".gitignore",
    "__pycache__",
    "build",
    ".git",
    ".pdm-python",
    ".python-version",
    "tests/test.py"
)


def _matches_excluded_path(relative_path: Path) -> bool:
    relative_text = relative_path.as_posix()
    return any(relative_path.match(pattern) for pattern in EXCLUDED_PATHS) or any(
        relative_text == pattern or relative_text.startswith(f"{pattern}/")
        for pattern in EXCLUDED_PATHS
        if "*" not in pattern
    )


def _remove_excluded_paths(root: Path) -> list[str]:
    removed: list[str] = []

    for path in sorted(root.rglob("*"), key=lambda candidate: len(candidate.parts), reverse=True):
        if not path.exists():
            continue

        relative_path = path.relative_to(root)
        if not _matches_excluded_path(relative_path):
            continue

        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        removed.append(relative_path.as_posix())

    return removed


def _default_output_path(repo_root: Path) -> Path:
    return repo_root.parent / f"{repo_root.name}_clean_snapshot.zip"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Copy this repository, remove configured files and folders from the copy, "
            "and package the result as a zip archive."
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Zip file to create (default: <repo-name>_clean_snapshot.zip next to the repo).",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    output_path = args.output or _default_output_path(repo_root)
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=f"{repo_root.name}_snapshot_") as temp_dir:
        staging_root = Path(temp_dir) / repo_root.name
        shutil.copytree(repo_root, staging_root)

        removed_paths = _remove_excluded_paths(staging_root)

        print(f"Staged copy of repository created at: {staging_root}")

        archive_base_name = output_path.with_suffix("")
        if output_path.exists():
            output_path.unlink()

        shutil.make_archive(
            base_name=str(archive_base_name),
            format="zip",
            root_dir=staging_root.parent,
            base_dir=staging_root.name,
        )

    print(f"Created zip archive: {output_path}")
    print(f"Removed {len(removed_paths)} paths from the staged copy.")
    for removed_path in removed_paths:
        print(f"- {removed_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())