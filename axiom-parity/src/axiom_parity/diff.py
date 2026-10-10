"""Changed files and their before/after text, from git or the GitHub API."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .github import GitHub, NotFound


class LocalDiff:
    """A diff between two refs of a local clone.

    In CI the clone is the PR's merge commit fetched with depth 2, so
    ``HEAD^1..HEAD`` is exactly what merging the PR would change.
    """

    def __init__(self, root: str | Path, base: str, head: str) -> None:
        self.root = Path(root)
        self.base = base
        self.head = head
        self._renames: dict[str, str] = {}

    def _git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True)

    def changed_files(self) -> list[str]:
        out = self._git("diff", "--name-status", "-M", self.base, self.head)
        if out.returncode != 0:
            raise RuntimeError(out.stderr.strip())
        files = []
        for line in out.stdout.splitlines():
            parts = line.split("\t")
            if parts[0].startswith("R") and len(parts) == 3:
                self._renames[parts[2]] = parts[1]
                files.append(parts[2])
            elif len(parts) >= 2:
                files.append(parts[-1])
        return files

    def read(self, path: str, side: str) -> str | None:
        ref = self.base if side == "base" else self.head
        if side == "base":
            path = self._renames.get(path, path)
        res = self._git("show", f"{ref}:{path}")
        return res.stdout if res.returncode == 0 else None


class ApiDiff:
    """A PR's diff read through the REST API (for runs without a checkout)."""

    def __init__(self, gh: GitHub, repo: str, pr: int) -> None:
        self.gh = gh
        self.repo = repo
        self.pr = pr
        pull = gh.pull(repo, pr)
        self.head = pull["head"]["sha"]
        compare = gh.get_json(f"/repos/{repo}/compare/{pull['base']['sha']}...{self.head}")
        self.base = compare.get("merge_base_commit", {}).get("sha") or pull["base"]["sha"]
        self._files = gh.pull_files(repo, pr)
        self._renames = {f["filename"]: f["previous_filename"] for f in self._files if f.get("previous_filename")}
        self._status = {f["filename"]: f.get("status") for f in self._files}

    def changed_files(self) -> list[str]:
        return [f["filename"] for f in self._files]

    def read(self, path: str, side: str) -> str | None:
        status = self._status.get(path)
        if side == "base" and status == "added" or side == "head" and status == "removed":
            return None
        ref = self.base if side == "base" else self.head
        if side == "base":
            path = self._renames.get(path, path)
        try:
            return self.gh.get_raw(self.repo, path, ref)
        except NotFound:
            return None
