from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class GitSnapshot:
    repository_path: str
    head: str
    branch: str
    status: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(arguments)} failed")
    return result.stdout.strip()


def repository_root(path: str | Path) -> Path:
    candidate = Path(path).expanduser().resolve()
    root = _git(candidate, "rev-parse", "--show-toplevel")
    return Path(root).resolve()


def snapshot(path: str | Path) -> GitSnapshot:
    root = repository_root(path)
    return GitSnapshot(
        repository_path=str(root),
        head=_git(root, "rev-parse", "HEAD"),
        branch=_git(root, "branch", "--show-current"),
        status=_git(root, "status", "--porcelain=v1", "--untracked-files=all"),
    )


def same_worktree(before: GitSnapshot, after: GitSnapshot) -> bool:
    return before == after

