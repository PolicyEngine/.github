"""Changed files and their before/after text, from git or the GitHub API."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .git_paths import name_status, show
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

    def changed_files(self) -> list[str]:
        """Each changed file's path at head (a deleted file's at base).

        ``-z`` keeps a path Git would quote, or that holds a newline or tab,
        whole, and each record is parsed by its status: a rename's base path is
        kept for ``read``. ``--no-relative`` lists paths from the top of the
        tree even if the ``diff.relative`` setting is on. Output the record
        grammar doesn't account for raises rather than dropping a file.
        """
        out = subprocess.run(
            [
                "git",
                "-C",
                str(self.root),
                "diff",
                "--name-status",
                "--no-relative",
                "-M",
                "-z",
                self.base,
                self.head,
            ],
            capture_output=True,
        )
        if out.returncode != 0:
            raise RuntimeError(out.stderr.decode("utf-8", "replace").strip())
        files = []
        for change in name_status(out.stdout):
            if change.status == "R" and change.source is not None:
                self._renames[change.path] = change.source
            # A copy's head path is a new file: its base side reads as absent.
            files.append(change.path)
        return files

    def read(self, path: str, side: str) -> str | None:
        ref = self.base if side == "base" else self.head
        if side == "base":
            path = self._renames.get(path, path)
        return show(self.root, ref, path)


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
