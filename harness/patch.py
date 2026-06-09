"""Applies an implementer diff onto a fresh branch in the product repo, so every
attempt is isolated and trivially discardable. Pure git plumbing — no model calls."""
from __future__ import annotations
import subprocess
import tempfile
import os


def _git(repo: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)


def start_branch(repo: str, branch: str) -> None:
    _git(repo, "checkout", "-B", branch)


def apply_diff(repo: str, diff_text: str) -> tuple[bool, str]:
    """Returns (applied_ok, message). Does not commit."""
    if not diff_text.strip():
        return False, "empty diff"
    fd, path = tempfile.mkstemp(suffix=".diff")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(diff_text if diff_text.endswith("\n") else diff_text + "\n")
        proc = _git(repo, "apply", "--whitespace=nowarn", path)
        if proc.returncode != 0:
            return False, proc.stderr.strip()
        return True, "applied"
    finally:
        os.unlink(path)


def commit_all(repo: str, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)
