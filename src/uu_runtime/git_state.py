from __future__ import annotations

import hashlib
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class GitSnapshot:
    repository_path: str
    head: str
    branch: str
    status: str
    content_digest: str
    ignored_status: str

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


def _content_digest(root: Path) -> str:
    digest = hashlib.sha256()
    diff = subprocess.run(
        ["git", "-C", str(root), "diff", "--binary", "--no-ext-diff", "HEAD"],
        capture_output=True, check=False,
    )
    if diff.returncode != 0:
        raise RuntimeError(diff.stderr.decode(errors="replace").strip() or "git diff failed")
    digest.update(diff.stdout)
    untracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--others", "--exclude-standard", "-z"],
        capture_output=True, check=False,
    )
    if untracked.returncode != 0:
        raise RuntimeError(untracked.stderr.decode(errors="replace").strip() or "git ls-files failed")
    for raw_path in sorted(part for part in untracked.stdout.split(b"\0") if part):
        relative = raw_path.decode(errors="surrogateescape")
        candidate = root / relative
        digest.update(raw_path)
        if candidate.is_symlink():
            digest.update(candidate.readlink().as_posix().encode(errors="surrogateescape"))
        elif candidate.is_file():
            with candidate.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
    return digest.hexdigest()


def snapshot(path: str | Path) -> GitSnapshot:
    root = repository_root(path)
    return GitSnapshot(
        repository_path=str(root),
        head=_git(root, "rev-parse", "HEAD"),
        branch=_git(root, "branch", "--show-current"),
        status=_git(root, "status", "--porcelain=v1", "--untracked-files=all"),
        content_digest=_content_digest(root),
        ignored_status=_git(root, "status", "--porcelain=v1", "--ignored=matching", "--untracked-files=all"),
    )


def same_worktree(before: GitSnapshot, after: GitSnapshot) -> bool:
    return before == after
